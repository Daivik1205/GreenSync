# router.py — Phase 8
# Eco-optimal routing engine using A* / Dijkstra on the Digital Twin graph.
# Cost function balances travel time, congestion, fuel, and CO₂.

import networkx as nx
from digital_twin.twin import DigitalTwin


# Weights for cost function — tune based on research objectives
W_TIME       = 0.4
W_CONGESTION = 0.3
W_CO2        = 0.3


def edge_cost(twin: DigitalTwin, from_zone: str, to_zone: str) -> float:
    """
    Compute cost of traversing an edge in the zone graph.
    Lower cost = preferred path.
    """
    state = twin.get_zone(to_zone)
    speed = max(state.get("avg_speed", 1.0), 0.5)  # avoid division by zero

    time_cost   = 1.0 / speed          # slower = higher cost
    congestion  = state.get("density", 0) / 20.0   # normalise to [0,1]
    co2_cost    = congestion            # congestion proxy for idle emissions

    return W_TIME * time_cost + W_CONGESTION * congestion + W_CO2 * co2_cost


def find_route(twin: DigitalTwin, origin: str, destination: str) -> list[str]:
    """
    Find eco-optimal route from origin to destination zone.
    Returns ordered list of zone IDs.
    """
    G = twin.graph

    try:
        path = nx.astar_path(
            G, origin, destination,
            weight=lambda u, v, _: edge_cost(twin, u, v)
        )
        return path
    except nx.NetworkXNoPath:
        return []


def zones_to_sumo_edges(path: list[str], zone_edge_map: dict[str, list[str]]) -> list[str]:
    """
    Convert zone path to flat list of SUMO edge IDs for TraCI rerouting.
    zone_edge_map: { zone_id: [sumo_edge_id, ...] }
    """
    edges = []
    for zone in path:
        edges.extend(zone_edge_map.get(zone, []))
    return edges
