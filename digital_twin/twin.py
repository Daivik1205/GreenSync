# twin.py — Phase 5
# Digital Twin: real-time graph-based state store of the city.
# Nodes = zones, Edges = road connections between zones.
# Updated every simulation cycle with latest RSU + AI data.
#
# NOTE: This is a software state graph, not a physics simulation.

import networkx as nx
from datetime import datetime


class DigitalTwin:
    def __init__(self):
        self.graph = nx.DiGraph()
        self.last_updated: datetime = None

    def add_zone(self, zone_id: str, lat: float, lng: float, adjacent_zones: list[str]):
        self.graph.add_node(zone_id, lat=lat, lng=lng,
                            density=0, avg_speed=0, event="free_flow",
                            predicted_speed=None)
        for adj in adjacent_zones:
            self.graph.add_edge(zone_id, adj)

    def update_zone(self, zone_id: str, zone_state: dict, predicted_speed: float = None):
        if zone_id not in self.graph.nodes:
            return
        self.graph.nodes[zone_id].update({
            "density": zone_state.get("vehicle_count", 0),
            "avg_speed": zone_state.get("avg_speed", 0),
            "event": zone_state.get("event", "free_flow"),
            "predicted_speed": predicted_speed,
            "updated_at": datetime.now().isoformat(),
        })
        self.last_updated = datetime.now()

    def get_zone(self, zone_id: str) -> dict:
        return dict(self.graph.nodes[zone_id])

    def all_zones(self) -> list[str]:
        return list(self.graph.nodes)

    def adjacent_zones(self, zone_id: str) -> list[str]:
        return list(self.graph.successors(zone_id))

    def snapshot(self) -> dict:
        """Return full twin state — useful for Flutter heatmap."""
        return {
            zone: dict(self.graph.nodes[zone])
            for zone in self.graph.nodes
        }
