# rsu_manager.py — Phase 2
# RSU (Road-Side Unit) zone management.
#
# Zones are now lightweight organisational containers — they group edges
# and junctions for aggregation and MQTT routing.  The primary detection
# layer is edge-level (see edge_detector.py).
#
# GUI visualisation:
#   • Each zone is drawn as a thin OUTLINE circle (fill=False) — the road
#     network is always fully visible underneath.
#   • Zone radius is computed automatically so neighbouring zones do NOT
#     overlap (set to 40 % of the closest inter-centroid distance).
#   • Individual road lanes are coloured by edge_detector.color_edges()
#     every simulation step — green / amber / red directly on the roads.
#
# NOTE: "RADAR sensing" is simulated via TraCI edge statistics —
#       there is no physical sensor.

import math
import traci
from dataclasses import dataclass, field
from rsu.edge_detector import EdgeState


# ── Zone outline visual settings ─────────────────────────────────────────────
ZONE_N_POINTS     = 32     # polygon smoothness
ZONE_RADIUS_FRAC  = 0.30   # radius = nearest_neighbour_dist × this factor
                            # Matches BOUNDARY_FACTOR (0.32) in zone_builder closely so
                            # the drawn circle represents the actual sensing footprint.
                            # Two adjacent circles: r_i + r_j = 0.60 × d(i,j) → clear gap.
ZONE_RADIUS_MIN   = 0      # no minimum — let dense clusters be small
ZONE_RADIUS_MAX   = 180    # metres — tighter cap keeps circles small and non-distracting

ZONE_OUTLINE_COLOR = (80, 160, 255, 180)    # medium-blue outline, slightly more opaque
ZONE_OUTLINE_WIDTH = 1


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class Zone:
    zone_id:  str
    tl_ids:   list[str]
    edge_ids: set
    cx:       float = 0.0
    cy:       float = 0.0
    radius:   float = ZONE_RADIUS_MIN


@dataclass
class ZoneState:
    zone_id:          str
    vehicle_count:    int
    avg_speed:        float   # m/s — mean across all zone edges with vehicles
    dominant_event:   str     # worst event across zone edges
    edge_states:      dict = field(default_factory=dict)   # {edge_id: EdgeState}

    # Alias kept for backward compatibility with MQTT / twin
    @property
    def event(self):
        return self.dominant_event

    @property
    def density(self):
        return self.vehicle_count


# ── Internal helpers ──────────────────────────────────────────────────────────

def _discover_edges(tl_ids: list[str]) -> set:
    """
    Auto-discover road edges from each TL's controlled lanes.
    Lane format: "edge_id_laneIndex" — strip trailing _N to get edge.
    Internal junction edges (:prefix) are excluded.
    """
    edges = set()
    for tl_id in tl_ids:
        try:
            for lane in traci.trafficlight.getControlledLanes(tl_id):
                edge = lane.rsplit("_", 1)[0]
                if not edge.startswith(":"):
                    edges.add(edge)
        except Exception:
            pass
    return edges


def _centroid(tl_ids: list[str]) -> tuple:
    """Average (x, y) of all TL junctions — zone centre point."""
    xs, ys = [], []
    for tl_id in tl_ids:
        try:
            x, y = traci.junction.getPosition(tl_id)
            xs.append(x); ys.append(y)
        except Exception:
            pass
    return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)


def _compute_radii(zones: list) -> list[float]:
    """
    Assign each zone a radius = ZONE_RADIUS_FRAC × nearest-centroid distance,
    clamped to [ZONE_RADIUS_MIN, ZONE_RADIUS_MAX].
    This guarantees no two zone outlines overlap.
    """
    n = len(zones)
    radii = []
    for i, z in enumerate(zones):
        min_dist = float("inf")
        for j, other in enumerate(zones):
            if i == j:
                continue
            d = math.hypot(z.cx - other.cx, z.cy - other.cy)
            min_dist = min(min_dist, d)
        r = min_dist * ZONE_RADIUS_FRAC if min_dist < float("inf") else ZONE_RADIUS_MAX
        radii.append(min(ZONE_RADIUS_MAX, r))   # only cap at max; no floor clamp
    return radii


def _circle_shape(cx: float, cy: float, r: float, n: int = ZONE_N_POINTS) -> list:
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def _draw_zone_outline(zone: Zone):
    """
    Draw (or redraw) the zone as a thin outline circle on the SUMO GUI.
    fill=False keeps the road network fully visible.
    """
    shape = _circle_shape(zone.cx, zone.cy, zone.radius)
    try:
        if zone.zone_id in traci.polygon.getIDList():
            traci.polygon.remove(zone.zone_id)
    except Exception:
        pass
    try:
        traci.polygon.add(
            zone.zone_id,
            shape,
            color=ZONE_OUTLINE_COLOR,
            fill=False,
            layer=5,
            polygonType="rsu_zone_outline",
        )
    except Exception:
        pass   # headless — no GUI


# ── Public API ────────────────────────────────────────────────────────────────

def build_zone_from_def(zdef, valid_edges: set = None) -> "Zone":
    """
    Convert a ZoneDef (from zone_builder.py) into a full Zone object.
    Optionally filters edge_ids against valid_edges to drop unknown edges.
    Call assign_radii([…]) afterward to compute non-overlapping GUI radii.
    """
    edges = zdef.edge_ids
    if valid_edges is not None:
        edges = edges & valid_edges
    return Zone(
        zone_id  = zdef.zone_id,
        tl_ids   = [zdef.tl_id],
        edge_ids = edges,
        cx       = zdef.center_x,
        cy       = zdef.center_y,
    )


def build_zone(zone_id: str, tl_ids: list[str], extra_edges: list = None,
               valid_edges: set = None) -> Zone:
    """
    Build a Zone:
      1. Auto-discover edges from TL controlled lanes
      2. Merge with extra_edges
      3. Validate against the live SUMO network (drop unknown edges silently)
      4. Compute centroid from junction positions
      5. Draw initial outline polygon (radius assigned later by assign_radii())

    valid_edges: pass the result of traci.edge.getIDList() once at startup
                 to avoid per-build TraCI calls and silence "not known" errors.
    """
    edges = _discover_edges(tl_ids)
    if extra_edges:
        edges.update(e for e in extra_edges if not e.startswith(":"))

    # Drop any edge that doesn't exist in this SUMO network
    if valid_edges is not None:
        before = len(edges)
        edges  = edges & valid_edges
        dropped = before - len(edges)
        if dropped:
            print(f"   ⚠️  {zone_id}: dropped {dropped} unknown extra_edges")

    cx, cy = _centroid(tl_ids)
    zone   = Zone(zone_id=zone_id, tl_ids=tl_ids, edge_ids=edges, cx=cx, cy=cy)
    return zone


def assign_radii(zones: list[Zone]):
    """
    After ALL zones are built, compute non-overlapping radii and draw outlines.
    Must be called once, after all build_zone() calls.
    """
    radii = _compute_radii(zones)
    for zone, r in zip(zones, radii):
        zone.radius = r
        _draw_zone_outline(zone)


def compute_zone_state(zone: Zone, edge_states: dict[str, EdgeState]) -> ZoneState:
    """
    Aggregate per-edge states for all edges belonging to this zone.

    dominant_event priority:  congestion > slowdown > free_flow > unknown
    avg_speed: mean across edges that have at least one vehicle.
    """
    EVENT_PRIORITY = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}

    zone_edge_states = {eid: edge_states[eid]
                        for eid in zone.edge_ids
                        if eid in edge_states}

    active = [s for s in zone_edge_states.values() if s.vehicle_count > 0]

    total_vehicles = sum(s.vehicle_count for s in zone_edge_states.values())
    avg_speed      = (sum(s.avg_speed for s in active) / len(active)) if active else 0.0

    if active:
        dominant = max(active, key=lambda s: EVENT_PRIORITY.get(s.event, 0))
        dominant_event = dominant.event
    else:
        dominant_event = "unknown"

    return ZoneState(
        zone_id        = zone.zone_id,
        vehicle_count  = total_vehicles,
        avg_speed      = round(avg_speed, 2),
        dominant_event = dominant_event,
        edge_states    = zone_edge_states,
    )


def sense_all_zones(zones: list[Zone], edge_states: dict[str, EdgeState]) -> list[ZoneState]:
    """Aggregate edge_states into ZoneState for every zone."""
    return [compute_zone_state(z, edge_states) for z in zones]
