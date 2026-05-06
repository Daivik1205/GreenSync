# nav/predictive_model.py
# PredictiveModel — combines Locality Sensitive Hashing (LSH) with a
# PyTorch GRU to forecast per-edge traffic state at multiple horizons.
#
# Architecture:
#   StateVector(t) ──▶ LSH.query() ──▶ k nearest historical patterns
#   Sequence[t-N..t] + LSH_context ──▶ GRU ──▶ {T+5, T+10, …, T+30}
#
# Training runs online: samples accumulate from the live simulation and a
# mini-batch SGD step fires every RETRAIN_INTERVAL simulation steps.
# The model can be saved to / loaded from disk between runs.

from __future__ import annotations

import os
from collections import deque

import numpy as np
import torch
import torch.nn as nn

from .traffic_manager import StateVector, SEQUENCE_LEN

# ── Forecast horizons (simulation steps, 1 step ≈ 1 second) ─────────────────
FORECAST_STEPS: list[int] = [5, 10, 15, 20, 25, 30]

# ── Dimensions ────────────────────────────────────────────────────────────────
STATE_DIM      = 4            # [speed, density, delay, congestion]
LSH_N_TABLES   = 6            # hash tables in the LSH index
LSH_N_BITS     = 8            # bits per hash → 256 buckets per table
LSH_TOP_K      = 5            # neighbours to retrieve
LSH_CTX_DIM    = STATE_DIM * LSH_TOP_K     # = 20
INPUT_DIM      = STATE_DIM + LSH_CTX_DIM   # = 24 per timestep
OUTPUT_DIM     = STATE_DIM * len(FORECAST_STEPS)  # = 24

# ── GRU hyper-parameters ─────────────────────────────────────────────────────
GRU_HIDDEN    = 128
GRU_LAYERS    = 2
GRU_DROPOUT   = 0.1

# ── Training ──────────────────────────────────────────────────────────────────
TRAIN_BUFFER_MAX = 4000   # max training samples kept in memory
BATCH_SIZE       = 64

_MODEL_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "model", "lsh_gru.pt")
)


# ── LSH index ─────────────────────────────────────────────────────────────────

class LSHIndex:
    """
    Random-hyperplane Locality Sensitive Hashing for fast k-NN retrieval.

    Each hash function h_w(x) = sign(w · x) where w ~ N(0,I).
    n_tables independent hash functions → n_tables buckets per query.
    Candidates from all matching buckets are re-ranked by L2 distance.
    """

    def __init__(
        self,
        dim:      int = STATE_DIM,
        n_tables: int = LSH_N_TABLES,
        n_bits:   int = LSH_N_BITS,
        seed:     int = 42,
    ):
        rng = np.random.default_rng(seed)
        # Planes shape: (n_tables, n_bits, dim)
        self.planes: np.ndarray = rng.standard_normal(
            (n_tables, n_bits, dim)
        ).astype(np.float32)
        self.n_tables = n_tables
        self.n_bits   = n_bits

        # Hash tables: table_idx → {hash_int: [global_idx, ...]}
        self._tables: list[dict[int, list[int]]] = [{} for _ in range(n_tables)]
        self._vectors: list[np.ndarray] = []   # stored query vectors
        self._labels:  list[np.ndarray] = []   # corresponding future states

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _hash(self, vec: np.ndarray, table: int) -> int:
        bits = (self.planes[table] @ vec) > 0   # (n_bits,) bool
        h = 0
        for b in bits:
            h = (h << 1) | int(b)
        return h

    # ── Public API ─────────────────────────────────────────────────────────────

    def add(self, vector: np.ndarray, future_state: np.ndarray):
        """Store a (current_state → future_state) training pair."""
        idx = len(self._vectors)
        self._vectors.append(vector.astype(np.float32))
        self._labels.append(future_state.astype(np.float32))
        for t in range(self.n_tables):
            h = self._hash(vector, t)
            self._tables[t].setdefault(h, []).append(idx)

    def query(self, vector: np.ndarray, k: int = LSH_TOP_K) -> np.ndarray:
        """
        Return concatenated k nearest historical future-states as context.
        Shape: (STATE_DIM * k,) = (20,) by default.
        Falls back to zero vector when the index is empty.
        """
        n_stored = len(self._vectors)
        if n_stored == 0:
            return np.zeros(STATE_DIM * k, dtype=np.float32)

        # Collect candidates from all hash tables
        candidates: set[int] = set()
        for t in range(self.n_tables):
            h = self._hash(vector, t)
            for idx in self._tables[t].get(h, []):
                candidates.add(idx)

        # Fall back to random sample if no bucket hit
        if not candidates:
            candidates = set(
                np.random.choice(n_stored, size=min(50, n_stored), replace=False)
            )

        cands = list(candidates)
        vecs  = np.stack([self._vectors[i] for i in cands])
        dists = np.linalg.norm(vecs - vector.astype(np.float32), axis=1)
        top_k = np.argsort(dists)[:k]

        results = [self._labels[cands[i]] for i in top_k]
        while len(results) < k:
            results.append(np.zeros(STATE_DIM, dtype=np.float32))

        return np.concatenate(results[:k]).astype(np.float32)   # (STATE_DIM*k,)

    def __len__(self) -> int:
        return len(self._vectors)


# ── GRU model ─────────────────────────────────────────────────────────────────

class GRUTrafficModel(nn.Module):
    """
    Multi-step traffic forecaster.

    Input:  (batch, seq_len, INPUT_DIM)  — state + LSH context per timestep
    Output: (batch, OUTPUT_DIM)          — flat forecast for all horizons
    Each horizon's output is clamped to [0, 1] via Sigmoid (normalised state).
    """

    def __init__(self):
        super().__init__()
        self.gru = nn.GRU(
            input_size=INPUT_DIM,
            hidden_size=GRU_HIDDEN,
            num_layers=GRU_LAYERS,
            dropout=GRU_DROPOUT,
            batch_first=True,
        )
        self.out = nn.Linear(GRU_HIDDEN, OUTPUT_DIM)

    def forward(self, x):
        out, _ = self.gru(x)
        preds = self.out(out[:, -1, :])
        return torch.sigmoid(preds)


class PredictiveModel:
    def __init__(self, device: str = "cpu"):
        self.device    = torch.device(device)
        self.lsh       = LSHIndex()
        self.model     = GRUTrafficModel().to(self.device)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        self.scheduler = torch.optim.lr_scheduler.StepLR(
            self.optimizer, step_size=500, gamma=0.5
        )
        self.loss_fn  = nn.MSELoss()
        self._buf: deque = deque(maxlen=TRAIN_BUFFER_MAX)
        self.train_steps: int = 0
        self.last_loss:   float | None = None

    # ── Input construction ────────────────────────────────────────────────────

    def _build_input(
        self, sequence: np.ndarray, current_vec: np.ndarray
    ) -> np.ndarray:
        """
        Augment each timestep in the sequence with the LSH context derived
        from current_vec.  Context is the same for all timesteps (broadcast).

        sequence:    (seq_len, STATE_DIM)
        current_vec: (STATE_DIM,)
        returns:     (seq_len, INPUT_DIM)
        """
        lsh_ctx = self.lsh.query(current_vec)           # (LSH_CTX_DIM,)
        ctx_tiled = np.tile(lsh_ctx, (sequence.shape[0], 1))  # (seq_len, LSH_CTX_DIM)
        return np.concatenate([sequence, ctx_tiled], axis=1).astype(np.float32)

    # ── Inference ─────────────────────────────────────────────────────────────

    def predict(
        self,
        sequence:    np.ndarray,    # (SEQUENCE_LEN, STATE_DIM)
        current_vec: np.ndarray,    # (STATE_DIM,)
    ) -> dict[int, np.ndarray]:
        """
        Return predicted StateVector arrays for each forecast horizon.
        {5: array(4,), 10: array(4,), 15: …, 30: …}
        """
        inp = self._build_input(sequence[-SEQUENCE_LEN:], current_vec)
        x   = torch.tensor(inp, dtype=torch.float32).unsqueeze(0).to(self.device)
        self.model.eval()
        with torch.no_grad():
            out = self.model(x).squeeze(0).cpu().numpy()  # (OUTPUT_DIM,)

        return {
            step: out[i * STATE_DIM: (i + 1) * STATE_DIM]
            for i, step in enumerate(FORECAST_STEPS)
        }

    # ── Online training ───────────────────────────────────────────────────────

    def add_sample(
        self,
        sequence:     np.ndarray,   # (SEQUENCE_LEN, STATE_DIM) — input
        future_state: np.ndarray,   # (STATE_DIM,)              — ground-truth label
    ):
        """
        Feed one training example into the replay buffer and the LSH index.
        Also used to populate the LSH historical store for context retrieval.
        """
        current_vec = sequence[-1]
        self.lsh.add(current_vec, future_state)

        inp = self._build_input(sequence, current_vec)  # (seq_len, INPUT_DIM)
        # Target: replicate future_state across all forecast horizons (simplified
        # label — real multi-horizon labels would require future rollouts; this
        # gives the model a meaningful training signal from the first step)
        y = np.tile(future_state, len(FORECAST_STEPS)).astype(np.float32)
        self._buf.append((inp, y))

    def train_step(self, batch_size: int = BATCH_SIZE) -> float | None:
        """
        Execute one mini-batch gradient step.
        Returns loss value or None if not enough samples yet.
        """
        if len(self._buf) < batch_size:
            return None

        self.model.train()
        buf_list = list(self._buf)
        idxs = np.random.choice(len(buf_list), size=batch_size, replace=False)
        Xs, ys = [], []
        for i in idxs:
            Xs.append(buf_list[i][0])
            ys.append(buf_list[i][1])

        X = torch.tensor(np.stack(Xs), dtype=torch.float32).to(self.device)
        y = torch.tensor(np.stack(ys), dtype=torch.float32).to(self.device)

        pred = self.model(X)
        loss = self.loss_fn(pred, y)

        self.optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
        self.optimizer.step()
        self.scheduler.step()

        self.train_steps += 1
        self.last_loss = float(loss.item())
        return self.last_loss

    # ── Persistence ───────────────────────────────────────────────────────────

    def save(self, path: str = _MODEL_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        torch.save(
            {
                "model":       self.model.state_dict(),
                "optimizer":   self.optimizer.state_dict(),
                "train_steps": self.train_steps,
            },
            path,
        )

    def load(self, path: str = _MODEL_PATH) -> bool:
        if not os.path.exists(path):
            return False
        try:
            ckpt = torch.load(path, map_location=self.device, weights_only=True)
            self.model.load_state_dict(ckpt["model"])
            self.optimizer.load_state_dict(ckpt["optimizer"])
            self.train_steps = ckpt.get("train_steps", 0)
            print(f"[PredictiveModel] Loaded checkpoint ({self.train_steps} steps) from {path}")
            return True
        except Exception as e:
            print(f"[PredictiveModel] Could not load checkpoint: {e}")
            return False

    @property
    def n_samples(self) -> int:
        return len(self._buf)

    @property
    def lsh_size(self) -> int:
        return len(self.lsh)