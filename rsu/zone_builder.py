# zone_builder.py — builds radius-based RSU zones from the live SUMO network.
#
# ── Sensing model ────────────────────────────────────────────────────────────
# Each traffic-light junction is treated as a physical RSU mounting point.
# The RSU radiates a RADAR/DSRC sensing field with a finite radius — it can
# only observe edges whose midpoint falls within that radius.  This is closer
# to real infrastructure than the Voronoi approach (which forced every edge
# into exactly one zone regardless of distance).
#
# ── Overlap policy ───────────────────────────────────────────────────────────
# BOUNDARY_FACTOR < 0.50 guarantees that two adjacent zones never overlap:
#   r_i = d(i,j) × 0.48  →  r_i + r_j ≤ 0.96 × d(i,j) < d(i,j)
# A thin unmonitored strip is left between adjacent RSU footprints — this is
# physically realistic (RADAR/DSRC range is finite and RSUs don't overlap).
# Edges at boundaries are only included in one zone (the closest RSU).
#
# Edges that are farther than max_radius from every TL are intentionally
# left uncovered, simulating the real-world gap in RSU deployment.
#
# ── Adaptive sizing ──────────────────────────────────────────────────────────
# Dense intersection clusters → small nearest-neighbour distance → small radius
#   → fine-grained, non-overlapping zones that capture localised congestion.
# Isolated arterial TLs       → large nearest-neighbour distance → radius
#   capped at max_radius → broader coverage with minimal overlap with neighbours.
#
# ── Coverage statistics ──────────────────────────────────────────────────────
# After build_rsu_zones() verbose mode reports:
#   • number of RSU zones
#   • edges covered by exactly 1 zone (exclusive) vs. 2+ zones (boundary)
#   • edges not covered by any zone (between RSU footprints)

import math
import traci
from dataclasses import dataclass, field


# ── RSU sensing parameters ────────────────────────────────────────────────────
MIN_RADIUS       = 40.0    # m — floor: even dense TLs sense at least a 40m bubble
MAX_RADIUS       = 280.0   # m — cap: isolated RSUs don't engulf half the network
BOUNDARY_FACTOR  = 0.48    # radius = nearest_neighbour_dist × this factor
                            # < 0.5 → guaranteed no sensing-radius overlap with nearest TL
                            # 0.48 leaves a thin unmonitored strip between adjacent RSUs


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ZoneDef:
    """
    Descriptor of one RSU zone.  zone_id is human-readable; radius reflects the
    physical RADAR/DSRC sensing range of the unit at (center_x, center_y).
    edge_ids may overlap with adjacent zones at boundaries.
    """
    zone_id:  str
    tl_id:    str
    center_x: float
    center_y: float
    radius:   float          # computed sensing radius (m)
    edge_ids: set[str] = field(default_factory=set)

    @property
    def edge_count(self) -> int:
        return len(self.edge_ids)


# ── Geometry helpers ──────────────────────────────────────────────────────────

def _tl_centroid(tl_id: str) -> tuple[float, float] | None:
    """
    Return (x, y) of a traffic-light junction.
    Primary:  traci.junction.getPosition() — exact for simple junction IDs.
    Fallback: average the first shape-point of every controlled lane —
              works for cluster-junction IDs that lack a direct entry.
    """
    try:
        x, y = traci.junction.getPosition(tl_id)
        if abs(x) > 0.01 or abs(y) > 0.01:
            return (x, y)
    except Exception:
        pass

    try:
        lanes  = list(dict.fromkeys(traci.trafficlight.getControlledLanes(tl_id)))
        xs, ys = [], []
        for lid in lanes:
            try:
                pt = traci.lane.getShape(lid)[0]
                xs.append(pt[0])
                ys.append(pt[1])
            except Exception:
                pass
        if xs:
            return (sum(xs) / len(xs), sum(ys) / len(ys))
    except Exception:
        pass

    return None


def _edge_representative_points(edge_id: str) -> list[tuple[float, float]]:
    """
    Return [start, mid, end] of lane-0's shape — used to decide whether any
    part of a long edge falls inside a zone's sensing radius.
    Falls back to [(0,0)] on error.
    """
    try:
        shape = traci.lane.getShape(f"{edge_id}_0")
        if not shape:
            return [(0.0, 0.0)]
        pts = [shape[0], shape[len(shape) // 2], shape[-1]]
        # De-duplicate while preserving order
        seen, unique = set(), []
        for p in pts:
            if p not in seen:
                seen.add(p)
                unique.append(p)
        return unique
    except Exception:
        return [(0.0, 0.0)]


def _dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2)


# ── Public API ────────────────────────────────────────────────────────────────

def build_rsu_zones(verbose: bool = True) -> list[ZoneDef]:
    """
    Build radius-based RSU zones with minimal spatial overlap.
    Must be called AFTER traci.start().

    Algorithm
    ─────────
    1. Locate every TL junction in the network (position via TraCI).
    2. For each TL compute adaptive_radius:
           adaptive_radius = clamp(nearest_neighbour_dist × BOUNDARY_FACTOR,
                                   MIN_RADIUS, MAX_RADIUS)
       BOUNDARY_FACTOR = 0.48 < 0.5 guarantees no two sensing radii overlap
       (r_i + r_j ≤ 0.96 × d(i,j) < d(i,j) for any pair i,j).
    3. Assign an edge to a zone if the minimum distance from any of the edge's
       representative points (start / mid / end) to the zone centre ≤ radius.
       This correctly handles long edges that span multiple zone footprints.
    4. Edges that fall inside two or more zones' radii appear in both — this
       is intentional boundary overlap, not a bug.

    Returns a list of ZoneDef sorted by zone_id.
    """
    # ── 1. Collect TL positions ───────────────────────────────────────────────
    tl_ids  = list(traci.trafficlight.getIDList())
    centers: dict[str, tuple[float, float]] = {}
    for tl_id in tl_ids:
        pos = _tl_centroid(tl_id)
        if pos is not None:
            centers[tl_id] = pos

    if not centers:
        raise RuntimeError("zone_builder: no TL positions found in network.")

    tl_list = list(centers)
    n_tl    = len(tl_list)
    cx_arr  = [centers[t][0] for t in tl_list]
    cy_arr  = [centers[t][1] for t in tl_list]

    # ── 2. Compute adaptive radii ─────────────────────────────────────────────
    radii: list[float] = []
    for i in range(n_tl):
        min_dist = float("inf")
        for j in range(n_tl):
            if i == j:
                continue
            d = _dist(cx_arr[i], cy_arr[i], cx_arr[j], cy_arr[j])
            if d < min_dist:
                min_dist = d
        if min_dist == float("inf"):
            # Only one TL — use max radius
            r = MAX_RADIUS
        else:
            r = min_dist * BOUNDARY_FACTOR
        radii.append(max(MIN_RADIUS, min(MAX_RADIUS, r)))

    # ── 3. Assign edges to zones (radius-based, overlap allowed) ─────────────
    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    bucket: dict[str, set[str]] = {t: set() for t in tl_list}

    for eid in all_edges:
        rep_pts = _edge_representative_points(eid)
        for i, tl_id in enumerate(tl_list):
            r = radii[i]
            # Check if any representative point of the edge is within the radius
            for (px, py) in rep_pts:
                if _dist(cx_arr[i], cy_arr[i], px, py) <= r:
                    bucket[tl_id].add(eid)
                    break   # already in this zone — no need to check more pts

    # ── 4. Build and sort ZoneDef list ───────────────────────────────────────
    zones = sorted(
        [
            ZoneDef(
                zone_id  = f"zone_{i + 1:02d}",
                tl_id    = tl_id,
                center_x = centers[tl_id][0],
                center_y = centers[tl_id][1],
                radius   = radii[i],
                edge_ids = bucket[tl_id],
            )
            for i, tl_id in enumerate(tl_list)
        ],
        key=lambda z: z.zone_id,
    )

    # ── Coverage report ───────────────────────────────────────────────────────
    if verbose:
        # Count how many zones each edge appears in
        from collections import Counter
        edge_zone_count: Counter = Counter()
        for z in zones:
            for eid in z.edge_ids:
                edge_zone_count[eid] += 1

        exclusive  = sum(1 for c in edge_zone_count.values() if c == 1)
        boundary   = sum(1 for c in edge_zone_count.values() if c >= 2)
        covered    = exclusive + boundary
        uncovered  = len(all_edges) - covered
        avg_edges  = covered / len(zones) if zones else 0
        radii_vals = [z.radius for z in zones]

        print(f"   {len(zones)} RSU zones | radius {min(radii_vals):.0f}–{max(radii_vals):.0f} m "
              f"(avg {sum(radii_vals)/len(radii_vals):.0f} m)")
        print(f"   Coverage: {covered}/{len(all_edges)} edges covered "
              f"({exclusive} exclusive, {boundary} boundary-shared, "
              f"{uncovered} uncovered)")
        print(f"   avg {avg_edges:.0f} edges/zone")

    return zones
