# v2_main.py — GreenSync V2 Integration Orchestrator
#
# New data flow (per simulation step):
#
#   [TomTom API]  ──(60s poll)──┐
#   [MQTT Intents] ─────────────┼──▶ HybridDigitalTwin ──▶ A* Eco-routing
#   [SUMO TraCI]  ──(per step)──┘         │
#                                          ▼
#                               ShadowVehicleInjector
#                               (mirror intents → SUMO)
#
# Environment variables:
#   TOMTOM_API_KEY        — TomTom Traffic API key (mock mode if unset)
#   MQTT_BROKER_HOST      — default "localhost"
#   MQTT_BROKER_PORT      — default 1883
#   SUMO_NET_PATH         — path to .net.xml (default: greensync_phase1/map.net.xml)
#   GREENSYNC_HEADLESS    — 1 = no SUMO GUI (default 0)

import os
import time
import logging

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

from backend.tomtom_poller       import TomTomPoller
from backend.intent_aggregator   import RouteIntentStore, IntentAggregator
from backend.hybrid_twin         import HybridDigitalTwin
from backend.shadow_vehicle_injector import ShadowVehicleInjector

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
logger = logging.getLogger("v2_main")

# ── Config ────────────────────────────────────────────────────────────────────
HEADLESS       = os.environ.get("GREENSYNC_HEADLESS", "0") == "1"
MAX_STEPS      = None
STEP_DELAY     = 0.05
PRINT_INTERVAL = 10
BROKER_HOST    = os.environ.get("MQTT_BROKER_HOST", "localhost")
BROKER_PORT    = int(os.environ.get("MQTT_BROKER_PORT", "1883"))
NET_PATH       = os.environ.get("SUMO_NET_PATH", "greensync_phase1/map.net.xml")

_RANK = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}
_W    = 88


def build_zones() -> tuple[list[Zone], set[str]]:
    import traci as _t
    valid_edges = set(_t.edge.getIDList())
    logger.info("Building RSU zones...")
    zone_defs = build_rsu_zones(verbose=False)
    zones: list[Zone] = []
    for zd in zone_defs:
        z = build_zone_from_def(zd, valid_edges=valid_edges)
        zones.append(z)
    assign_radii(zones)
    all_edges: set[str] = set()
    for z in zones:
        all_edges.update(z.edge_ids)
    logger.info("%d zones | %d unique edges", len(zones), len(all_edges))
    return zones, all_edges


def _enrich_vehicles(vehicles, edge_states):
    for v in vehicles:
        es = edge_states.get(v["edge_id"])
        if es:
            v["congestion_level"]   = es.event
            v["road_speed_kmh"]     = es.speed_kmh
            v["road_vehicle_count"] = es.vehicle_count
        else:
            v["congestion_level"]   = "unknown"
            v["road_speed_kmh"]     = 0.0
            v["road_vehicle_count"] = 0
    return vehicles


def _print_v2_dashboard(step_n: int, twin: HybridDigitalTwin,
                        shadow_count: int, vehicles: list[dict]):
    diag = twin.diagnostics()
    tomtom_tag = (f"TomTom {diag['tomtom_age_seconds']}s ago"
                  if diag["tomtom_age_seconds"] is not None
                  else "TomTom: MOCK")
    if diag.get("tomtom_stale"):
        tomtom_tag += " ⚠️ STALE"

    print(f"\n{'━' * _W}")
    print(f"  GreenSync V2 │ Step {step_n:>5} │ 🚗 SUMO: {len(vehicles):>3} │ "
          f"👥 Shadows: {shadow_count} │ {tomtom_tag}")
    print(f"  Intents: {diag.get('active_intents', 0)} active │ "
          f"Routes: {diag.get('route_counts', {})} │ "
          f"Telemetry users: {diag.get('active_users_with_telemetry', 0)}")
    print(f"{'━' * _W}", flush=True)


def run():
    # ── V2 backend services ───────────────────────────────────────────────────
    tomtom  = TomTomPoller()
    tomtom.start()

    store       = RouteIntentStore()
    aggregator  = IntentAggregator(store, broker_host=BROKER_HOST, broker_port=BROKER_PORT)

    # Connect MQTT for intent aggregation before SUMO starts
    try:
        aggregator.start()
    except Exception as exc:
        logger.warning("IntentAggregator MQTT connect failed (will retry): %s", exc)

    # ── SUMO startup ──────────────────────────────────────────────────────────
    start(HEADLESS)
    zones, all_edges = build_zones()
    setup_edges(all_edges)

    # ── Hybrid twin (replaces DigitalTwin) ────────────────────────────────────
    twin = HybridDigitalTwin(tomtom_poller=tomtom, intent_store=store)

    # ── Shadow vehicle injector ───────────────────────────────────────────────
    shadow_injector = ShadowVehicleInjector(
        net_path=NET_PATH,
        intent_store=store,
    )
    shadow_injector.ensure_vehicle_type()

    # ── Publisher MQTT (zone state + signals) ─────────────────────────────────
    mqtt = mqtt_connect(host=BROKER_HOST, port=BROKER_PORT)

    sim_step = 0
    try:
        while MAX_STEPS is None or sim_step < MAX_STEPS:

            # Phase 1: advance SUMO
            vehicles = step()

            # Phase 2a: RSU edge sensing
            edge_states = sense_edges_subscribed()
            vehicles    = _enrich_vehicles(vehicles, edge_states)
            if not HEADLESS:
                color_edges(edge_states)

            # Phase 2b: Zone aggregation
            zone_states = sense_all_zones(zones, edge_states)

            # Phase 3–5: MQTT + classifier + hybrid twin update
            for zs in zone_states:
                active_es = [s for s in zs.edge_states.values() if s.vehicle_count > 0]
                worst_es  = max(active_es,
                                key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
                                default=None)
                zs_dict = {
                    "zone_id":              zs.zone_id,
                    "vehicle_count":        zs.vehicle_count,
                    "avg_speed":            zs.avg_speed,
                    "event":                zs.dominant_event,
                    "density":              zs.vehicle_count,
                    "worst_road":           worst_es.edge_id if worst_es else "",
                    "worst_road_speed_kmh": worst_es.speed_kmh if worst_es else 0.0,
                }
                publish_zone_state(mqtt, zs_dict)
                classify(zs_dict)
                twin.update_zone(zs.zone_id, zs_dict)

            for tl_id in get_all_traffic_light_ids():
                publish_signal_phase(mqtt, tl_id, get_traffic_light_state(tl_id))

            # Phase C: inject/update shadow vehicles from real-world intents
            shadow_injector.step()

            if sim_step % PRINT_INTERVAL == 0:
                _print_v2_dashboard(sim_step, twin,
                                    shadow_injector.active_count(), vehicles)

            if not HEADLESS:
                time.sleep(STEP_DELAY)

            sim_step += 1

    finally:
        reset_edge_colors(all_edges)
        stop()
        mqtt_disconnect(mqtt)
        aggregator.stop()
        tomtom.stop()
        logger.info("GreenSync V2 shutdown complete.")


if __name__ == "__main__":
    run()
