# classifier.py — Phase 4
# Edge-level event classification. Converts raw RSU zone state into
# structured events with severity. Runs at RSU level — no cloud needed.
#
# Events: free_flow | slowdown | congestion | obstacle | environmental

from dataclasses import dataclass


@dataclass
class TrafficEvent:
    zone_id: str
    event_type: str       # congestion | slowdown | free_flow | obstacle
    severity: str         # low | medium | high
    avg_speed: float
    vehicle_count: int


def classify(zone_state: dict) -> TrafficEvent:
    """
    Classify a zone state dict into a structured TrafficEvent.
    """
    event = zone_state.get("event", "free_flow")
    count = zone_state.get("vehicle_count", 0)
    speed = zone_state.get("avg_speed", 0.0)

    severity = _severity(event, count)

    return TrafficEvent(
        zone_id=zone_state["zone_id"],
        event_type=event,
        severity=severity,
        avg_speed=speed,
        vehicle_count=count,
    )


def _severity(event: str, vehicle_count: int) -> str:
    if event == "free_flow":
        return "low"
    if event == "slowdown":
        return "medium" if vehicle_count > 5 else "low"
    if event == "congestion":
        return "high" if vehicle_count > 15 else "medium"
    return "low"
