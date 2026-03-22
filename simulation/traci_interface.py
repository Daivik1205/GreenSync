# traci_interface.py — Phase 1
# Python interface to the SUMO simulation via TraCI.
# Starts SUMO, steps through simulation, and exposes raw vehicle + edge state.
# All other phases consume data from here.

import traci
import os
import time

SUMO_CFG     = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "greensync_phase1", "map.sumocfg"))
GUI_DELAY_MS = 100   # ms per step in GUI — controls how fast vehicles move visually


def start(headless: bool = True):
    """
    Start the SUMO simulation.

    headless=True  (default / RPi)
        Launches `sumo` — no window, pure data pipeline.

    headless=False (mentor demo / dev)
        Launches `sumo-gui` via traci.start().
        MUST be run via ./run.sh so that X11 env vars
        (DISPLAY, XAUTHORITY, FONTCONFIG_FILE, PROJ_DATA)
        are already exported and inherited by the subprocess.
        Do NOT use python main.py directly in GUI mode.
    """
    if 'SUMO_HOME' not in os.environ:
        print("WARNING: SUMO_HOME not set — XML validation disabled.")

    if headless:
        traci.start(["sumo", "-c", SUMO_CFG, "--no-step-log", "--no-warnings"])

    else:
        # X11 env vars are exported by run.sh before Python starts.
        # Set defaults here only as a safety fallback.
        os.environ.setdefault("DISPLAY",         ":0")
        os.environ.setdefault("XAUTHORITY",      os.path.expanduser("~/.Xauthority"))
        os.environ.setdefault("FONTCONFIG_FILE", "/opt/homebrew/etc/fonts/fonts.conf")
        sumo_home = os.environ.get("SUMO_HOME", "")
        if sumo_home:
            os.environ.setdefault("PROJ_DATA", os.path.join(sumo_home, "data", "proj"))

        print("🚦 Launching sumo-gui...")
        # traci.start() manages the subprocess + connection together —
        # this is more reliable than subprocess.Popen + traci.connect() separately.
        traci.start([
            "sumo-gui",
            "-c",        SUMO_CFG,
            "--delay",   str(GUI_DELAY_MS),
            "--no-warnings",
        ])
        print("✅ Connected — simulation running")


def step() -> list[dict]:
    """
    Advance simulation by one step.

    Returns a list of vehicle state dicts:
        id           — vehicle ID string
        position     — (x, y) coordinates in SUMO network space
        speed        — current speed in m/s
        edge_id      — road edge the vehicle is currently on
        lane_id      — specific lane ID
        waiting_time — accumulated time (s) vehicle has been stopped (speed < 0.1 m/s)
                       used downstream for queue length estimation
    """
    traci.simulationStep()
    vehicles = []
    for vid in traci.vehicle.getIDList():
        vehicles.append({
            "id":           vid,
            "position":     traci.vehicle.getPosition(vid),
            "speed":        traci.vehicle.getSpeed(vid),
            "edge_id":      traci.vehicle.getRoadID(vid),
            "lane_id":      traci.vehicle.getLaneID(vid),
            "waiting_time": traci.vehicle.getAccumulatedWaitingTime(vid),
        })
    return vehicles


def _interpret_signal_string(signal_str: str) -> str:
    """
    Interpret a SUMO signal string into GREEN / YELLOW / RED.

    SUMO signal chars:
        G / g  — green (g = green with lower priority / yielding)
        s      — green-minor (stop-and-go)
        y / Y  — yellow
        r / R  — red
        u      — red + yellow (used in some European signal programs)

    Priority: any green/s → GREEN, elif any yellow/u → YELLOW, else RED.
    """
    s = signal_str.lower()
    if 'g' in s or 's' in s:
        return "GREEN"
    elif 'y' in s or 'u' in s:
        return "YELLOW"
    return "RED"


def get_traffic_light_state(tl_id: str) -> dict:
    """
    Get current signal state and time remaining for one traffic light junction.

    Returns:
        tl_id              — traffic light ID
        phase_index        — integer phase index (0, 1, 2 ...)
        signal_string      — raw SUMO signal string e.g. 'GGrrGGrr'
        phase_label        — human-readable: GREEN | YELLOW | RED
        duration_remaining — seconds until this phase ends (next switch)
        current_time       — simulation clock (seconds)
    """
    current_time  = traci.simulation.getTime()
    next_switch   = traci.trafficlight.getNextSwitch(tl_id)
    signal_string = traci.trafficlight.getRedYellowGreenState(tl_id)

    return {
        "tl_id":              tl_id,
        "phase_index":        traci.trafficlight.getPhase(tl_id),
        "signal_string":      signal_string,
        "phase_label":        _interpret_signal_string(signal_string),
        "duration_remaining": round(max(next_switch - current_time, 0.0), 1),
        "current_time":       current_time,
    }


def get_all_traffic_light_ids() -> list[str]:
    return list(traci.trafficlight.getIDList())


def get_edge_vehicle_count(edge_id: str) -> int:
    """
    Number of vehicles on an edge in the last simulation step.
    Used by RSU zone sensing to compute density.
    """
    return traci.edge.getLastStepVehicleNumber(edge_id)


def get_edge_mean_speed(edge_id: str) -> float:
    """
    Mean speed of vehicles on an edge in the last simulation step (m/s).
    Returns 0.0 if no vehicles are present.
    Used by RSU zone sensing to compute average zone speed.
    """
    return traci.edge.getLastStepMeanSpeed(edge_id)


def reroute_vehicle(vehicle_id: str, new_edges: list[str]):
    """
    Feed routing decisions back into SUMO — closes the Phase 10 loop.
    new_edges must be a list of consecutive SUMO edge IDs forming a valid route.
    """
    traci.vehicle.setRoute(vehicle_id, new_edges)


def stop():
    try:
        traci.close()
    except Exception:
        pass  # already disconnected (e.g. GUI was closed manually)
