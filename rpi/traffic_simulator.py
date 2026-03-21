# traffic_simulator.py
# Wraps the SUMO simulation via TraCI to extract per-junction
# queue lengths and signal phase data each simulation step.

def get_simulation_state(step: int) -> list[dict]:
    """
    Advance SUMO by one step and extract state for all junctions.
    Returns: list of {
        junction_id, phase, duration_remaining,
        queue_length, estimated_clearance_time
    }
    """
    pass


def start_simulation(sumo_cfg: str, headless: bool = True):
    """
    Start SUMO (gui or headless) and open TraCI connection.
    """
    pass


def stop_simulation():
    """
    Close TraCI connection and shut down SUMO.
    """
    pass
