# hybrid_twin.py — Phase B: Hybrid Predictive Digital Twin
#
# Extends the base DigitalTwin with two additional weight signals:
#
#   1. TomTom live speed baseline — replaces synthetic SUMO-only averages
#      with ground-truth road flow data, refreshed every 60 s.
#
#   2. Crowdsourced intent pressure — penalises edges preemptively when
#      many users have selected the same route, before physical congestion
#      appears in SUMO or TomTom.
#
# Edge weight formula (A* cost):
#
#   cost(u → v) = W_TIME       * (1 / blended_speed)
#               + W_CONGESTION * congestion_ratio
#               + W_INTENT     * intent_pressure(route_id)
#               + W_CO2        * congestion_proxy
#
# blended_speed = α * sumo_avg_speed + (1-α) * tomtom_current_speed
#   where α = SUMO_BLEND_WEIGHT (default 0.4).
#   If TomTom data is stale/unavailable, α falls back to 1.0 (SUMO only).

import math
import logging
from typing import TYPE_CHECKING

import networkx as nx

from digital_twin.twin import DigitalTwin

if TYPE_CHECKING:
    from backend.tomtom_poller   import TomTomPoller
    from backend.intent_aggregator import RouteIntentStore

logger = logging.getLogger(__name__)

# ── Cost function weights ─────────────────────────────────────────────────────
W_TIME       = 0.35
W_CONGESTION = 0.30
W_INTENT     = 0.20
W_CO2        = 0.15

SUMO_BLEND_WEIGHT = 0.4    # α in blended_speed above

# Maximum age (seconds) of TomTom data before we fall back to SUMO-only
TOMTOM_STALENESS_LIMIT = 180


class HybridDigitalTwin(DigitalTwin):
    """
    Drop-in replacement for DigitalTwin that fuses three data sources:
      • SUMO/RSU zone states (inherited from DigitalTwin.update_zone)
      • TomTom Traffic Flow API baselines
      • Crowdsourced routing intents from Android clients
    """

    def __init__(self,
                 tomtom_poller:  "TomTomPoller | None"  = None,
                 intent_store:   "RouteIntentStore | None" = None):
        super().__init__()
        self._tomtom  = tomtom_poller
        self._intents = intent_store

        # Mapping zone_id → nearest TomTom sample point key ("{lat},{lon}")
        # Populated lazily when zones are added.
        self._zone_to_point: dict[str, str] = {}

        # Mapping zone_id → set of route_ids that pass through it.
        # Populated when register_route_zones() is called.
        self._zone_routes: dict[str, set[str]] = {}

    # ── Zone registration ─────────────────────────────────────────────────────

    def add_zone(self, zone_id: str, lat: float, lng: float, adjacent_zones: list[str]):
        super().add_zone(zone_id, lat, lng, adjacent_zones)
        self._zone_to_point[zone_id] = self._nearest_tomtom_point(lat, lng)

    def register_route_zones(self, route_id: str, zone_ids: list[str]):
        """
        Call this when an OSRM route is computed to link route → zones.
        Used by the intent pressure term to penalise specific zone paths.
        """
        for zid in zone_ids:
            self._zone_routes.setdefault(zid, set()).add(route_id)

    # ── Hybrid edge cost ──────────────────────────────────────────────────────

    def edge_cost(self, from_zone: str, to_zone: str) -> float:
        """
        Hybrid cost combining SUMO state, TomTom baseline, and intent pressure.
        Used as the NetworkX A* weight function.
        """
        node = self.graph.nodes.get(to_zone, {})

        sumo_speed   = max(float(node.get("avg_speed", 1.0)), 0.5)
        tomtom_speed = self._tomtom_speed_for(to_zone)
        blended_speed = self._blend(sumo_speed, tomtom_speed)

        congestion_ratio = 1.0 - min(blended_speed / 60.0, 1.0)   # 60 km/h = free-flow
        intent_pressure  = self._intent_pressure_for(to_zone)
        co2_proxy        = congestion_ratio * float(node.get("density", 0)) / 20.0

        cost = (
            W_TIME       * (1.0 / blended_speed)
            + W_CONGESTION * congestion_ratio
            + W_INTENT     * intent_pressure
            + W_CO2        * co2_proxy
        )
        return cost

    def find_route(self, origin: str, destination: str) -> list[str]:
        """A* routing using the hybrid cost function."""
        try:
            return nx.astar_path(
                self.graph, origin, destination,
                weight=lambda u, v, _: self.edge_cost(u, v),
            )
        except nx.NetworkXNoPath:
            return []

    # ── TomTom integration ────────────────────────────────────────────────────

    def _tomtom_speed_for(self, zone_id: str) -> float | None:
        """Returns TomTom current speed (km/h) for the zone, or None if unavailable."""
        if self._tomtom is None:
            return None
        import time
        if time.time() - self._tomtom.last_poll_at > TOMTOM_STALENESS_LIMIT:
            return None
        point_key = self._zone_to_point.get(zone_id)
        if not point_key:
            return None
        flow = self._tomtom.get_flow(point_key)
        return flow.current_speed if flow else None

    def _blend(self, sumo_speed: float, tomtom_speed: float | None) -> float:
        if tomtom_speed is None:
            return sumo_speed
        alpha = SUMO_BLEND_WEIGHT
        return alpha * sumo_speed + (1.0 - alpha) * tomtom_speed

    def _nearest_tomtom_point(self, lat: float, lng: float) -> str:
        """Find closest TomTom sample point key by Euclidean distance."""
        from backend.tomtom_poller import BENGALURU_SAMPLE_POINTS
        best_key, best_dist = "", float("inf")
        for p_lat, p_lon in BENGALURU_SAMPLE_POINTS:
            d = math.hypot(lat - p_lat, lng - p_lon)
            if d < best_dist:
                best_dist = d
                best_key  = f"{p_lat},{p_lon}"
        return best_key

    # ── Intent pressure ───────────────────────────────────────────────────────

    def _intent_pressure_for(self, zone_id: str) -> float:
        """
        Sum of intent pressure across all routes that pass through this zone.
        Higher = more users heading this way = preemptive penalty.
        """
        if self._intents is None:
            return 0.0
        route_ids = self._zone_routes.get(zone_id, set())
        if not route_ids:
            return 0.0
        total = sum(self._intents.route_pressure_factor(rid) for rid in route_ids)
        return min(total, 1.0)   # cap at 1.0 so it doesn't dominate

    # ── Diagnostic ───────────────────────────────────────────────────────────

    def diagnostics(self) -> dict:
        """Returns a snapshot of V2 blend quality for monitoring."""
        import time
        tomtom_age = (time.time() - self._tomtom.last_poll_at) if self._tomtom else None
        intent_stats = self._intents.stats() if self._intents else {}
        return {
            "tomtom_age_seconds": round(tomtom_age, 1) if tomtom_age is not None else None,
            "tomtom_stale":       tomtom_age > TOMTOM_STALENESS_LIMIT if tomtom_age else True,
            "sumo_blend_weight":  SUMO_BLEND_WEIGHT,
            **intent_stats,
        }
