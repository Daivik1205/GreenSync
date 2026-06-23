# shadow_vehicle_injector.py — Phase C: Closed-loop SUMO shadow vehicles
#
# Mirrors real-world Kotlin client journeys into the running SUMO simulation
# as "shadow" vehicles. Each unique active user intent creates one shadow
# vehicle whose route tracks the user's selected waypoint path.
#
# How it works:
#   1. IntentAggregator receives a route intent (lat/lon waypoints).
#   2. ShadowVehicleInjector converts waypoints → nearest SUMO edges via
#      sumolib network geometry lookup.
#   3. A SUMO vehicle is added via traci.vehicle.add() on a synthetic
#      "shadow_route" with type "shadow_vehicle".
#   4. Each step, the shadow vehicle's position is updated to match the
#      real user's reported GPS (from ECU telemetry) if available.
#   5. When the intent expires (TTL), the shadow vehicle is removed.
#
# Shadow vehicles are visually distinct in SUMO GUI (blue, type="shadow").

import logging
import math
from typing import TYPE_CHECKING

import sumolib

if TYPE_CHECKING:
    import traci

logger = logging.getLogger(__name__)

SHADOW_TYPE_ID   = "shadow_vehicle"
SHADOW_COLOR     = (0, 120, 255, 200)   # RGBA — blue semi-transparent


class ShadowVehicleInjector:
    """
    Maintains a shadow vehicle in SUMO for every active user intent.
    Must be called once per simulation step via step().
    """

    def __init__(self, net_path: str, intent_store, traci_module=None):
        """
        net_path:     path to SUMO .net.xml for coordinate→edge lookup
        intent_store: RouteIntentStore instance
        traci_module: pass traci after traci.start(); defaults to import traci
        """
        self._net         = sumolib.net.readNet(net_path, withInternal=False)
        self._intents     = intent_store
        self._active: dict[str, str] = {}   # user_id → shadow vehicle ID in SUMO
        self._route_seq   = 0               # monotonic counter for unique route IDs

        if traci_module is None:
            import traci as _traci
            self._traci = _traci
        else:
            self._traci = traci_module

    # ── Per-step update ───────────────────────────────────────────────────────

    def step(self):
        """
        Called every simulation step.
        - Injects new shadow vehicles for new intents.
        - Removes shadow vehicles whose intents have expired.
        """
        active_intents  = self._intents._intents   # {user_id: UserIntent}
        intent_user_ids = set(active_intents.keys())
        shadow_user_ids = set(self._active.keys())

        # Inject new shadows
        for uid in intent_user_ids - shadow_user_ids:
            intent = active_intents[uid]
            self._inject(uid, intent)

        # Remove stale shadows
        for uid in shadow_user_ids - intent_user_ids:
            self._remove(uid)

        # Update positions from ECU telemetry
        self._update_speeds()

    # ── Vehicle type registration ─────────────────────────────────────────────

    def ensure_vehicle_type(self):
        """Register shadow_vehicle type if not already present. Call after traci.start()."""
        existing = self._traci.vehicletype.getIDList()
        if SHADOW_TYPE_ID not in existing:
            self._traci.vehicletype.copy("DEFAULT_VEHTYPE", SHADOW_TYPE_ID)
            self._traci.vehicletype.setColor(SHADOW_TYPE_ID, SHADOW_COLOR)
            self._traci.vehicletype.setLength(SHADOW_TYPE_ID, 4.5)
            logger.debug("Registered SUMO vehicle type '%s'", SHADOW_TYPE_ID)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _inject(self, user_id: str, intent):
        edges = self._waypoints_to_edges(intent.waypoints)
        if len(edges) < 2:
            logger.debug("Shadow inject skipped for %s — insufficient edges (%d)", user_id, len(edges))
            return

        self._route_seq += 1
        route_id  = f"shadow_route_{self._route_seq}"
        veh_id    = f"shadow_{user_id}"

        try:
            self._traci.route.add(route_id, edges)
            self._traci.vehicle.add(
                vehID=veh_id,
                routeID=route_id,
                typeID=SHADOW_TYPE_ID,
                depart="now",
                departLane="best",
                departSpeed="max",
            )
            self._active[user_id] = veh_id
            logger.info("Shadow vehicle injected: %s → edges %s…%s",
                        veh_id, edges[0], edges[-1])
        except self._traci.exceptions.TraCIException as exc:
            logger.warning("Shadow inject failed for %s: %s", user_id, exc)

    def _remove(self, user_id: str):
        veh_id = self._active.pop(user_id, None)
        if veh_id is None:
            return
        try:
            active_vehs = self._traci.vehicle.getIDList()
            if veh_id in active_vehs:
                self._traci.vehicle.remove(veh_id)
                logger.info("Shadow vehicle removed: %s", veh_id)
        except self._traci.exceptions.TraCIException as exc:
            logger.debug("Shadow remove error for %s: %s", veh_id, exc)

    def _update_speeds(self):
        """
        Apply real-world speed from ECU telemetry to matching shadow vehicles
        so their simulation behaviour reflects actual driving velocity.
        """
        telemetry_map = {t.user_id: t for t in self._intents.latest_telemetry()}
        active_vehs   = set(self._traci.vehicle.getIDList())

        for user_id, veh_id in self._active.items():
            if veh_id not in active_vehs:
                continue
            tel = telemetry_map.get(user_id)
            if tel and tel.speed_kmh is not None:
                speed_ms = tel.speed_kmh / 3.6
                try:
                    self._traci.vehicle.setSpeed(veh_id, speed_ms)
                except self._traci.exceptions.TraCIException:
                    pass

    def _waypoints_to_edges(self, waypoints: list[tuple[float, float]]) -> list[str]:
        """
        Convert GPS waypoints (lat, lon) to SUMO edge IDs.
        Uses sumolib's getNeighboringEdges to find closest edges.
        Returns deduplicated ordered edge list.
        """
        edges: list[str] = []
        for lat, lon in waypoints:
            x, y = self._net.convertLonLat2XY(lon, lat)
            nearby = self._net.getNeighboringEdges(x, y, r=100, includeJunctions=False)
            if not nearby:
                continue
            # Sort by distance, pick closest non-internal edge
            candidates = sorted(nearby, key=lambda e: e[1])
            for edge, _dist in candidates:
                eid = edge.getID()
                if not eid.startswith(":"):
                    if not edges or edges[-1] != eid:
                        edges.append(eid)
                    break
        return edges

    def active_count(self) -> int:
        return len(self._active)

    def active_shadows(self) -> dict[str, str]:
        """Returns {user_id: sumo_vehicle_id} for all live shadows."""
        return dict(self._active)
