# main.py — GreenSync full-system integration
#
# Data flow (per simulation step)
# ────────────────────────────────────────────────────────────────────────────
#  Phase 1  simulation.step()
#               → advance SUMO by 1 step, collect raw vehicle list
#               → enrich each vehicle with real-time road congestion level
#
#  Phase 2a sense_edges_subscribed()
#               → batch-read ALL zone edges from TraCI in ONE round-trip
#                 (SUMO virtual loop-detector metrics used as RSU readings)
#               → color_edges() — diff-only Google Maps lane painting in GUI
#
#  Phase 2b sense_all_zones()
#               → aggregate edge states up to zone level
#               → 35 MECE zones — complete network coverage, no gaps/overlaps
#
#  Phase 3  MQTT publish (zone state + signal phases)
#  Phase 4  Event classifier
#  Phase 5  Digital twin update
#  Phase 6  GRU prediction   [TODO]
#  Phase 7  Event propagation [TODO]
#  Phase 8  Eco-routing       [TODO]
#  Phase 9  Flutter / mobile  [TODO]

import time
import os

from simulation.traci_interface  import (start, step, get_all_traffic_light_ids,
                                          get_traffic_light_state, stop)
from rsu.zone_builder            import build_mece_zones
from rsu.rsu_manager             import (build_zone_from_def, assign_radii,
                                          sense_all_zones, Zone)
from rsu.edge_detector           import (setup_edges, sense_edges_subscribed,
                                          color_edges, reset_edge_colors)
from communication.publisher     import (connect as mqtt_connect, publish_zone_state,
                                          publish_signal_phase, disconnect as mqtt_disconnect)
from event_classifier.classifier import classify
from digital_twin.twin           import DigitalTwin

# ── Simulation control ────────────────────────────────────────────────────────
HEADLESS      = False    # False = GUI via ./run.sh
MAX_STEPS     = None     # None = run indefinitely
STEP_DELAY    = 0.05     # seconds between steps (GUI pacing)
PRINT_INTERVAL = 10      # terminal refresh every N steps

# ── Terminal display limits ───────────────────────────────────────────────────
MAX_VEH_ROWS  = 15       # max vehicle rows shown per refresh
MAX_ROAD_ROWS = 10       # top-N congested roads shown
MAX_ZONE_ROWS = 35       # all zones (one per TL) — full MECE coverage

# ── Event display ─────────────────────────────────────────────────────────────
_ICON = {
    "free_flow":  "🟢",
    "slowdown":   "🟡",
    "congestion": "🔴",
    "unknown":    "⚪",
}
_EVENT_RANK = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}


# ── Zone build ────────────────────────────────────────────────────────────────

def build_zones() -> tuple[list[Zone], set[str]]:
    """
    Auto-build MECE RSU zones and convert them to Zone objects.
    Returns (zones, all_edges) where all_edges is the union of every zone's edges.
    Must be called AFTER traci.start().
    """
    import traci as _traci
    valid_edges = set(_traci.edge.getIDList())

    print("\n📡 Building MECE RSU zones (Voronoi / TL-seeded)...")
    zone_defs = build_mece_zones(verbose=True)

    zones: list[Zone] = []
    for zd in zone_defs:
        z = build_zone_from_def(zd, valid_edges=valid_edges)
        zones.append(z)

    # Compute non-overlapping radii and draw zone outline circles in SUMO GUI
    assign_radii(zones)

    all_edges: set[str] = set()
    for z in zones:
        all_edges.update(z.edge_ids)

    print(f"📡 {len(zones)} zones ready | {len(all_edges)} unique edges monitored\n")
    return zones, all_edges


# ── Vehicle enrichment ────────────────────────────────────────────────────────

def _enrich_vehicles(vehicles: list[dict], edge_states: dict) -> list[dict]:
    """
    Attach real-time road state to every vehicle dict so downstream systems
    receive complete, synchronized per-vehicle data:
        congestion_level  — event label of the road the vehicle is currently on
        road_speed_kmh    — current mean speed (km/h) on that road
        road_occupancy    — occupancy % on that road
    """
    for v in vehicles:
        es = edge_states.get(v["edge_id"])
        if es:
            v["congestion_level"] = es.event
            v["road_speed_kmh"]   = es.speed_kmh
            v["road_occupancy"]   = es.occupancy
        else:
            v["congestion_level"] = "unknown"
            v["road_speed_kmh"]   = 0.0
            v["road_occupancy"]   = 0.0
    return vehicles


# ── Terminal display ──────────────────────────────────────────────────────────

def _print_dashboard(sim_step: int, sim_time: float,
                     vehicles: list[dict],
                     edge_states: dict,
                     zone_states: list):
    """
    Three-panel real-time dashboard printed to terminal.

    Panel 1 — VEHICLES     : per-vehicle position, speed, edge, road congestion
    Panel 2 — ROADS        : top congested edges ranked by occupancy
    Panel 3 — RSU ZONES    : all MECE zones with aggregate metrics
    """
    W = 78   # terminal width

    # ── Header ────────────────────────────────────────────────────────────────
    print(f"\n{'━' * W}")
    print(f"  GreenSync RSU Monitor  │  Step {sim_step:>5}  │  "
          f"t={sim_time:>7.1f}s  │  🚗 {len(vehicles)} vehicles  │  "
          f"Zones: {len(zone_states)}")
    print(f"{'━' * W}")

    # ── Panel 1: Vehicles ─────────────────────────────────────────────────────
    # Sort worst congestion first so the most interesting rows appear at top
    sorted_veh = sorted(
        vehicles,
        key=lambda v: _EVENT_RANK.get(v.get("congestion_level", "unknown"), 0),
        reverse=True,
    )[:MAX_VEH_ROWS]

    print(f"\n  ▸ VEHICLES  ({min(len(vehicles), MAX_VEH_ROWS)} of {len(vehicles)} shown"
          f" — worst congestion first)")
    vfmt = "  {:<10} {:>6} {:>11} {:>11}  {:<22}  {}"
    print(vfmt.format("ID", "km/h", "X", "Y", "Edge", "Road Congestion"))
    print("  " + "─" * (W - 2))
    for v in sorted_veh:
        spd  = round(v["speed"] * 3.6, 1)
        x, y = round(v["position"][0], 1), round(v["position"][1], 1)
        lvl  = v.get("congestion_level", "unknown")
        icon = _ICON.get(lvl, "⚪")
        print(vfmt.format(
            str(v["id"])[:10],
            f"{spd:.1f}",
            f"{x:.1f}",
            f"{y:.1f}",
            str(v["edge_id"])[:22],
            f"{icon} {lvl}",
        ))

    # ── Panel 2: Most congested roads ─────────────────────────────────────────
    active_edges = [s for s in edge_states.values() if s.vehicle_count > 0]
    # Rank by: event severity first, then occupancy
    ranked_edges = sorted(
        active_edges,
        key=lambda s: (_EVENT_RANK.get(s.event, 0), s.occupancy),
        reverse=True,
    )[:MAX_ROAD_ROWS]

    print(f"\n  ▸ ROAD SEGMENTS  (top {MAX_ROAD_ROWS} by congestion severity"
          f"  |  active roads: {len(active_edges)})")
    rfmt = "  {:<24} {:>7} {:>7} {:>6}  {}"
    print(rfmt.format("Edge", "km/h", "Occ %", "Halt", "Status"))
    print("  " + "─" * (W - 2))
    for s in ranked_edges:
        icon = _ICON.get(s.event, "⚪")
        print(rfmt.format(
            str(s.edge_id)[:24],
            f"{s.speed_kmh:.1f}",
            f"{s.occupancy:.1f}",
            str(s.halting_count),
            f"{icon} {s.event}",
        ))
    if not ranked_edges:
        print("  (no vehicles on monitored roads yet)")

    # ── Panel 3: RSU zone summary ─────────────────────────────────────────────
    # Sort zones: congested first, then by vehicle count descending
    sorted_zones = sorted(
        zone_states,
        key=lambda z: (_EVENT_RANK.get(z.dominant_event, 0), z.vehicle_count),
        reverse=True,
    )

    # Compute zone occupancy = mean of active-edge occupancies
    def _zone_occ(zs) -> float:
        active = [s for s in zs.edge_states.values() if s.vehicle_count > 0]
        return round(sum(s.occupancy for s in active) / len(active), 1) if active else 0.0

    print(f"\n  ▸ RSU ZONE SUMMARY  ({len(zone_states)} MECE zones — full network coverage)")
    zfmt = "  {:<10} {:>6} {:>6} {:>7} {:>7}  {}"
    print(zfmt.format("Zone", "Edges", "Vehs", "km/h", "Occ %", "Dominant Event"))
    print("  " + "─" * (W - 2))
    for zs in sorted_zones:
        icon   = _ICON.get(zs.dominant_event, "⚪")
        spd_kh = round(zs.avg_speed * 3.6, 1)
        occ    = _zone_occ(zs)
        n_edges = len(zs.edge_states)
        print(zfmt.format(
            zs.zone_id,
            str(n_edges),
            str(zs.vehicle_count),
            f"{spd_kh:.1f}",
            f"{occ:.1f}",
            f"{icon} {zs.dominant_event}",
        ))

    print(f"\n{'━' * W}", flush=True)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    start(HEADLESS)

    if not HEADLESS:
        print("\n" + "━" * 68)
        print("  GreenSync — SUMO GUI mode")
        print("  ⚠️  Do NOT click Play ▶ in the SUMO GUI window.")
        print("  Python drives every step via TraCI.")
        print("  Roads: smooth red→orange→yellow→green (Google Maps style)")
        print("  Zone outlines: thin blue circles (35 MECE, non-overlapping)")
        print("━" * 68 + "\n")

    zones, all_edges = build_zones()

    # One-time setup: cache geometry, subscribe to batch metrics, paint roads
    print("🎨 Setting up edge sensing (subscriptions + colour cache)...")
    setup_edges(all_edges)
    print()

    mqtt = mqtt_connect()
    twin = DigitalTwin()

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # ── Phase 1: advance sim, collect raw vehicle list ─────────────────
            vehicles = step()

            # ── Phase 2a: batch-read all zone edges in ONE TraCI round-trip ────
            # SUMO's internal loop-detector values (speed, occupancy, halting)
            # are used directly as RSU infrastructure sensor readings.
            edge_states = sense_edges_subscribed()

            # Enrich each vehicle with the real-time state of its current road
            vehicles = _enrich_vehicles(vehicles, edge_states)

            # Paint roads Google Maps-style (diff-only — only changed lanes)
            if not HEADLESS:
                color_edges(edge_states)

            # ── Phase 2b: aggregate edge states → zone states ─────────────────
            zone_states = sense_all_zones(zones, edge_states)

            # ── Terminal dashboard ─────────────────────────────────────────────
            if sim_step % PRINT_INTERVAL == 0:
                import traci as _t
                sim_time = _t.simulation.getTime()
                _print_dashboard(sim_step, sim_time, vehicles, edge_states, zone_states)

            # GUI pacing
            if not HEADLESS:
                time.sleep(STEP_DELAY)

            # ── Phase 3–5: MQTT, classifier, digital twin ──────────────────────
            for zs in zone_states:
                zs_dict = {
                    "zone_id":       zs.zone_id,
                    "vehicle_count": zs.vehicle_count,
                    "avg_speed":     zs.avg_speed,
                    "event":         zs.dominant_event,
                    "density":       zs.vehicle_count,
                }
                publish_zone_state(mqtt, zs_dict)
                classify(zs_dict)
                twin.update_zone(zs.zone_id, zs_dict)

            for tl_id in get_all_traffic_light_ids():
                publish_signal_phase(mqtt, tl_id, get_traffic_light_state(tl_id))

            sim_step += 1

    finally:
        reset_edge_colors(all_edges)
        stop()
        mqtt_disconnect(mqtt)


if __name__ == "__main__":
    run()
