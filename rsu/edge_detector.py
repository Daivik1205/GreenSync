# edge_detector.py — Phase 2 (edge-level sensing)
#
# Google Maps-style real-time traffic overlay for SUMO GUI.
#
# Coloring strategy
# ─────────────────
# Each lane is painted with traci.lane.setColor() using a smooth colour
# derived from the lane's *speed ratio* (current mean speed / posted limit).
#
#   ratio ≥ 0.75  →  green   (free flow)
#   ratio 0.50    →  yellow
#   ratio 0.25    →  orange
#   ratio ≤ 0.00  →  red     (standstill / congestion)
#
# Alpha is 155 on all active colours so the road geometry and vehicles
# (drawn on top of lanes in SUMO) remain clearly visible beneath the tint.
# Roads with no vehicles get a near-invisible grey wash (alpha=35) so they
# visually "reset" without becoming white.
#
# Per-edge max-speed lookup is done once at startup via prime_edge_cache()
# and stored in a module dict — zero extra TraCI calls per step.
#
# Each directed edge is treated independently, so opposite-direction lanes
# on the same physical road show different colours when conditions differ.

import traci
from dataclasses import dataclass

# ── Event thresholds (m/s) — kept for zone aggregation label ─────────────────
CONGESTION_THRESHOLD = 2.0   # m/s (~7 km/h)
SLOWDOWN_THRESHOLD   = 6.0   # m/s (~22 km/h)

# ── Visual tuning ─────────────────────────────────────────────────────────────
OVERLAY_ALPHA    = 155   # 0–255; 155 ≈ 60 % opaque — road + vehicles still visible
NO_VEH_ALPHA     = 35    # faint wash on empty roads
NO_VEH_COLOR     = (160, 160, 160, NO_VEH_ALPHA)   # near-invisible grey
DEFAULT_COLOR    = (255, 255, 255, 255)              # full reset on shutdown

# ── Module-level cache: edge_id → max speed (m/s) ────────────────────────────
_edge_max_speed: dict[str, float] = {}
_edge_n_lanes:   dict[str, int]   = {}


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class EdgeState:
    edge_id:       str
    vehicle_count: int
    avg_speed:     float    # m/s — TraCI last-step mean speed
    occupancy:     float    # 0–100 %
    speed_ratio:   float    # avg_speed / max_speed, clamped [0, 1]
    event:         str      # free_flow | slowdown | congestion | unknown


# ── Color helpers ─────────────────────────────────────────────────────────────

def _lerp(a: int, b: int, t: float) -> int:
    """Integer linear interpolation."""
    return int(a + (b - a) * max(0.0, min(1.0, t)))


def _ratio_to_color(ratio: float) -> tuple:
    """
    Google Maps-style smooth gradient based on speed ratio [0, 1].

    Colour stops (R, G, B):
        1.00  →  (  0, 210,  60)  bright green
        0.75  →  (255, 210,   0)  yellow
        0.40  →  (255, 120,   0)  orange
        0.00  →  (210,   0,   0)  red

    All with OVERLAY_ALPHA so road geometry shows through.
    """
    a = OVERLAY_ALPHA

    if ratio >= 0.75:
        # Full green
        return (0, 210, 60, a)

    if ratio >= 0.50:
        # Green → yellow  (ratio 0.75 → 0.50)
        t = (ratio - 0.50) / 0.25
        return (_lerp(255,   0, t),
                _lerp(210, 210, t),
                _lerp(  0,  60, t),
                a)

    if ratio >= 0.25:
        # Yellow → orange  (ratio 0.50 → 0.25)
        t = (ratio - 0.25) / 0.25
        return (_lerp(255, 255, t),
                _lerp(120, 210, t),
                0,
                a)

    # Orange → red  (ratio 0.25 → 0.00)
    t = ratio / 0.25
    return (_lerp(210, 255, t),
            _lerp(  0, 120, t),
            0,
            a)


def _event_from_ratio(ratio: float, vehicle_count: int) -> str:
    if vehicle_count == 0:
        return "unknown"
    if ratio < (CONGESTION_THRESHOLD / max(_edge_max_speed.get("_ref", 13.9), 1)):
        return "congestion"
    # Fall back to absolute thresholds for labelling
    speed_ms = ratio  # not real speed — use raw speed instead (computed in caller)
    return "unknown"


def _detect_event(speed: float, count: int) -> str:
    if count == 0:
        return "unknown"
    if speed < CONGESTION_THRESHOLD:
        return "congestion"
    if speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


# ── Cache primer — call ONCE after traci.start() ──────────────────────────────

def prime_edge_cache(edge_ids: set | list):
    """
    Pre-fetch max speed and lane count for every edge.
    Must be called after traci.start() and before the main loop.
    Silently skips unknown edges.
    """
    for eid in edge_ids:
        if eid.startswith(":"):
            continue
        try:
            n = traci.edge.getLaneNumber(eid)
            _edge_n_lanes[eid] = n
            # Use lane 0's max speed as the edge limit
            max_spd = traci.lane.getMaxSpeed(f"{eid}_0")
            _edge_max_speed[eid] = max(max_spd, 1.0)   # guard against 0
        except Exception:
            _edge_n_lanes[eid]   = 1
            _edge_max_speed[eid] = 13.9   # fallback: 50 km/h


# ── Public API ────────────────────────────────────────────────────────────────

def get_edge_state(edge_id: str) -> EdgeState:
    """
    Query TraCI for the current state of one directed edge.
    Uses last-step aggregated values — O(1) per edge, no vehicle scan.
    """
    try:
        count     = traci.edge.getLastStepVehicleNumber(edge_id)
        speed     = traci.edge.getLastStepMeanSpeed(edge_id)
        occupancy = traci.edge.getLastStepOccupancy(edge_id)
    except Exception:
        return EdgeState(edge_id, 0, 0.0, 0.0, 0.0, "unknown")

    max_spd = _edge_max_speed.get(edge_id, 13.9)
    ratio   = min(speed / max_spd, 1.0) if speed > 0 else 0.0
    event   = _detect_event(speed, count)

    return EdgeState(
        edge_id       = edge_id,
        vehicle_count = count,
        avg_speed     = round(speed, 2),
        occupancy     = round(occupancy, 1),
        speed_ratio   = round(ratio, 3),
        event         = event,
    )


def sense_edges(edge_ids: set | list) -> dict[str, EdgeState]:
    """
    Batch-sense every edge.  Returns {edge_id: EdgeState}.
    Internal junction edges (:prefix) are skipped.
    """
    return {
        eid: get_edge_state(eid)
        for eid in edge_ids
        if not eid.startswith(":")
    }


def color_edge(edge_id: str, state: EdgeState):
    """
    Paint all lanes of an edge with a Google Maps-style traffic colour.

    Active roads (vehicles present):
        smooth gradient from red (stopped) → green (free flow)
        based on speed_ratio = current_speed / posted_limit

    Empty roads:
        near-invisible grey wash so they appear uncoloured without
        reverting to the SUMO default white (which looks odd mid-run).

    Vehicles are rendered ON TOP of lane colours by SUMO, so they
    are always visible regardless of the overlay.
    """
    if state.vehicle_count > 0:
        color = _ratio_to_color(state.speed_ratio)
    else:
        color = NO_VEH_COLOR

    n = _edge_n_lanes.get(edge_id, 1)
    try:
        for i in range(n):
            traci.lane.setColor(f"{edge_id}_{i}", color)
    except Exception:
        pass   # headless mode — no GUI


def color_edges(edge_states: dict[str, EdgeState]):
    """Paint every edge in the dict.  Called once per simulation step."""
    for edge_id, state in edge_states.items():
        color_edge(edge_id, state)


def reset_edge_colors(edge_ids: set | list):
    """Restore all lanes to SUMO default white.  Call on clean shutdown."""
    for eid in edge_ids:
        n = _edge_n_lanes.get(eid, 1)
        try:
            for i in range(n):
                traci.lane.setColor(f"{eid}_{i}", DEFAULT_COLOR)
        except Exception:
            pass
