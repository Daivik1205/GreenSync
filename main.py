# main.py — Phase 10: Full System Integration
#
# Orchestrates the complete GreenSync loop:
#   SUMO → TraCI → RSU sensing → MQTT → Digital Twin → AI
#   → Event classification → Propagation → Routing → back to SUMO
#
# Data flow:
#   simulation.step()          Phase 1: raw vehicle state
#   rsu.sense_all_zones()      Phase 2: zone density + speed
#   publisher.publish_*()      Phase 3: MQTT broadcast
#   classifier.classify()      Phase 4: structured events
#   twin.update_zone()         Phase 5: digital twin state update
#   gru.predict()              Phase 6: predicted future speed
#   propagator.propagate()     Phase 7: cascading event detection
#   router.find_route()        Phase 8: eco-optimal route
#   traci.reroute_vehicle()    Phase 10: feed back into SUMO

import time

from simulation.traci_interface import start, step, get_all_traffic_light_ids, get_traffic_light_state, reroute_vehicle, stop
from rsu.rsu_manager import Zone, sense_all_zones
from communication.publisher import connect as mqtt_connect, publish_zone_state, publish_signal_phase, disconnect as mqtt_disconnect
from event_classifier.classifier import classify
from digital_twin.twin import DigitalTwin
from routing.router import find_route, zones_to_sumo_edges

# TODO: import AI models once trained

HEADLESS   = False  # False = GUI mode via run.sh. True = headless for RPi/CI.
MAX_STEPS  = None   # None = run indefinitely
STEP_DELAY = 0.05   # seconds between steps in GUI mode — controls how fast vehicles move visually


def build_zones() -> list[Zone]:
    # TODO: load zone definitions from zones_config
    return []


def run():
    start(HEADLESS)

    if not HEADLESS:
        print()
        print("━" * 55)
        print("  GreenSync simulation running")
        print("  sumo-gui is a VIEWER — Python drives every step.")
        print("  ⚠️  Do NOT click Play ▶ in the GUI window.")
        print("  Vehicles will appear and move automatically.")
        print("━" * 55)
        print()

    mqtt = mqtt_connect()
    twin = DigitalTwin()
    zones = build_zones()

    # TODO: initialise twin graph from zone adjacency config
    # TODO: load XGBoost + GRU models

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # Phase 1 — get raw vehicle state
            vehicles = step()

            if sim_step % 50 == 0:
                print(f"\n{'━'*60}")
                print(f"  Step {sim_step:>5} | Total vehicles: {len(vehicles):>3} | Zones: {len(zones)}")
                print(f"{'━'*60}")
                print(f"  {'ID':<8} {'Speed (km/h)':>12} {'X':>10} {'Y':>10}  {'Edge'}")
                print(f"  {'-'*8} {'-'*12} {'-'*10} {'-'*10}  {'-'*20}")
                for v in vehicles[:20]:
                    speed_kmh = round(v['speed'] * 3.6, 1)
                    x, y      = round(v['position'][0], 2), round(v['position'][1], 2)
                    print(f"  {v['id']:<8} {speed_kmh:>11.1f}  {x:>10} {y:>10}  {v['edge_id']}")
                print(flush=True)

            # Slow down the loop in GUI mode so vehicles move visibly
            if not HEADLESS:
                time.sleep(STEP_DELAY)

            # Phase 2 — RSU zone sensing
            zone_states = sense_all_zones(zones, vehicles)

            for zs in zone_states:
                zs_dict = zs.__dict__

                # Phase 3 — publish to MQTT
                publish_zone_state(mqtt, zs_dict)

                # Phase 4 — classify event
                event = classify(zs_dict)

                # Phase 5 — update digital twin
                twin.update_zone(zs.zone_id, zs_dict)

                # Phase 6 — AI prediction (TODO: wire in GRU)
                # predicted_speed = gru.predict(...)
                # twin.update_zone(zs.zone_id, zs_dict, predicted_speed)

                # Phase 7 — propagate if congestion detected
                # if event.event_type == "congestion":
                #     propagator.propagate(twin, zs.zone_id, event.event_type)

            # Phase 8 — reroute vehicles (TODO: per-vehicle routing)
            # for vehicle in vehicles:
            #     route = find_route(twin, origin_zone, dest_zone)
            #     sumo_edges = zones_to_sumo_edges(route, zone_edge_map)
            #     reroute_vehicle(vehicle["id"], sumo_edges)

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
