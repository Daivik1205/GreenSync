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

from simulation.traci_interface import start, step, get_all_traffic_light_ids, get_traffic_light_state, reroute_vehicle, stop
from rsu.rsu_manager import Zone, sense_all_zones
from communication.publisher import connect as mqtt_connect, publish_zone_state, publish_signal_phase, disconnect as mqtt_disconnect
from event_classifier.classifier import classify
from digital_twin.twin import DigitalTwin
from routing.router import find_route, zones_to_sumo_edges

# TODO: import AI models once trained

HEADLESS = False   # False = connect to externally launched sumo-gui (see traci_interface.py for launch cmd)
MAX_STEPS = None   # None = run indefinitely


def build_zones() -> list[Zone]:
    # TODO: load zone definitions from config or overpass_fetcher
    return []


def run():
    start(headless=HEADLESS)
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
