# propagator.py — Phase 7
# Models cascading traffic events across the zone graph.
# Example: congestion in Zone A propagates to adjacent Zone B, C.
# Uses BFS on the Digital Twin graph.

from collections import deque
from digital_twin.twin import DigitalTwin


def propagate(twin: DigitalTwin, source_zone: str, event_type: str,
              max_hops: int = 2) -> list[dict]:
    """
    BFS from source_zone. Mark adjacent zones as impacted.
    Returns list of impacted zones with propagated event info.
    """
    visited = set()
    queue = deque([(source_zone, 0)])
    impacted = []

    while queue:
        zone_id, hops = queue.popleft()
        if zone_id in visited or hops > max_hops:
            continue
        visited.add(zone_id)

        if hops > 0:
            impacted.append({
                "zone_id": zone_id,
                "caused_by": source_zone,
                "event_type": event_type,
                "hops_from_source": hops,
            })

        for adj in twin.adjacent_zones(zone_id):
            if adj not in visited:
                queue.append((adj, hops + 1))

    return impacted
