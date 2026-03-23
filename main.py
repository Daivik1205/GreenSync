# main.py — Phase 10: Full System Integration
#
# Orchestrates the complete GreenSync loop:
#   SUMO → TraCI → RSU sensing → MQTT → Digital Twin → AI
#   → Event classification → Propagation → Routing → back to SUMO
#
# Data flow:
#   simulation.step()          Phase 1: raw vehicle state
#   rsu.sense_all_zones()      Phase 2: zone density + speed + GUI polygons
#   publisher.publish_*()      Phase 3: MQTT broadcast
#   classifier.classify()      Phase 4: structured events
#   twin.update_zone()         Phase 5: digital twin state update
#   gru.predict()              Phase 6: predicted future speed
#   propagator.propagate()     Phase 7: cascading event detection
#   router.find_route()        Phase 8: eco-optimal route
#   traci.reroute_vehicle()    Phase 10: feed back into SUMO

import time

from simulation.traci_interface  import (start, step, get_all_traffic_light_ids,
                                          get_traffic_light_state, reroute_vehicle, stop)
from rsu.rsu_manager             import build_zone, sense_all_zones, update_zone_visual
from rsu.zones_config            import ZONE_DEFINITIONS
from communication.publisher     import (connect as mqtt_connect, publish_zone_state,
                                          publish_signal_phase, disconnect as mqtt_disconnect)
from event_classifier.classifier import classify
from digital_twin.twin           import DigitalTwin
from routing.router              import find_route, zones_to_sumo_edges

HEADLESS   = True   # True = headless (RPi/CI). False = GUI via ./run.sh
MAX_STEPS  = None   # None = run indefinitely
STEP_DELAY = 0.05   # seconds between steps in GUI mode

# Event icons for terminal output
EVENT_ICON = {
    "free_flow":  "🟢",
    "slowdown":   "🟡",
    "congestion": "🔴",
    "unknown":    "⚪",
}


def build_zones():
    """
    Build all 6 RSU zones from zones_config.
    Must be called AFTER traci.start() — needs live TraCI connection
    to auto-discover edges and compute junction centroids.
    Draws initial blue polygon for each zone on the SUMO GUI.
    """
    zones = []
    print("\n📡 Building RSU zones...")
    for defn in ZONE_DEFINITIONS:
        zone = build_zone(
            zone_id     = defn["zone_id"],
            tl_ids      = defn["tl_ids"],
            extra_edges = defn.get("extra_edges", []),
        )
        print(f"   ✅ {zone.zone_id:<28}  {len(zone.edge_ids):>3} edges  "
              f"centroid ({zone.cx:>9.1f}, {zone.cy:>9.1f})")
        zones.append(zone)
    print(f"📡 {len(zones)} zones ready\n")
    return zones


def _print_step(sim_step: int, vehicles: list, zone_states: list):
    """Pretty-print vehicle table + zone states every 50 steps."""
    print(f"\n{'━'*65}")
    print(f"  Step {sim_step:>5} | Vehicles: {len(vehicles):>3} | Zones: {len(zone_states)}")
    print(f"{'━'*65}")

    if zone_states:
        print(f"  {'ZONE':<28} {'VEH':>4}  {'SPD m/s':>7}  STATUS")
        print(f"  {'-'*28} {'-'*4}  {'-'*7}  {'-'*18}")
        for zs in zone_states:
            icon = EVENT_ICON.get(zs.event, "⚪")
            print(f"  {zs.zone_id:<28} {zs.vehicle_count:>4}  "
                  f"{zs.avg_speed:>7.2f}  {icon} {zs.event}")
        print()

    print(f"  {'ID':<8} {'km/h':>6} {'X':>10} {'Y':>10}  {'Edge'}")
    print(f"  {'-'*8} {'-'*6} {'-'*10} {'-'*10}  {'-'*22}")
    for v in vehicles[:20]:
        speed_kmh = round(v["speed"] * 3.6, 1)
        x, y      = round(v["position"][0], 2), round(v["position"][1], 2)
        print(f"  {v['id']:<8} {speed_kmh:>6.1f} {x:>10} {y:>10}  {v['edge_id']}")
    print(flush=True)


def run():
    start(HEADLESS)

    if not HEADLESS:
        print("\n" + "━" * 55)
        print("  GreenSync — SUMO GUI mode")
        print("  ⚠️  Do NOT click Play ▶ in the GUI window.")
        print("  Python drives every step via TraCI.")
        print("  Zone polygons will appear on the map.")
        print("━" * 55 + "\n")

    # Build zones AFTER start() — needs live TraCI connection
    zones = build_zones()
    mqtt  = mqtt_connect()
    twin  = DigitalTwin()

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # Phase 1 — raw vehicle state from SUMO
            vehicles = step()

            # Phase 2 — RSU zone sensing
            zone_states = sense_all_zones(zones, vehicles)

            # Update zone polygon colours on the GUI
            for zs, zone in zip(zone_states, zones):
                update_zone_visual(zone, zs.event)

            # Terminal output every 50 steps
            if sim_step % 50 == 0:
                _print_step(sim_step, vehicles, zone_states)

            # GUI pacing
            if not HEADLESS:
                time.sleep(STEP_DELAY)

            for zs in zone_states:
                zs_dict = zs.__dict__

                # Phase 3 — MQTT broadcast
                publish_zone_state(mqtt, zs_dict)

                # Phase 4 — event classification
                event = classify(zs_dict)

                # Phase 5 — digital twin update
                twin.update_zone(zs.zone_id, zs_dict)

                # Phase 6 — AI prediction (TODO: wire in GRU)
                # Phase 7 — event propagation (TODO)

            # Phase 3 — publish signal phases
            for tl_id in get_all_traffic_light_ids():
                tl_state = get_traffic_light_state(tl_id)
                publish_signal_phase(mqtt, tl_id, tl_state)

            sim_step += 1

    finally:
        stop()
        mqtt_disconnect(mqtt)


if __name__ == "__main__":
    run()
