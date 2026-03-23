# rsu_manager.py — Phase 2
# RSU (Road-Side Unit) zone sensing simulation.
#
# Each zone wraps one or more real traffic light junctions from the
# Bengaluru SUMO network. At startup, road edges are auto-discovered
# from the traffic lights' controlled lanes, then merged with any
# manually specified extra_edges (for road segments between junctions).
#
# Zone state is visualised directly on the SUMO GUI as coloured
# semi-transparent circle polygons — green (free flow), amber
# (slowdown), red (congestion). Polygon colour updates every step.
#
# NOTE: "RADAR sensing" is simulated via TraCI — there is no physical
# sensor. This models the data a real RSU/RADAR would produce.

import math
import traci
from dataclasses import dataclass


# ── Polygon visual settings ────────────────────────────────────────────────
ZONE_RADIUS   = 600   # metres — circle radius on the SUMO map
ZONE_N_POINTS = 20    # polygon smoothness (more = rounder circle)

EVENT_COLORS = {
    "free_flow":  (0,   200,  0,  80),   # green,  semi-transparent
    "slowdown":   (255, 180,  0, 110),   # amber
    "congestion": (220,   0,  0, 140),   # red,    more opaque
    "unknown":    ( 80,  80, 255, 60),   # blue    (no vehicles yet)
}

# ── Speed thresholds (m/s) ─────────────────────────────────────────────────
CONGESTION_THRESHOLD = 2.0   # < 2 m/s  (~7  km/h) → congestion
SLOWDOWN_THRESHOLD   = 6.0   # < 6 m/s  (~22 km/h) → slowdown


# ── Data classes ───────────────────────────────────────────────────────────

@dataclass
class Zone:
    zone_id:  str
    tl_ids:   list[str]   # traffic light IDs anchoring this zone
    edge_ids: set          # road edges belonging to this zone
    cx:       float = 0.0  # centroid X in SUMO network space
    cy:       float = 0.0  # centroid Y in SUMO network space


@dataclass
class ZoneState:
    zone_id:       str
    vehicle_count: int
    avg_speed:     float   # m/s
    density:       float   # vehicles (normalised by zone length in Phase 5+)
    event:         str     # free_flow | slowdown | congestion | unknown


# ── Internal helpers ───────────────────────────────────────────────────────

def _discover_edges(tl_ids: list[str]) -> set:
    """
    Auto-discover road edges from each TL's controlled lanes.
    Lane format: "edge_id_laneIndex" — strip the trailing _N to get edge.
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
    """Average (x, y) position of all TL junctions — zone centre point."""
    xs, ys = [], []
    for tl_id in tl_ids:
        try:
            x, y = traci.junction.getPosition(tl_id)
            xs.append(x)
            ys.append(y)
        except Exception:
            pass
    return (sum(xs) / len(xs), sum(ys) / len(ys)) if xs else (0.0, 0.0)


def _circle_shape(cx: float, cy: float, r: float, n: int = ZONE_N_POINTS) -> list:
    """Return a list of (x, y) points forming a circle polygon."""
    return [
        (cx + r * math.cos(2 * math.pi * i / n),
         cy + r * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


# ── Polygon drawing ────────────────────────────────────────────────────────

def _draw_polygon(zone: Zone, event: str):
    """
    Add (or replace) the zone polygon on the SUMO GUI.
    Silently ignored in headless mode.
    """
    color = EVENT_COLORS.get(event, EVENT_COLORS["unknown"])
    shape = _circle_shape(zone.cx, zone.cy, ZONE_RADIUS)

    try:
        if zone.zone_id in traci.polygon.getIDList():
            traci.polygon.remove(zone.zone_id)
    except Exception:
        pass

    try:
        traci.polygon.add(
            zone.zone_id,
            shape,
            color=color,
            fill=True,
            layer=10,
            polygonType="rsu_zone",
        )
    except Exception:
        pass  # headless — no GUI, skip silently


def update_zone_visual(zone: Zone, event: str):
    """
    Efficiently update zone polygon colour without removing/re-adding.
    Falls back to full redraw if setColor fails.
    """
    color = EVENT_COLORS.get(event, EVENT_COLORS["unknown"])
    try:
        traci.polygon.setColor(zone.zone_id, color)
    except Exception:
        _draw_polygon(zone, event)


# ── Public API ─────────────────────────────────────────────────────────────

def build_zone(zone_id: str, tl_ids: list[str], extra_edges: list = None) -> Zone:
    """
    Build a Zone object:
      1. Auto-discover edges from TL controlled lanes
      2. Merge with extra_edges (manually specified road segments)
      3. Compute centroid from junction positions
      4. Draw initial blue polygon on SUMO GUI

    Must be called AFTER traci.start() so TraCI is connected.
    """
    edges = _discover_edges(tl_ids)
    if extra_edges:
        edges.update(e for e in extra_edges if not e.startswith(":"))

    cx, cy = _centroid(tl_ids)
    zone   = Zone(zone_id=zone_id, tl_ids=tl_ids, edge_ids=edges, cx=cx, cy=cy)

    _draw_polygon(zone, "unknown")   # blue circle → zone boundary visible immediately
    return zone


def compute_zone_state(zone: Zone, vehicles: list[dict]) -> ZoneState:
    """
    Compute zone state from live vehicle list.
    Only counts vehicles whose edge_id is in the zone's edge set.
    Internal junction edges (:prefix) are double-filtered for safety.
    """
    zone_vehicles = [
        v for v in vehicles
        if v["edge_id"] in zone.edge_ids
        and not v["edge_id"].startswith(":")
    ]
    count     = len(zone_vehicles)
    avg_speed = (sum(v["speed"] for v in zone_vehicles) / count) if count > 0 else 0.0
    event     = detect_event(avg_speed) if count > 0 else "unknown"

    return ZoneState(
        zone_id       = zone.zone_id,
        vehicle_count = count,
        avg_speed     = round(avg_speed, 2),
        density       = count,
        event         = event,
    )


def detect_event(avg_speed: float) -> str:
    if avg_speed < CONGESTION_THRESHOLD:
        return "congestion"
    elif avg_speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


def sense_all_zones(zones: list, vehicles: list[dict]) -> list:
    """Compute state for every zone and return list of ZoneState objects."""
    return [compute_zone_state(z, vehicles) for z in zones]
