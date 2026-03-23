# main.py — GreenSync full-system integration
#
# Data flow (per simulation step)
# ────────────────────────────────────────────────────────────────────────────
#  Phase 1   simulation.step()
#                → advance SUMO one step, collect raw vehicle list
#                → enrich each vehicle: congestion_level, road_speed_kmh,
#                  road_vehicle_count of its current edge
#
#  Phase 2a  sense_edges_subscribed()
#                → batch-read ALL zone edges in ONE TraCI round-trip
#                  (SUMO loop-detector metrics as RSU infrastructure readings)
#                → color_edges() — diff-only Google Maps lane overlay
#
#  Phase 2b  sense_all_zones()
#                → aggregate edge states → zone-level summaries
#                → radius-based zones, boundary edges shared between zones
#
#  Phase 3   MQTT publish (zone state + signal phases)
#  Phase 4   Event classifier
#  Phase 5   Digital twin update
#  Phase 6   GRU prediction   [TODO]
#  Phase 7   Event propagation [TODO]
#  Phase 8   Eco-routing       [TODO]
#  Phase 9   Flutter / mobile  [TODO]

import time

from simulation.traci_interface  import (start, step, get_all_traffic_light_ids,
                                          get_traffic_light_state, stop)
from rsu.zone_builder            import build_rsu_zones
from rsu.rsu_manager             import (build_zone_from_def, assign_radii,
                                          sense_all_zones, Zone)
from rsu.edge_detector           import (setup_edges, sense_edges_subscribed,
                                          color_edges, reset_edge_colors)
from communication.publisher     import (connect as mqtt_connect, publish_zone_state,
                                          publish_signal_phase, disconnect as mqtt_disconnect)
from event_classifier.classifier import classify
from digital_twin.twin           import DigitalTwin

# ── Simulation control ────────────────────────────────────────────────────────
HEADLESS       = False   # False = SUMO GUI via ./run.sh
MAX_STEPS      = None    # None = run indefinitely
STEP_DELAY     = 0.05    # seconds between steps (GUI pacing)
PRINT_INTERVAL = 10      # terminal refresh every N steps

# ── Dashboard display limits ──────────────────────────────────────────────────
DASH_TOP_ZONES  = 6    # zones to show (most congested first)
DASH_TOP_ROADS  = 4    # roads per zone (most congested first)
DASH_TOP_VEHS   = 3    # vehicles per road (highest wait-time first)

# ── Event icons and ranking ───────────────────────────────────────────────────
_ICON = {
    "free_flow":  "🟢",
    "slowdown":   "🟡",
    "congestion": "🔴",
    "unknown":    "⚪",
}
_RANK = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}
_W    = 84   # terminal width


# ── Zone construction ─────────────────────────────────────────────────────────

def build_zones() -> tuple[list[Zone], set[str]]:
    """
    Auto-build radius-based RSU zones and convert them to Zone objects.
    Returns (zones, all_edges).  Must be called AFTER traci.start().
    """
    import traci as _t
    valid_edges = set(_t.edge.getIDList())

    print("\n📡 Building RSU zones (radius-based, minimal-overlap)...")
    zone_defs = build_rsu_zones(verbose=True)

    zones: list[Zone] = []
    for zd in zone_defs:
        z = build_zone_from_def(zd, valid_edges=valid_edges)
        zones.append(z)

    assign_radii(zones)   # draw non-overlapping outline circles in SUMO GUI

    all_edges: set[str] = set()
    for z in zones:
        all_edges.update(z.edge_ids)

    print(f"📡 {len(zones)} zones active | "
          f"{len(all_edges)} unique edges monitored\n")
    return zones, all_edges


# ── Vehicle enrichment ────────────────────────────────────────────────────────

def _enrich_vehicles(vehicles: list[dict],
                     edge_states: dict) -> list[dict]:
    """
    Attach real-time road metrics to every vehicle dict:
        congestion_level     — event label of the vehicle's current road
        road_speed_kmh       — mean speed (km/h) on that road right now
        road_vehicle_count   — number of vehicles currently on that road
        road_occupancy       — lane occupancy % on that road
    """
    for v in vehicles:
        es = edge_states.get(v["edge_id"])
        if es:
            v["congestion_level"]   = es.event
            v["road_speed_kmh"]     = es.speed_kmh
            v["road_vehicle_count"] = es.vehicle_count
            v["road_occupancy"]     = es.occupancy
        else:
            v["congestion_level"]   = "unknown"
            v["road_speed_kmh"]     = 0.0
            v["road_vehicle_count"] = 0
            v["road_occupancy"]     = 0.0
    return vehicles


# ── Hierarchical terminal dashboard ──────────────────────────────────────────

def _print_dashboard(sim_step: int, sim_time: float,
                     vehicles:    list[dict],
                     edge_states: dict,
                     zone_states: list):
    """
    Hierarchical real-time dashboard:

        ▸ SUMMARY header — step, time, vehicle count, network-wide event counts

        ▸ RSU ZONES (top DASH_TOP_ZONES by congestion)
            Each zone shows: road count, vehicle count, avg speed, dominant event
            ├─ ROAD entries (top DASH_TOP_ROADS per zone)
            │    Each road shows: vehicle count, avg speed km/h, occupancy,
            │                     halting count, event label
            │    └─ VEHICLE entries (top DASH_TOP_VEHS per road)
            │         Each vehicle: ID, speed km/h, position (x, y),
            │                       congestion level, road avg speed
            :

        ▸ NETWORK ROADS — top congested roads across all zones
    """
    # Build edge → [vehicles] mapping once (O(V))
    edge_veh: dict[str, list[dict]] = {}
    for v in vehicles:
        eid = v["edge_id"]
        if not eid.startswith(":"):
            edge_veh.setdefault(eid, []).append(v)

    # ── HEADER ────────────────────────────────────────────────────────────────
    active_edges = [s for s in edge_states.values() if s.vehicle_count > 0]
    n_cong = sum(1 for s in active_edges if s.event == "congestion")
    n_slow = sum(1 for s in active_edges if s.event == "slowdown")
    n_free = sum(1 for s in active_edges if s.event == "free_flow")

    print(f"\n{'━' * _W}")
    print(f"  GreenSync RSU Monitor │ Step {sim_step:>5} │ "
          f"t={sim_time:>7.1f}s │ 🚗 {len(vehicles):>3} vehicles │ "
          f"Roads: 🔴{n_cong} 🟡{n_slow} 🟢{n_free}")
    print(f"{'━' * _W}")

    # ── ZONE → ROAD → VEHICLE TREE ────────────────────────────────────────────
    # Show only zones that have active traffic, sorted by severity then count
    active_zones = [
        zs for zs in zone_states
        if zs.vehicle_count > 0 or zs.dominant_event != "unknown"
    ]
    sorted_zones = sorted(
        active_zones,
        key=lambda z: (_RANK.get(z.dominant_event, 0), z.vehicle_count),
        reverse=True,
    )[:DASH_TOP_ZONES]

    if not sorted_zones:
        print("\n  ⏳  Waiting for vehicles to enter the network …\n")
    else:
        print(f"\n  ▸ RSU ZONES  "
              f"(showing {len(sorted_zones)} of {len(zone_states)} — "
              f"most congested first)\n")

    for zs in sorted_zones:
        z_icon  = _ICON.get(zs.dominant_event, "⚪")
        z_spd   = round(zs.avg_speed * 3.6, 1)
        z_edges = len(zs.edge_states)

        # Zone header line
        print(f"  {z_icon} {zs.zone_id:<10}  "
              f"{z_edges:>3} roads │ {zs.vehicle_count:>3} vehs │ "
              f"{z_spd:>6.1f} km/h │ {zs.dominant_event.upper()}")

        # Roads inside this zone that have vehicles, worst first
        active_road_states = sorted(
            [s for s in zs.edge_states.values() if s.vehicle_count > 0],
            key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
            reverse=True,
        )[:DASH_TOP_ROADS]

        for s in active_road_states:
            r_icon = _ICON.get(s.event, "⚪")
            # Is this a boundary edge (may appear in another zone too)?
            r_fmt  = "  │  {icon} {eid:<26} {cnt:>2} vehs │ {spd:>6.1f} km/h │ " \
                     "occ {occ:>5.1f}% │ halt {halt:>2} │ {ev}"
            print(r_fmt.format(
                icon = r_icon,
                eid  = str(s.edge_id)[:26],
                cnt  = s.vehicle_count,
                spd  = s.speed_kmh,
                occ  = s.occupancy,
                halt = s.halting_count,
                ev   = s.event,
            ))

            # Vehicles on this road — show highest-wait-time first
            road_vehs = sorted(
                edge_veh.get(s.edge_id, []),
                key=lambda v: v.get("waiting_time", 0),
                reverse=True,
            )[:DASH_TOP_VEHS]

            for v in road_vehs:
                vspd  = round(v["speed"] * 3.6, 1)
                x     = round(v["position"][0], 0)
                y     = round(v["position"][1], 0)
                v_lvl = v.get("congestion_level", "unknown")
                rspd  = v.get("road_speed_kmh", 0.0)
                rcnt  = v.get("road_vehicle_count", 0)
                wait  = round(v.get("waiting_time", 0), 0)
                print(f"  │  │  └ {str(v['id']):<10}  "
                      f"{vspd:>6.1f} km/h  "
                      f"({x:>8.0f}, {y:>8.0f})  "
                      f"wait {wait:>5.0f}s  "
                      f"road: {rspd:.1f} km/h / {rcnt} vehs")

        if z_edges > DASH_TOP_ROADS:
            remaining_roads = z_edges - len(active_road_states)
            if remaining_roads > 0:
                print(f"  │     … +{remaining_roads} more roads in zone (no active traffic)")
        print("  │")

    # ── NETWORK-WIDE ROAD SUMMARY ─────────────────────────────────────────────
    ranked_roads = sorted(
        active_edges,
        key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
        reverse=True,
    )[:8]

    print(f"\n  ▸ NETWORK — top congested roads across all zones")
    hdr = "  {:<28} {:>7} {:>7} {:>5}  {}"
    print(hdr.format("Edge", "km/h", "Occ %", "Halt", "Event"))
    print("  " + "─" * (_W - 2))
    for s in ranked_roads:
        icon = _ICON.get(s.event, "⚪")
        print(hdr.format(
            str(s.edge_id)[:28],
            f"{s.speed_kmh:.1f}",
            f"{s.occupancy:.1f}",
            str(s.halting_count),
            f"{icon} {s.event}",
        ))
    if not ranked_roads:
        print("  (no vehicles on monitored roads yet)")

    print(f"\n{'━' * _W}", flush=True)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run():
    start(HEADLESS)

    if not HEADLESS:
        print("\n" + "━" * 68)
        print("  GreenSync — SUMO GUI mode")
        print("  ⚠️  Do NOT click Play ▶ in the GUI window.")
        print("  Python drives every step via TraCI.")
        print("  Roads: smooth red→orange→yellow→green (Google Maps style)")
        print("  Zones: minimal-overlap RADAR circles, boundary sharing allowed")
        print("━" * 68 + "\n")

    zones, all_edges = build_zones()

    print("🎨 Setting up edge sensing (subscriptions + colour cache)...")
    setup_edges(all_edges)
    print()

    mqtt = mqtt_connect()
    twin = DigitalTwin()

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # ── Phase 1: advance sim, collect vehicle list ─────────────────────
            vehicles = step()

            # ── Phase 2a: batch-read ALL zone edges (ONE TraCI round-trip) ─────
            edge_states = sense_edges_subscribed()

            # Enrich every vehicle with real-time road state
            vehicles = _enrich_vehicles(vehicles, edge_states)

            # Paint roads Google Maps-style (diff-only — minimal TraCI writes)
            if not HEADLESS:
                color_edges(edge_states)

            # ── Phase 2b: aggregate edges → zone states ────────────────────────
            zone_states = sense_all_zones(zones, edge_states)

            # ── Hierarchical terminal dashboard ────────────────────────────────
            if sim_step % PRINT_INTERVAL == 0:
                import traci as _t
                sim_time = _t.simulation.getTime()
                _print_dashboard(sim_step, sim_time, vehicles,
                                 edge_states, zone_states)

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
