# edge_detector.py — Phase 2 (edge-level sensing)
#
# Google Maps-style real-time traffic overlay for SUMO GUI.
#
# ────────────────────────────────────────────────────────────────────
# SUMO rendering pipeline (important for colour design)
# ────────────────────────────────────────────────────────────────────
#   1. Canvas / OSM background  (dark grey / black)
#   2. Lane surface colour       ← traci.lane.setColor() writes HERE
#   3. Lane markings             (white dashed lines — drawn on top)
#   4. Vehicles                  (always rendered above lane surface)
#
# Consequences:
#   • Vehicles are ALWAYS visible above the colour overlay regardless of alpha.
#   • Low alpha (≤160) blends into the dark canvas and produces dull, barely
#     visible colours.  We therefore use alpha 220 for active-traffic lanes.
#   • Empty lanes get dark-grey (50,50,50,255) — matches SUMO's default road
#     colour so unmonitored roads look natural and roads with colour stand out.
#
# Colour gradient (speed ratio = current_speed / posted_limit):
#   1.00  →  #00D93C  vivid green   (free flow)
#   0.75  →  #FFD200  yellow
#   0.50  →  #FF7800  orange
#   0.25  →  #D20000  red
#   0.00  →  #A80000  deep red      (standstill)
#
# Each directed edge is coloured independently — opposite lanes on the
# same street correctly show different colours when conditions differ.
# ────────────────────────────────────────────────────────────────────

import traci
from dataclasses import dataclass

# ── Event thresholds (m/s) ─────────────────────────────────────────────────
CONGESTION_THRESHOLD = 2.0   # < 2 m/s  (~7 km/h)
SLOWDOWN_THRESHOLD   = 6.0   # < 6 m/s  (~22 km/h)

# ── Visual constants ────────────────────────────────────────────────────────
_ALPHA       = 220                      # active-traffic lane overlay opacity
_EMPTY_COLOR = (50,  50,  50, 255)      # dark grey → matches SUMO default road
_RESET_COLOR = (255, 255, 255, 255)     # full white reset used on shutdown only

# Gradient colour stops  (R, G, B) at ratio breakpoints
_STOPS = [
    (1.00, (  0, 217,  60)),   # vivid green
    (0.75, (255, 210,   0)),   # yellow
    (0.50, (255, 120,   0)),   # orange
    (0.25, (210,   0,   0)),   # red
    (0.00, (168,   0,   0)),   # deep red / standstill
]

# ── Module-level caches (populated once at startup) ─────────────────────────
_max_speed: dict[str, float] = {}   # edge_id → posted speed limit (m/s)
_n_lanes:   dict[str, int]   = {}   # edge_id → lane count


# ── Data class ──────────────────────────────────────────────────────────────

@dataclass
class EdgeState:
    edge_id:       str
    vehicle_count: int
    avg_speed:     float   # m/s — TraCI last-step mean speed
    occupancy:     float   # 0–100 %
    speed_ratio:   float   # avg_speed / posted_limit, clamped [0, 1]
    event:         str     # free_flow | slowdown | congestion | unknown


# ── Colour helpers ──────────────────────────────────────────────────────────

def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * max(0.0, min(1.0, t)))


def _ratio_to_color(ratio: float) -> tuple:
    """
    Linearly interpolate between the nearest two colour stops
    and return an (R, G, B, A) tuple at the active overlay alpha.
    """
    ratio = max(0.0, min(1.0, ratio))

    # Find the two stops that bracket this ratio
    for i in range(len(_STOPS) - 1):
        hi_r, hi_c = _STOPS[i]
        lo_r, lo_c = _STOPS[i + 1]
        if ratio >= lo_r:
            t = (ratio - lo_r) / (hi_r - lo_r)   # 0 = lo_c, 1 = hi_c
            return (
                _lerp(lo_c[0], hi_c[0], t),
                _lerp(lo_c[1], hi_c[1], t),
                _lerp(lo_c[2], hi_c[2], t),
                _ALPHA,
            )

    # ratio exactly 0
    return (*_STOPS[-1][1], _ALPHA)


def _detect_event(speed: float, count: int) -> str:
    if count == 0:
        return "unknown"
    if speed < CONGESTION_THRESHOLD:
        return "congestion"
    if speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


# ── Cache primer — call ONCE after traci.start() ────────────────────────────

def prime_edge_cache(edge_ids: set | list):
    """
    Pre-fetch posted speed limits and lane counts for every edge.
    Must be called after traci.start(), before the main loop.
    Silently skips unknown or internal (:) edges.
    """
    for eid in edge_ids:
        if eid.startswith(":"):
            continue
        try:
            n = traci.edge.getLaneNumber(eid)
            _n_lanes[eid] = n
            _max_speed[eid] = max(traci.lane.getMaxSpeed(f"{eid}_0"), 1.0)
        except Exception:
            _n_lanes[eid]   = 1
            _max_speed[eid] = 13.9   # fallback: 50 km/h


def init_edge_colors(edge_ids: set | list):
    """
    Paint every monitored edge dark-grey at startup so they are
    visually distinct from unmonitored roads from step 0.
    Call once immediately after prime_edge_cache().
    """
    for eid in edge_ids:
        if eid.startswith(":"):
            continue
        n = _n_lanes.get(eid, 1)
        try:
            for i in range(n):
                traci.lane.setColor(f"{eid}_{i}", _EMPTY_COLOR)
        except Exception:
            pass


# ── Public API ──────────────────────────────────────────────────────────────

def get_edge_state(edge_id: str) -> EdgeState:
    """
    Query TraCI for the current state of one directed edge.
    Uses last-step aggregated statistics — no vehicle-list scanning.
    """
    try:
        count     = traci.edge.getLastStepVehicleNumber(edge_id)
        speed     = traci.edge.getLastStepMeanSpeed(edge_id)
        occupancy = traci.edge.getLastStepOccupancy(edge_id)
    except Exception:
        return EdgeState(edge_id, 0, 0.0, 0.0, 0.0, "unknown")

    max_spd = _max_speed.get(edge_id, 13.9)
    ratio   = min(speed / max_spd, 1.0) if speed > 0 else 0.0

    return EdgeState(
        edge_id       = edge_id,
        vehicle_count = count,
        avg_speed     = round(speed, 2),
        occupancy     = round(occupancy, 1),
        speed_ratio   = round(ratio, 3),
        event         = _detect_event(speed, count),
    )


def sense_edges(edge_ids: set | list) -> dict[str, EdgeState]:
    """
    Batch-sense every edge.  Returns {edge_id: EdgeState}.
    Internal junction edges (:prefix) are always skipped.
    """
    return {
        eid: get_edge_state(eid)
        for eid in edge_ids
        if not eid.startswith(":")
    }


def color_edge(edge_id: str, state: EdgeState):
    """
    Paint all lanes of a directed edge.

    Active roads (≥1 vehicle):
        Smooth gradient red → orange → yellow → green based on speed_ratio.
        Alpha=220 gives vivid, clearly visible colours on SUMO's dark canvas.
        Vehicles are rendered ABOVE the lane surface — yellow cars are always
        visible on top regardless of the overlay colour or alpha.

    Empty roads:
        Dark grey (50,50,50) — matches SUMO's default road appearance so the
        network stays readable and coloured roads clearly stand out.
    """
    color = _ratio_to_color(state.speed_ratio) if state.vehicle_count > 0 else _EMPTY_COLOR
    n     = _n_lanes.get(edge_id, 1)
    try:
        for i in range(n):
            traci.lane.setColor(f"{edge_id}_{i}", color)
    except Exception:
        pass   # headless / edge not in network — no-op


def color_edges(edge_states: dict[str, EdgeState]):
    """Paint every edge in the dict.  Called once per simulation step."""
    for edge_id, state in edge_states.items():
        color_edge(edge_id, state)


def reset_edge_colors(edge_ids: set | list):
    """Reset all lanes to full white.  Call on clean shutdown."""
    for eid in edge_ids:
        n = _n_lanes.get(eid, 1)
        try:
            for i in range(n):
                traci.lane.setColor(f"{eid}_{i}", _RESET_COLOR)
        except Exception:
            pass
