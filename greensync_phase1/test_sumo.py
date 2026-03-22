import traci
import os
import sys

if 'SUMO_HOME' not in os.environ:
    sys.exit("SUMO_HOME not set")

BASE_DIR = "/Users/aryangupta/Developer/GreenSync/greensync_phase1"
sumoCmd = ["sumo-gui", "-c", os.path.join(BASE_DIR, "map.sumocfg")]
traci.start(sumoCmd)

step = 0

while step < 200:
    traci.simulationStep()

    vehicle_ids = traci.vehicle.getIDList()

    print(f"\n--- Step {step} ---")

    for vid in vehicle_ids[:5]:  # limit output
        pos = traci.vehicle.getPosition(vid)
        speed = traci.vehicle.getSpeed(vid)

        print(f"{vid} -> Pos: {pos}, Speed: {round(speed,2)}")

    step += 1

traci.close()
