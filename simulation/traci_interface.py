# traci_interface.py — Phase 1
# Python interface to the SUMO simulation via TraCI.
# Starts SUMO, steps through simulation, and exposes raw vehicle state.
# All other phases consume data from here.

import traci
import os
import sys

SUMO_CFG = "../greensync_phase1/map.sumocfg"


def start(headless: bool = True):
    """
    Start SUMO. Use headless=False for GUI during development.
    """
    if 'SUMO_HOME' not in os.environ:
        sys.exit("SUMO_HOME not set")

    binary = "sumo" if headless else "sumo-gui"
    traci.start([binary, "-c", SUMO_CFG])


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
