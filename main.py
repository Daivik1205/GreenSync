# main.py — Phase 10: Full System Integration
#
# Orchestrates the complete GreenSync loop:
#   SUMO → TraCI → RSU edge sensing → lane colouring → zone aggregation
#   → MQTT → Digital Twin → AI → Event classification → Propagation
#   → Routing → back to SUMO
#
# Data flow (per step):
#   simulation.step()              Phase 1: advance sim, get raw vehicle list
#   sense_edges(all_edges)         Phase 2a: per-edge speed/occupancy/event
#   color_edges(edge_states)       Phase 2a: paint roads green/amber/red in GUI
#   sense_all_zones(zones,edges)   Phase 2b: aggregate zone state from edges
#   publisher.publish_*()          Phase 3: MQTT broadcast
#   classifier.classify()          Phase 4: structured event record
#   twin.update_zone()             Phase 5: digital twin state update
#   gru.predict()                  Phase 6: predicted future speed  [TODO]
#   propagator.propagate()         Phase 7: cascading event detection [TODO]
#   router.find_route()            Phase 8: eco-optimal route        [TODO]
#   traci.reroute_vehicle()        Phase 10: feed back into SUMO

import time

from simulation.traci_interface  import (start, step, get_all_traffic_light_ids,
                                          get_traffic_light_state, reroute_vehicle, stop)
from rsu.rsu_manager             import build_zone, assign_radii, sense_all_zones
from rsu.zones_config            import ZONE_DEFINITIONS
from rsu.edge_detector           import (sense_edges, color_edges, reset_edge_colors,
                                          prime_edge_cache)
from communication.publisher     import (connect as mqtt_connect, publish_zone_state,
                                          publish_signal_phase, disconnect as mqtt_disconnect)
from event_classifier.classifier import classify
from digital_twin.twin           import DigitalTwin
from routing.router              import find_route, zones_to_sumo_edges

HEADLESS   = False   # True = headless (RPi/CI). False = GUI via ./run.sh
MAX_STEPS  = None    # None = run indefinitely
STEP_DELAY = 0.05    # seconds between steps in GUI mode

# Terminal event icons
EVENT_ICON = {
    "free_flow":  "🟢",
    "slowdown":   "🟡",
    "congestion": "🔴",
    "unknown":    "⚪",
}


def build_zones():
    """
    Build all RSU zones from zones_config.
    Must be called AFTER traci.start() — needs live TraCI connection.
    Draws non-overlapping outline circles for each zone on the SUMO GUI.
    """
    import traci as _traci
    # Fetch the full edge list ONCE — used to validate zone extra_edges
    valid_edges = set(_traci.edge.getIDList())

    zones = []
    print("\n📡 Building RSU zones...")
    for defn in ZONE_DEFINITIONS:
        zone = build_zone(
            zone_id     = defn["zone_id"],
            tl_ids      = defn["tl_ids"],
            extra_edges = defn.get("extra_edges", []),
            valid_edges = valid_edges,
        )
        zones.append(zone)

    # Compute non-overlapping radii and draw outlines in one pass
    assign_radii(zones)

    for zone in zones:
        print(f"   ✅ {zone.zone_id:<28}  {len(zone.edge_ids):>3} edges  "
              f"centroid ({zone.cx:>9.1f}, {zone.cy:>9.1f})  r={zone.radius:.0f} m")

    print(f"📡 {len(zones)} zones ready\n")
    return zones


def _all_zone_edges(zones) -> set:
    """Collect every edge that belongs to at least one zone."""
    edges = set()
    for z in zones:
        edges.update(z.edge_ids)
    return edges


def _print_step(sim_step: int, vehicles: list, zone_states: list):
    """Pretty-print zone summary + up to 20 vehicles every 50 steps."""
    print(f"\n{'━'*68}")
    print(f"  Step {sim_step:>5} | Vehicles: {len(vehicles):>3} | Zones: {len(zone_states)}")
    print(f"{'━'*68}")

    if zone_states:
        print(f"  {'ZONE':<28} {'VEH':>4}  {'SPD m/s':>7}  STATUS")
        print(f"  {'-'*28} {'-'*4}  {'-'*7}  {'-'*20}")
        for zs in zone_states:
            icon = EVENT_ICON.get(zs.dominant_event, "⚪")
            print(f"  {zs.zone_id:<28} {zs.vehicle_count:>4}  "
                  f"{zs.avg_speed:>7.2f}  {icon} {zs.dominant_event}")
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
        print("\n" + "━" * 58)
        print("  GreenSync — SUMO GUI mode")
        print("  ⚠️  Do NOT click Play ▶ in the GUI window.")
        print("  Python drives every step via TraCI.")
        print("  Roads: smooth green→yellow→orange→red gradient (Google Maps style).")
        print("  Zone outlines: thin blue circles (non-overlapping).")
        print("━" * 58 + "\n")

    zones     = build_zones()
    all_edges = _all_zone_edges(zones)

    # Pre-fetch speed limits + lane counts once — used for smooth colour gradient
    print("🎨 Priming edge colour cache...")
    prime_edge_cache(all_edges)
    print(f"   {len(all_edges)} edges cached\n")

    mqtt = mqtt_connect()
    twin = DigitalTwin()

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # ── Phase 1 — advance simulation, get raw vehicle list ──────────
            vehicles = step()

            # ── Phase 2a — per-edge sensing (primary detection layer) ───────
            # Each directed road edge is queried independently via TraCI
            # aggregated statistics (no vehicle-list scanning).
            edge_states = sense_edges(all_edges)

            # Paint lanes green / amber / red directly on the map
            color_edges(edge_states)

            # ── Phase 2b — zone aggregation (secondary / organisational) ────
            zone_states = sense_all_zones(zones, edge_states)

            # Terminal output every 50 steps
            if sim_step % 50 == 0:
                _print_step(sim_step, vehicles, zone_states)

            # GUI pacing
            if not HEADLESS:
                time.sleep(STEP_DELAY)

            # ── Phase 3–5 — MQTT, classification, digital twin ──────────────
            for zs in zone_states:
                zs_dict = {
                    "zone_id":       zs.zone_id,
                    "vehicle_count": zs.vehicle_count,
                    "avg_speed":     zs.avg_speed,
                    "event":         zs.dominant_event,
                    "density":       zs.vehicle_count,
                }

                publish_zone_state(mqtt, zs_dict)     # Phase 3
                classify(zs_dict)                      # Phase 4
                twin.update_zone(zs.zone_id, zs_dict) # Phase 5

                # Phase 6 — AI prediction (TODO: wire in GRU)
                # Phase 7 — event propagation (TODO)

            # Signal phase broadcast
            for tl_id in get_all_traffic_light_ids():
                tl_state = get_traffic_light_state(tl_id)
                publish_signal_phase(mqtt, tl_id, tl_state)

            sim_step += 1

    finally:
        reset_edge_colors(all_edges)   # restore road colours on exit
        stop()
        mqtt_disconnect(mqtt)


if __name__ == "__main__":
    run()
