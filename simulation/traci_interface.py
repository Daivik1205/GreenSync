# traci_interface.py — Phase 1
# Python interface to the SUMO simulation via TraCI.
# Starts SUMO, steps through simulation, and exposes raw vehicle state.
# All other phases consume data from here.

import traci
import os
import sys

SUMO_CFG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "greensync_phase1", "map.sumocfg")


GUI_TRACI_PORT = 8813   # port used when launching sumo-gui externally via `open -a`

def start(headless: bool = True, gui_port: int = None):
    """
    Start SUMO or connect to an already-running SUMO GUI instance.

    Modes:
      headless=True            → launch sumo (no window) — for dev + RPi
      headless=False           → connect to externally launched sumo-gui
                                 (launch it first via the shell script below)

    macOS GUI launch command (run in a separate terminal FIRST):
      open -a "/Applications/SUMO sumo-gui.app" --args \\
        -c "<abs_path>/greensync_phase1/map.sumocfg" \\
        --remote-port 8813 --start --delay 100

    Then run python main.py normally — TraCI will connect to port 8813.
    """
    if 'SUMO_HOME' not in os.environ:
        print("WARNING: SUMO_HOME not set — XML validation disabled. Continuing anyway.")

    if headless:
        cmd = ["sumo", "-c", SUMO_CFG, "--no-step-log"]
        traci.start(cmd)
    else:
        port = gui_port or GUI_TRACI_PORT
        print(f"Connecting to external SUMO GUI on port {port}...")
        print("Make sure you launched sumo-gui first with --remote-port 8813")
        traci.connect(port)


def step() -> list[dict]:
    """
    Advance simulation by one step.
    Returns raw vehicle state: [{ id, position, speed, edge_id, lane_id }]
    """
    traci.simulationStep()
    vehicles = []
    for vid in traci.vehicle.getIDList():
        vehicles.append({
            "id": vid,
            "position": traci.vehicle.getPosition(vid),
            "speed": traci.vehicle.getSpeed(vid),
            "edge_id": traci.vehicle.getRoadID(vid),
            "lane_id": traci.vehicle.getLaneID(vid),
        })
    return vehicles


def get_traffic_light_state(tl_id: str) -> dict:
    """
    Get current phase and time remaining for a traffic light junction.
    """
    return {
        "tl_id": tl_id,
        "phase": traci.trafficlight.getPhase(tl_id),
        "phase_name": traci.trafficlight.getPhaseName(tl_id),
        "next_switch": traci.trafficlight.getNextSwitch(tl_id),
        "current_time": traci.simulation.getTime(),
    }


def get_all_traffic_light_ids() -> list[str]:
    return traci.trafficlight.getIDList()


def reroute_vehicle(vehicle_id: str, new_edges: list[str]):
    """
    Feed routing decisions back into SUMO — closes the loop (Phase 10).
    """
    traci.vehicle.setRoute(vehicle_id, new_edges)


def stop():
    traci.close()
