# nav/prediction_buffer.py
# PredictionBuffer — runs GRU inference ONCE per batch-of-steps for ALL edges
# and caches the results so the A* algorithm can do O(1) lookups.
#
# This decouples expensive inference from the routing hot-path:
#   SimController step → buffer.update() → runs inference + training in background
#   ModifiedAStar      → buffer.get()    → pure dict lookup, no inference

from __future__ import annotations

import numpy as np

from .traffic_manager import TrafficManager, SEQUENCE_LEN
from .predictive_model import PredictiveModel, FORECAST_STEPS, STATE_DIM

# ── Scheduling parameters ─────────────────────────────────────────────────────
PRED_REFRESH_EVERY   = 5    # re-run GRU every N sim steps (fast with batching)
SAMPLE_COLLECT_EVERY = 2    # add training samples every N steps
RETRAIN_EVERY        = 20   # mini-batch SGD every N steps


class PredictionBuffer:
    """
    Per-edge GRU forecast cache.

    Layout:
        _cache[edge_id][t_offset] = np.ndarray(STATE_DIM,)
    where t_offset ∈ FORECAST_STEPS (5, 10, 15, 20, 25, 30).

    The buffer is refreshed every PRED_REFRESH_EVERY steps; between refreshes
    callers read stale-but-valid predictions (edge traffic changes slowly
    relative to the routing decision window).
    """

    def __init__(
        self,
        traffic_manager: TrafficManager,
        model:           PredictiveModel,
    ):
        self._tm    = traffic_manager
        self._model = model
        self._cache: dict[str, dict[int, np.ndarray]] = {}
        self._step  = 0

    # ── Per-simulation-step update ────────────────────────────────────────────

    def update(self, sim_step: int, edge_ids: list[str]):
        """
        Called once every simulation step by SimController.

        Responsibilities (staggered to spread CPU load):
          1. Collect new training samples from accumulated history.
          2. Fire a mini-batch training step.
          3. Refresh the prediction cache for all edges.
        """
        self._step = sim_step

        # 1. Collect training samples
        if sim_step % SAMPLE_COLLECT_EVERY == 0:
            self._collect_samples(edge_ids)

        # 2. Online training
        if sim_step % RETRAIN_EVERY == 0 and sim_step > 0:
            self._model.train_step()

        # 3. Refresh cache
        if sim_step % PRED_REFRESH_EVERY == 0:
            self._refresh(edge_ids)

    # ── Cache read (called by ModifiedAStar — must be fast) ───────────────────

    def get_prediction(self, edge_id: str, t_offset: int) -> np.ndarray | None:
        """
        Return the predicted StateVector array for edge_id at T+t_offset steps.
        Automatically snaps t_offset to the nearest available forecast horizon.
        Returns None if no prediction is cached for this edge.
        """
        preds = self._cache.get(edge_id)
        if not preds:
            return None
        nearest = min(FORECAST_STEPS, key=lambda s: abs(s - t_offset))
        return preds.get(nearest)

    def get_current_state(self, edge_id: str):
        """Convenience pass-through to TrafficManager.get_current()."""
        return self._tm.get_current(edge_id)

    # ── Properties surfaced to the dashboard ─────────────────────────────────

    @property
    def training_loss(self) -> float | None:
        return self._model.last_loss

    @property
    def train_steps(self) -> int:
        return self._model.train_steps

    @property
    def n_samples(self) -> int:
        return self._model.n_samples

    @property
    def lsh_size(self) -> int:
        return self._model.lsh_size

    # ── Private helpers ───────────────────────────────────────────────────────

    def _collect_samples(self, edge_ids: list[str]):
        """Feed completed history windows into the model's training buffer."""
        min_needed = SEQUENCE_LEN + 1
        for eid in edge_ids:
            current = self._tm.get_current(eid)
            # Skip edges with no vehicle activity — pure-zero samples add no signal
            if current is None or (current.speed == 0.0 and current.density == 0.0):
                continue
            hist = self._tm.get_history(eid, min_needed)
            if hist is None or len(hist) < min_needed:
                continue
            seq    = hist[:SEQUENCE_LEN]
            future = hist[SEQUENCE_LEN]
            self._model.add_sample(seq, future)

    def _refresh(self, edge_ids: list[str]):
        """
        Run GRU inference in ONE batched forward pass for all ready edges.
        Previously called predict() per-edge (N separate passes); batching is
        ~N× faster and keeps the background thread from starving state.update().
        """
        import torch
        import numpy as np

        batch_eids: list[str]       = []
        batch_inputs: list[np.ndarray] = []

        for eid in edge_ids:
            current = self._tm.get_current(eid)
            # Skip edges with no vehicle activity — their prediction would be all-zeros
            if current is None or (current.speed == 0.0 and current.density == 0.0):
                continue
            seq = self._tm.get_history(eid, SEQUENCE_LEN)
            if seq is None:
                continue
            inp = self._model._build_input(seq, current.to_array())  # (seq_len, INPUT_DIM)
            batch_eids.append(eid)
            batch_inputs.append(inp)

        if not batch_eids:
            return

        X = torch.tensor(
            np.stack(batch_inputs), dtype=torch.float32
        ).to(self._model.device)          # (N, seq_len, INPUT_DIM)

        self._model.model.eval()
        with torch.no_grad():
            out = self._model.model(X).cpu().numpy()  # (N, OUTPUT_DIM)

        for i, eid in enumerate(batch_eids):
            self._cache[eid] = {
                step: out[i, j * STATE_DIM: (j + 1) * STATE_DIM]
                for j, step in enumerate(FORECAST_STEPS)
            }

    def forecast_summary(self, edge_id: str) -> dict[str, float] | None:
        """
        Return a human-readable dict of predicted speeds (km/h) per horizon.
        Useful for the dashboard's route analysis panel.
        """
        preds = self._cache.get(edge_id)
        if not preds:
            return None
        return {
            f"T+{step}s": round(float(arr[0]) * 14.0 * 3.6, 1)   # speed_norm → km/h
            for step, arr in preds.items()
        }