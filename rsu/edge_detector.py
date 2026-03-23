# edge_detector.py — Phase 2 (SUMO-native edge sensing + Google Maps overlay)
#
# Design principles
# ─────────────────
# 1. SUMO as a virtual sensor grid
#    Each edge's SUMO loop-detector metrics (vehicle count, mean speed,
#    occupancy, halting count) are treated as RSU infrastructure readings.
#    No physical sensor simulation needed — SUMO computes these natively.
#
# 2. TraCI subscriptions for efficient batch reads
#    At startup, subscribe_edges() registers all zone edges with TraCI.
#    Each simulationStep() makes SUMO push updates internally; after
#    stepping, sense_edges_subscribed() reads ALL subscribed edge data in
#    a SINGLE TraCI round-trip instead of N × 3 individual calls.
#
# 3. Smart (diff-only) lane colouring
#    Each lane's last-painted colour is cached.  color_edges() only calls
#    traci.lane.setColor() when the colour actually changed — drastically
#    reducing TraCI write traffic when traffic is stable.
#
# 4. Google Maps-style smooth gradient
#    Speed ratio (current / posted limit) drives a continuous colour ramp:
#    deep-red (stopped) → red → orange → yellow → bright-green (free flow)
#    Alpha=220 on the dark SUMO canvas gives vivid, clearly visible overlays.
#    SUMO renders vehicles ABOVE the lane surface, so yellow cars are always
#    visible regardless of the overlay colour or alpha.
#
# 5. Per-direction independence
#    Each directed edge is sensed and coloured independently — opposite lanes
#    on the same physical road reflect their own real-time conditions.

import traci
from dataclasses import dataclass

# ── Event thresholds (m/s) ─────────────────────────────────────────────────────
CONGESTION_THRESHOLD = 2.0   # < 2 m/s  ≈  7 km/h
SLOWDOWN_THRESHOLD   = 6.0   # < 6 m/s  ≈ 22 km/h

# ── Colour gradient stops  (ratio, (R, G, B)) ─────────────────────────────────
# ratio = current_speed / posted_speed_limit  (0 = stopped, 1 = full speed)
_ALPHA = 220    # overlay alpha — vivid on dark SUMO canvas; vehicles drawn above
_STOPS = [
    (1.00, (  0, 210,  60)),   # bright green   — free flow
    (0.75, (255, 210,   0)),   # yellow
    (0.50, (255, 120,   0)),   # orange
    (0.25, (210,   0,   0)),   # red
    (0.00, (168,   0,   0)),   # deep red        — standstill
]
_EMPTY_COLOR = ( 50,  50,  50, 255)   # dark-grey — empty monitored road
_RESET_COLOR = (255, 255, 255, 255)   # full-white reset used on shutdown

# ── TraCI subscription variable constants ─────────────────────────────────────
try:
    from traci import constants as _TC
    _SUB_VARS = [
        _TC.LAST_STEP_VEHICLE_NUMBER,   # 0x10  — vehicle count
        _TC.LAST_STEP_MEAN_SPEED,       # 0x11  — mean speed (m/s)
        _TC.LAST_STEP_OCCUPANCY,        # 0x13  — occupancy (%)
        _TC.LAST_STEP_HALTING_NUMBER,   # 0x14  — vehicles with speed < 0.1 m/s
    ]
    _TC_COUNT   = _TC.LAST_STEP_VEHICLE_NUMBER
    _TC_SPEED   = _TC.LAST_STEP_MEAN_SPEED
    _TC_OCC     = _TC.LAST_STEP_OCCUPANCY
    _TC_HALTING = _TC.LAST_STEP_HALTING_NUMBER
except Exception:
    # Raw hex fallback in case constant names differ between SUMO versions
    _SUB_VARS   = [0x10, 0x11, 0x13, 0x14]
    _TC_COUNT   = 0x10
    _TC_SPEED   = 0x11
    _TC_OCC     = 0x13
    _TC_HALTING = 0x14

# ── Module-level caches ────────────────────────────────────────────────────────
_max_speed:    dict[str, float] = {}   # edge_id → posted speed limit (m/s)
_n_lanes:      dict[str, int]   = {}   # edge_id → number of lanes
_color_cache:  dict[str, tuple] = {}   # lane_id → last colour applied (diff-guard)
_subscribed:   set[str]         = set()


# ── Data class ─────────────────────────────────────────────────────────────────

@dataclass
class EdgeState:
    edge_id:       str
    vehicle_count: int
    avg_speed:     float    # m/s — SUMO last-step mean speed (virtual loop sensor)
    occupancy:     float    # 0–100 % — % of road surface occupied
    halting_count: int      # vehicles with speed < 0.1 m/s (virtual detector)
    speed_ratio:   float    # avg_speed / posted_limit, clamped [0, 1]
    event:         str      # free_flow | slowdown | congestion | unknown

    @property
    def speed_kmh(self) -> float:
        return round(self.avg_speed * 3.6, 1)


# ── Colour helpers ─────────────────────────────────────────────────────────────

def _lerp(a: int, b: int, t: float) -> int:
    return int(a + (b - a) * max(0.0, min(1.0, t)))


def _ratio_to_color(ratio: float) -> tuple:
    """Smooth interpolation between the nearest two gradient stops."""
    ratio = max(0.0, min(1.0, ratio))
    for i in range(len(_STOPS) - 1):
        hi_r, hi_c = _STOPS[i]
        lo_r, lo_c = _STOPS[i + 1]
        if ratio >= lo_r:
            t = (ratio - lo_r) / (hi_r - lo_r)
            return (
                _lerp(lo_c[0], hi_c[0], t),
                _lerp(lo_c[1], hi_c[1], t),
                _lerp(lo_c[2], hi_c[2], t),
                _ALPHA,
            )
    return (*_STOPS[-1][1], _ALPHA)


def _detect_event(speed: float, count: int) -> str:
    if count == 0:
        return "unknown"
    if speed < CONGESTION_THRESHOLD:
        return "congestion"
    if speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


# ── Setup — call ONCE after traci.start() ─────────────────────────────────────

def setup_edges(edge_ids: set | list):
    """
    One-time initialisation for all monitored edges:
      1. Cache posted speed limit and lane count (no per-step TraCI overhead).
      2. Subscribe to SUMO's internal loop-detector metrics so all data
         arrives in one round-trip after each simulationStep().
      3. Paint all lanes dark-grey to mark them as RSU-monitored from step 0.

    Call this ONCE, after traci.start() and after building zones.
    """
    for eid in edge_ids:
        if eid.startswith(":"):
            continue

        # ── Cache geometry ────────────────────────────────────────────────────
        try:
            n = traci.edge.getLaneNumber(eid)
            _n_lanes[eid]   = n
            _max_speed[eid] = max(traci.lane.getMaxSpeed(f"{eid}_0"), 1.0)
        except Exception:
            _n_lanes[eid]   = 1
            _max_speed[eid] = 13.9   # fallback: 50 km/h

        # ── Subscribe to batch sensor metrics ─────────────────────────────────
        try:
            traci.edge.subscribe(eid, _SUB_VARS)
            _subscribed.add(eid)
        except Exception:
            pass

    # ── Initialise lane colours to dark-grey ─────────────────────────────────
    for eid in edge_ids:
        if eid.startswith(":"):
            continue
        n = _n_lanes.get(eid, 1)
        try:
            for i in range(n):
                lid = f"{eid}_{i}"
                traci.lane.setColor(lid, _EMPTY_COLOR)
                _color_cache[lid] = _EMPTY_COLOR
        except Exception:
            pass

    print(f"   {len(_subscribed)} edges subscribed | {len(_n_lanes)} edges cached")


# ── Per-step sensing (call after simulationStep()) ────────────────────────────

def sense_edges_subscribed() -> dict[str, "EdgeState"]:
    """
    Read ALL subscribed edge metrics from SUMO in ONE TraCI round-trip.
    Returns {edge_id: EdgeState}.

    SUMO pushes subscription results automatically after simulationStep().
    getAllSubscriptionResults() fetches the entire batch at once — no
    per-edge TCP overhead.
    """
    all_results = traci.edge.getAllSubscriptionResults()
    states: dict[str, EdgeState] = {}

    for eid, data in all_results.items():
        count    = int(data.get(_TC_COUNT,   0))
        speed    = float(data.get(_TC_SPEED,  0.0))
        occ      = float(data.get(_TC_OCC,    0.0))
        halting  = int(data.get(_TC_HALTING, 0))
        max_spd  = _max_speed.get(eid, 13.9)
        ratio    = min(speed / max_spd, 1.0) if count > 0 and speed > 0 else 0.0

        states[eid] = EdgeState(
            edge_id       = eid,
            vehicle_count = count,
            avg_speed     = round(speed, 2),
            occupancy     = round(occ, 1),
            halting_count = halting,
            speed_ratio   = round(ratio, 3),
            event         = _detect_event(speed, count),
        )

    return states


def sense_edges(edge_ids: set | list) -> dict[str, "EdgeState"]:
    """
    Fallback direct-query sensing (used if subscriptions not set up).
    Slower than sense_edges_subscribed() but always correct.
    """
    states: dict[str, EdgeState] = {}
    for eid in edge_ids:
        if eid.startswith(":"):
            continue
        try:
            count   = traci.edge.getLastStepVehicleNumber(eid)
            speed   = traci.edge.getLastStepMeanSpeed(eid)
            occ     = traci.edge.getLastStepOccupancy(eid)
            halting = traci.edge.getLastStepHaltingNumber(eid)
        except Exception:
            states[eid] = EdgeState(eid, 0, 0.0, 0.0, 0, 0.0, "unknown")
            continue

        max_spd = _max_speed.get(eid, 13.9)
        ratio   = min(speed / max_spd, 1.0) if count > 0 and speed > 0 else 0.0
        states[eid] = EdgeState(
            edge_id       = eid,
            vehicle_count = count,
            avg_speed     = round(speed, 2),
            occupancy     = round(occ, 1),
            halting_count = halting,
            speed_ratio   = round(ratio, 3),
            event         = _detect_event(speed, count),
        )
    return states


# ── Per-step colouring ────────────────────────────────────────────────────────

def color_edges(edge_states: dict[str, "EdgeState"]):
    """
    Paint every monitored lane Google Maps-style.

    Diff-only updates: setColor is only called when the target colour differs
    from the cached previous value — minimises TraCI write traffic.

    Active lanes  → smooth gradient red → orange → yellow → green (alpha 220)
    Empty lanes   → dark grey (50,50,50) matching SUMO default road look
    """
    for eid, state in edge_states.items():
        target = _ratio_to_color(state.speed_ratio) if state.vehicle_count > 0 else _EMPTY_COLOR
        n      = _n_lanes.get(eid, 1)
        try:
            for i in range(n):
                lid = f"{eid}_{i}"
                if _color_cache.get(lid) != target:
                    traci.lane.setColor(lid, target)
                    _color_cache[lid] = target
        except Exception:
            pass


def reset_edge_colors(edge_ids: set | list):
    """Restore all lanes to full white.  Call on clean shutdown."""
    for eid in edge_ids:
        n = _n_lanes.get(eid, 1)
        try:
            for i in range(n):
                traci.lane.setColor(f"{eid}_{i}", _RESET_COLOR)
        except Exception:
            pass
