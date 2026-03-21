# rsu_manager.py — Phase 2
# RSU (Road-Side Unit) zone sensing simulation.
# Divides the map into geographic zones. For each zone, aggregates
# vehicle density and average speed from TraCI data to simulate
# what a physical RADAR/RSU would sense.
#
# NOTE: "RADAR sensing" here is simulated via TraCI — there is no
# physical sensor. This models the data an RSU would produce.

from dataclasses import dataclass, field


@dataclass
class Zone:
    zone_id: str
    edge_ids: list[str]        # SUMO edge IDs belonging to this zone
    lat: float = 0.0
    lng: float = 0.0


@dataclass
class ZoneState:
    zone_id: str
    vehicle_count: int
    avg_speed: float           # m/s
    density: float             # vehicles per 100m
    event: str = "free_flow"   # free_flow | slowdown | congestion


# Speed thresholds (m/s) — tune to Bengaluru conditions
CONGESTION_THRESHOLD = 2.0    # < 2 m/s (~7 km/h)
SLOWDOWN_THRESHOLD   = 6.0    # < 6 m/s (~22 km/h)


def detect_event(avg_speed: float) -> str:
    if avg_speed < CONGESTION_THRESHOLD:
        return "congestion"
    elif avg_speed < SLOWDOWN_THRESHOLD:
        return "slowdown"
    return "free_flow"


def compute_zone_state(zone: Zone, vehicles: list[dict]) -> ZoneState:
    """
    Given raw vehicle list from TraCI, compute state for one zone.
    """
    zone_vehicles = [v for v in vehicles if v["edge_id"] in zone.edge_ids]
    count = len(zone_vehicles)
    avg_speed = (sum(v["speed"] for v in zone_vehicles) / count) if count > 0 else 0.0
    density = count  # TODO: normalise by zone length in 100m units

    return ZoneState(
        zone_id=zone.zone_id,
        vehicle_count=count,
        avg_speed=round(avg_speed, 2),
        density=density,
        event=detect_event(avg_speed),
    )


def sense_all_zones(zones: list[Zone], vehicles: list[dict]) -> list[ZoneState]:
    return [compute_zone_state(z, vehicles) for z in zones]
