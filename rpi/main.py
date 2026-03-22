# main.py
# Orchestrator — runs the main event loop:
#   1. Start SUMO simulation
#   2. Connect to MQTT broker + Supabase
#   3. Load XGBoost model
#   4. Each cycle: get simulation state → run inference → publish MQTT → log to Supabase

from traffic_simulator import start_simulation, get_simulation_state, stop_simulation
from inference_engine import load_model, predict
from mqtt_publisher import connect as mqtt_connect, publish_phase, publish_queue, disconnect as mqtt_disconnect
from supabase_logger import get_client, log_signal_event, log_queue_snapshot

SUMO_CFG = "../greensync_phase1/map.sumocfg"
CYCLE_LIMIT = None   # None = run indefinitely


def run():
    start_simulation(SUMO_CFG, headless=True)
    mqtt_client = mqtt_connect()
    supabase_client = get_client()
    model = load_model()

    step = 0
    try:
        while CYCLE_LIMIT is None or step < CYCLE_LIMIT:
            junctions = get_simulation_state(step)

            for j in junctions:
                prediction = predict(model, j["junction_id"], j["queue_length"])

                publish_phase(mqtt_client, j["junction_id"], j["phase"], prediction["phase_duration_predicted"])
                publish_queue(mqtt_client, j["junction_id"], j["queue_length"], j["estimated_clearance_time"])

                log_signal_event(supabase_client, j["junction_id"], j["phase"], prediction["phase_duration_predicted"])
                log_queue_snapshot(supabase_client, j["junction_id"], j["queue_length"], j["estimated_clearance_time"])

            step += 1

    finally:
        stop_simulation()
        mqtt_disconnect(mqtt_client)


if __name__ == "__main__":
    run()
