"""
explore_network.py — one-time script to inspect the Bengaluru SUMO network.
Run this once, capture the output, then delete.
Tells us: traffic light IDs, signal phases, and edge count for zone design.
"""

from simulation.traci_interface import start, stop, get_all_traffic_light_ids, get_traffic_light_state
import traci

print("Starting SUMO in headless mode...")
start(headless=True)

# Run a few steps so vehicles + signals are active
for _ in range(10):
    traci.simulationStep()

print("\n========== TRAFFIC LIGHTS ==========")
tl_ids = get_all_traffic_light_ids()
print(f"Total traffic lights: {len(tl_ids)}\n")

for tl_id in tl_ids:
    state = get_traffic_light_state(tl_id)
    controlled_lanes = traci.trafficlight.getControlledLanes(tl_id)
    controlled_links = traci.trafficlight.getControlledLinks(tl_id)
    print(f"TL: {tl_id}")
    print(f"   phase index   : {state['phase']}")
    print(f"   phase name    : {state['phase_name']}")
    print(f"   next switch   : {state['next_switch']:.1f}s")
    print(f"   current time  : {state['current_time']:.1f}s")
    print(f"   controlled lanes ({len(controlled_lanes)}): {list(controlled_lanes)[:4]}{'...' if len(controlled_lanes) > 4 else ''}")
    print()

print("\n========== EDGES ==========")
all_edges = [e for e in traci.edge.getIDList() if not e.startswith(':')]  # skip internal junction edges
print(f"Total road edges (excluding junctions): {len(all_edges)}")
print(f"First 20 edge IDs:")
for e in all_edges[:20]:
    print(f"   {e}")

print("\n========== ACTIVE VEHICLES ==========")
vehicle_ids = traci.vehicle.getIDList()
print(f"Active vehicles after 10 steps: {len(vehicle_ids)}")

stop()
print("\nDone. Use the traffic light IDs above to define RSU zones.")
