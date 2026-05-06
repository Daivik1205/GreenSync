# nav/traffic_manager.py
# TrafficManager — extracts per-edge state vectors from TraCI metrics
# and maintains a rolling history window consumed by the LSH-GRU predictor.
#
# StateVector S = [speed_norm, density_norm, delay_norm, congestion_enc]
# All components are normalised to [0, 1] so the GRU and LSH operate on a
# consistent scale regardless of road type or vehicle mix.

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import numpy as np

# ── Normalisation ceilings (domain knowledge, Bengaluru urban context) ────────
_MAX_SPEED   = 14.0    # m/s ≈ 50 km/h posted limit
_MAX_DENSITY = 30.0    # vehicles per edge (heavy urban)
_MAX_WAIT    = 300.0   # seconds accumulated wait (5 min = severe)

# History kept per edge (60 steps @ ~1 step/s ≈ 1 minute of context)
HISTORY_LEN   = 60
SEQUENCE_LEN  = 10     # GRU input window

# Congestion event → continuous encoding
_CONGESTION_ENC = {
    "free_flow":  0.0,
    "slowdown":   0.5,
    "congestion": 1.0,
    "unknown":    0.0,
}


@dataclass
class StateVector:
    """
    Normalised per-edge state snapshot consumed by LSH and GRU.
    All fields are in [0, 1].
    """
    speed:      float   # current_speed / speed_limit
    density:    float   # vehicle_count / MAX_DENSITY
    delay:      float   # max_waiting_time / MAX_WAIT
    congestion: float   # 0=free_flow  0.5=slowdown  1=congestion

    def to_array(self) -> np.ndarray:
        return np.array(
            [self.speed, self.density, self.delay, self.congestion],
            dtype=np.float32,
        )

    @staticmethod
    def from_array(arr: np.ndarray) -> "StateVector":
        a = arr.astype(float)
        return StateVector(float(a[0]), float(a[1]), float(a[2]), float(a[3]))

    @property
    def speed_ms(self) -> float:
        """Denormalised speed in m/s."""
        return self.speed * _MAX_SPEED

    @property
    def speed_kmh(self) -> float:
        return self.speed_ms * 3.6


class TrafficManager:
    """
    Bridges live TraCI edge metrics → normalised StateVectors consumed by the
    prediction pipeline.

    Call sequence each simulation step:
        tm.update(edge_states, vehicles)   ← feed latest metrics
        seq = tm.get_history(eid, n)       ← GRU reads sliding window
        sv  = tm.get_current(eid)          ← A* reads current state
    """

    def __init__(self):
        # edge_id → ring-buffer of raw np arrays (shape 4,)
        self._history: dict[str, deque] = {}
        # edge_id → latest StateVector
        self._current: dict[str, StateVector] = {}
        # edge_id → posted speed limit (m/s), populated at setup_edges time
        self._max_speed: dict[str, float] = {}

    # ── Setup ─────────────────────────────────────────────────────────────────

    def register_edges(
        self,
        edge_ids: set[str] | list[str],
        max_speeds: dict[str, float] | None = None,
    ):
        """
        Declare the set of monitored edges and (optionally) their speed limits.
        Safe to call multiple times — only adds new edges, never clears history.
        """
        for eid in edge_ids:
            if eid not in self._history:
                self._history[eid] = deque(maxlen=HISTORY_LEN)
        if max_speeds:
            self._max_speed.update(max_speeds)

    # ── Update ────────────────────────────────────────────────────────────────

    def update(self, edge_states: dict, vehicles: list[dict]):
        """
        Extract metrics from edge_states and feed into history.
        """
        # Calculate max waiting time per edge from vehicle data
        edge_wait = {}
        for v in vehicles:
            eid = v["edge_id"]
            if eid not in edge_wait:
                edge_wait[eid] = 0.0
            edge_wait[eid] = max(edge_wait[eid], v.get("waiting_time", 0.0))

        for eid, state in edge_states.items():
            if eid not in self._history:
                continue

            max_spd = self._max_speed.get(eid, _MAX_SPEED)
            speed_norm = min(state.avg_speed / max_spd, 1.0)
            density_norm = min(state.vehicle_count / _MAX_DENSITY, 1.0)
            wait_norm = min(edge_wait.get(eid, 0.0) / _MAX_WAIT, 1.0)
            congestion_enc = _CONGESTION_ENC.get(state.event, 0.0)

            sv = StateVector(speed_norm, density_norm, wait_norm, congestion_enc)
            self._current[eid] = sv
            self._history[eid].append(sv.to_array())

    # ── Access ────────────────────────────────────────────────────────────────

    def get_history(self, edge_id: str, n_steps: int) -> np.ndarray | None:
        """
        Return the most recent n_steps history for edge_id as a (N, 4) array.
        Returns None if not enough history exists.
        """
        hist = self._history.get(edge_id)
        if not hist or len(hist) < n_steps:
            return None
        # Convert the rightmost n_steps to a numpy array
        return np.array(list(hist)[-n_steps:], dtype=np.float32)

    def get_current(self, edge_id: str) -> StateVector | None:
        """Return the latest StateVector for edge_id."""
        return self._current.get(edge_id)