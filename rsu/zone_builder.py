# zone_builder.py — auto-builds MECE RSU zones from the live SUMO network.
#
# Strategy
# ────────
# 1. Locate every traffic-light junction in the network using TraCI.
#    For cluster-junction IDs (e.g. "cluster_...") the primary lookup is
#    traci.junction.getPosition(); the fallback averages the shape start-points
#    of all controlled lanes — works for every TL type SUMO supports.
#
# 2. Get every non-internal road edge from the live network
#    (traci.edge.getIDList(), drop those starting with ":").
#
# 3. Assign each edge to its nearest TL centroid (Voronoi nearest-neighbour).
#    This guarantees:
#       Mutually Exclusive    — every edge in exactly one zone
#       Collectively Exhaustive — every edge is covered
#    Zero manual configuration required.
#
# Adaptive sizing
# ───────────────
# Dense TL clusters (major intersections, market areas)
#   → many nearby TL seeds → small Voronoi cells → fine-grained zones
#     that capture complex multi-movement traffic patterns.
#
# Isolated TLs on straight arterial roads
#   → few nearby TL seeds → large Voronoi cell → broad zone covering
#     the full corridor between junctions.
#
# All O(|edges| × |TLs|) work runs ONCE at startup (≈100 k operations for
# the Bengaluru network).  No TraCI calls are made during the main loop.

import traci
from dataclasses import dataclass, field


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class ZoneDef:
    """
    Lightweight descriptor of one RSU zone.
    Contains no GUI state — pass to rsu_manager.build_zone_from_def()
    to get a full Zone with visual overlay support.
    """
    zone_id:  str            # human-readable "zone_01" … "zone_35"
    tl_id:    str            # SUMO traffic-light ID used as zone seed
    center_x: float          # zone centroid x (SUMO network coords, m)
    center_y: float          # zone centroid y
    edge_ids: set[str] = field(default_factory=set)

    @property
    def edge_count(self) -> int:
        return len(self.edge_ids)


# ── Internal geometry helpers ─────────────────────────────────────────────────

def _tl_centroid(tl_id: str) -> tuple[float, float] | None:
    """
    Return (x, y) of a traffic-light junction.
    Primary:  traci.junction.getPosition() — fast O(1) TraCI call.
    Fallback: average the first shape-point of every controlled lane —
              handles cluster junction IDs that may lack a direct junction entry.
    """
    try:
        x, y = traci.junction.getPosition(tl_id)
        if abs(x) > 0.01 or abs(y) > 0.01:   # (0,0) means "not found" in SUMO
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


def _edge_midpoint(edge_id: str) -> tuple[float, float]:
    """
    Return a representative (x, y) for an edge — midpoint of lane-0's shape.
    Falls back to (0, 0) only if TraCI has no shape data for this edge.
    """
    try:
        shape = traci.lane.getShape(f"{edge_id}_0")
        if shape:
            return shape[len(shape) // 2]
    except Exception:
        pass
    return (0.0, 0.0)


# ── Public API ────────────────────────────────────────────────────────────────

def build_mece_zones(verbose: bool = True) -> list[ZoneDef]:
    """
    Partition ALL non-internal edges in the network into MECE RSU zones.
    Must be called AFTER traci.start().

    Returns a list of ZoneDef sorted by zone_id ("zone_01", "zone_02", …).
    Each ZoneDef.edge_ids contains the complete, non-overlapping set of
    road edges that an RSU at that location is responsible for monitoring.
    """
    # ── 1. Collect TL centroids ───────────────────────────────────────────────
    tl_ids  = list(traci.trafficlight.getIDList())
    centers: dict[str, tuple[float, float]] = {}
    for tl_id in tl_ids:
        pos = _tl_centroid(tl_id)
        if pos is not None:
            centers[tl_id] = pos

    if not centers:
        raise RuntimeError("zone_builder: could not locate any TL positions.")

    tl_list = list(centers)
    cx_arr  = [centers[t][0] for t in tl_list]
    cy_arr  = [centers[t][1] for t in tl_list]
    n_tl    = len(tl_list)

    # ── 2. Voronoi assignment (O(|edges| × |TLs|)) ───────────────────────────
    all_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
    bucket: dict[str, set[str]] = {t: set() for t in tl_list}

    for eid in all_edges:
        mx, my   = _edge_midpoint(eid)
        best_i   = 0
        best_dsq = (mx - cx_arr[0]) ** 2 + (my - cy_arr[0]) ** 2
        for k in range(1, n_tl):
            dsq = (mx - cx_arr[k]) ** 2 + (my - cy_arr[k]) ** 2
            if dsq < best_dsq:
                best_dsq = dsq
                best_i   = k
        bucket[tl_list[best_i]].add(eid)

    # ── 3. Build and sort ZoneDef list ───────────────────────────────────────
    zones = sorted(
        [
            ZoneDef(
                zone_id  = f"zone_{i + 1:02d}",
                tl_id    = tl_id,
                center_x = centers[tl_id][0],
                center_y = centers[tl_id][1],
                edge_ids = bucket[tl_id],
            )
            for i, tl_id in enumerate(tl_list)
        ],
        key=lambda z: z.zone_id,
    )

    if verbose:
        n_total = sum(z.edge_count for z in zones)
        avg     = n_total / len(zones) if zones else 0
        sizes   = sorted(z.edge_count for z in zones)
        print(f"   {len(zones)} MECE zones | {n_total} edges total | "
              f"avg {avg:.0f} edges/zone | range [{sizes[0]}–{sizes[-1]}]")

    return zones
