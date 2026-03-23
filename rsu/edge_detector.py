# edge_detector.py — Phase 2 (edge-level sensing)
#
# Fine-grained, per-edge (road segment) event detection.
# Each SUMO edge is a directed road segment — opposite directions
# are separate edges, so congestion/slowdown is detected independently
# per direction.
#
# Coloring strategy:
#   Each edge's lanes are painted in SUMO GUI using traci.lane.setColor()
#   so road status is visible directly on the map without any filled overlays.
#
# Data exposed:
#   EdgeState — speed, occupancy, vehicle count, event label
#   sense_edges() — batch-sense a list of edge IDs
#   color_edge()  — paint all lanes of an edge in the GUI

import traci
from dataclasses import dataclass

# ── Event thresholds (m/s) ────────────────────────────────────────────────────
CONGESTION_THRESHOLD = 2.0   # < 2 m/s  (~7 km/h)  → congestion
SLOWDOWN_THRESHOLD   = 6.0   # < 6 m/s  (~22 km/h) → slowdown
# ≥ 6 m/s                                           → free_flow

# ── Lane colours (R, G, B, A) ─────────────────────────────────────────────────
# Semi-transparent so road markings remain visible underneath.
EDGE_COLORS = {
    "free_flow":  (0,   210,  60, 180),   # vivid green
    "slowdown":   (255, 165,   0, 200),   # amber / orange
    "congestion": (220,   0,   0, 220),   # red
    "unknown":    (120, 120, 120,  80),   # grey — no vehicles
}

# Default lane colour (resets the road to SUMO default white/grey)
DEFAULT_COLOR = (255, 255, 255, 255)


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class EdgeState:
    edge_id:       str
    vehicle_count: int
    avg_speed:     float   # m/s  (TraCI mean speed for the edge)
    occupancy:     float   # 0–100 %
    event:         str     # free_flow | slowdown | congestion | unknown


# ── Internal helpers ──────────────────────────────────────────────────────────

def _detect_event(avg_speed: float, vehicle_count: int) -> str:
    if vehicle_count == 0:
        return "unknown"
    if avg_speed < CONGESTION_THRESHOLD:
        return "congestion"
    elif avg_speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


def _get_lane_ids(edge_id: str) -> list[str]:
    """Return all lane IDs for an edge.  Falls back to edge_id_0 if TraCI call fails."""
    try:
        return list(traci.edge.getLaneNumber(edge_id)
                    and [f"{edge_id}_{i}" for i in range(traci.edge.getLaneNumber(edge_id))])
    except Exception:
        return [f"{edge_id}_0"]


# ── Public API ────────────────────────────────────────────────────────────────

def get_edge_state(edge_id: str) -> EdgeState:
    """
    Query TraCI for the current state of a single directed edge.
    Uses last simulation step aggregated values — no vehicle-list scanning needed.
    """
    try:
        count     = traci.edge.getLastStepVehicleNumber(edge_id)
        speed     = traci.edge.getLastStepMeanSpeed(edge_id)
        occupancy = traci.edge.getLastStepOccupancy(edge_id)
    except Exception:
        return EdgeState(edge_id, 0, 0.0, 0.0, "unknown")

    event = _detect_event(speed, count)
    return EdgeState(
        edge_id       = edge_id,
        vehicle_count = count,
        avg_speed     = round(speed, 2),
        occupancy     = round(occupancy, 1),
        event         = event,
    )


def sense_edges(edge_ids: set | list) -> dict[str, EdgeState]:
    """
    Batch-sense every edge in edge_ids.
    Returns {edge_id: EdgeState} mapping.
    Skips internal junction edges (: prefix) silently.
    """
    states = {}
    for eid in edge_ids:
        if not eid.startswith(":"):
            states[eid] = get_edge_state(eid)
    return states


def color_edge(edge_id: str, event: str):
    """
    Paint all lanes of an edge with the event colour.
    Called every simulation step — silently ignored in headless mode
    (traci.lane.setColor raises TraCIException if GUI is not active).
    """
    color = EDGE_COLORS.get(event, EDGE_COLORS["unknown"])
    try:
        n_lanes = traci.edge.getLaneNumber(edge_id)
        for i in range(n_lanes):
            traci.lane.setColor(f"{edge_id}_{i}", color)
    except Exception:
        pass   # headless or edge not in network


def color_edges(edge_states: dict[str, EdgeState]):
    """Paint all edges in the dict according to their event."""
    for edge_id, state in edge_states.items():
        color_edge(edge_id, state.event)


def reset_edge_colors(edge_ids: set | list):
    """Reset all lanes to the SUMO default (white).  Call on shutdown."""
    for eid in edge_ids:
        try:
            n_lanes = traci.edge.getLaneNumber(eid)
            for i in range(n_lanes):
                traci.lane.setColor(f"{eid}_{i}", DEFAULT_COLOR)
        except Exception:
            pass
