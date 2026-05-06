from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Optional

import traci

from .traffic_manager import TrafficManager
from .predictive_model import PredictiveModel
from .prediction_buffer import PredictionBuffer
from .modified_astar import ModifiedAStar, VEHICLE_PROFILES
from rsu.zone_builder import build_rsu_zones
from rsu.rsu_manager import build_zone_from_def, assign_radii, Zone, sense_all_zones
from simulation.traci_interface import (
    start as sumo_start, stop as sumo_stop, step as sumo_step,
    get_all_traffic_light_ids, get_traffic_light_state,
)
from rsu.edge_detector import sense_edges_subscribed, color_edges, setup_edges, reset_edge_colors, _max_speed
from communication.publisher import (
    connect as mqtt_connect, publish_zone_state,
    publish_signal_phase, disconnect as mqtt_disconnect,
)
from event_classifier.classifier import classify
from digital_twin.twin import DigitalTwin

# ── Terminal dashboard constants (mirrors main.py) ────────────────────────────
_ICON  = {"free_flow": "🟢", "slowdown": "🟡", "congestion": "🔴", "unknown": "⚪"}
_RANK  = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}
_W     = 84
PRINT_INTERVAL  = 10   # terminal refresh every N steps
DASH_TOP_ZONES  = 6
DASH_TOP_ROADS  = 4
DASH_TOP_VEHS   = 3


@dataclass
class RouteInfo:
    vehicle_id:        str
    origin_edge:       str
    dest_edge:         str
    vehicle_type:      str
    predictive_route:  list[str] = field(default_factory=list)
    static_route:      list[str] = field(default_factory=list)
    predictive_metrics: dict      = field(default_factory=dict)
    static_metrics:     dict      = field(default_factory=dict)
    computed_at_step:  int = 0
    # Comparative savings (positive = predictive is better)
    time_saved_s:      float = 0.0
    emit_saved_pct:    float = 0.0


# ── Thread-safe shared state ─────────────────────────────────────────────────

class SimState:
    """
    All mutable state shared between the SUMO background thread and the
    Streamlit dashboard.  Access is serialised by _lock.
    Never hold the lock while doing I/O or blocking work.
    """

    def __init__(self):
        self._lock             = threading.RLock()
        self.sim_step:   int   = 0
        self.sim_time:   float = 0.0
        self.vehicles:   list  = []
        self.edge_states: dict = {}
        self.zone_states: list = []
        self.active_routes: dict[str, RouteInfo] = {}
        self.training_loss: Optional[float] = None
        self.n_samples:  int   = 0
        self.lsh_size:   int   = 0
        self.train_steps: int  = 0
        self.running:    bool  = False
        self.error:      Optional[str] = None

    def update(self, **kwargs):
        with self._lock:
            for k, v in kwargs.items():
                setattr(self, k, v)

    def set_route(self, ri: RouteInfo):
        with self._lock:
            self.active_routes[ri.vehicle_id] = ri

    def snapshot(self) -> dict:
        """Return a deep-enough copy for dashboard consumption without holding lock."""
        with self._lock:
            return {
                "sim_step":      self.sim_step,
                "sim_time":      self.sim_time,
                "vehicles":      list(self.vehicles),
                "edge_states":   dict(self.edge_states),
                "zone_states":   list(self.zone_states),
                "active_routes": dict(self.active_routes),
                "training_loss": self.training_loss,
                "n_samples":     self.n_samples,
                "lsh_size":      self.lsh_size,
                "train_steps":   self.train_steps,
                "running":       self.running,
                "error":         self.error,
            }


# ── SimController ─────────────────────────────────────────────────────────────

class SimController:
    """
    Manages the full GreenSync simulation pipeline:

        start()           → launches SUMO + all phase modules in background thread
        request_route()   → queues a routing request (called from dashboard)
        stop()            → signals graceful shutdown
        state.snapshot()  → dashboard reads live data

    The background thread owns all TraCI calls; the dashboard never touches TraCI.
    """

    def __init__(
        self,
        headless:       bool = True,
        max_steps:      Optional[int] = None,
        step_delay:     float = 0.0,      # extra sleep per step (GUI pacing)
        enable_logging: bool = True,      # MQTT + classifier + digital twin + terminal dashboard
    ):
        self.headless       = headless
        self.max_steps      = max_steps
        self.step_delay     = step_delay
        self.enable_logging = enable_logging

        self.state  = SimState()
        self._q:    queue.Queue = queue.Queue()
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None

        # Core pipeline modules (created here, used only in background thread)
        self.traffic_manager = TrafficManager()
        self.predictive_model = PredictiveModel()
        self.prediction_buffer: Optional[PredictionBuffer] = None
        self.astar = ModifiedAStar()

        # Logging pipeline (MQTT, twin) — initialised in _setup if enable_logging
        self._mqtt = None
        self._twin: Optional[DigitalTwin] = None

        # Populated after SUMO starts
        self._zones:     list[Zone] = []
        self._all_edges: set[str]   = set()

    # ── Public control API ────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="GreenSyncSim"
        )
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def request_route(
        self,
        vehicle_id:   str,
        dest_edge:    str,
        vehicle_type: str = "default",
    ):
        """Queue a routing request to be processed by the SUMO thread."""
        self._q.put({
            "vehicle_id":   vehicle_id,
            "dest_edge":    dest_edge,
            "vehicle_type": vehicle_type,
        })

    # ── Background thread ─────────────────────────────────────────────────────

    def _run(self):
        try:
            self._setup()
            self._loop()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            self.state.update(error=str(exc))
        finally:
            self._teardown()

    def _setup(self):
        self.state.update(running=True, error=None)

        sumo_start(self.headless)

        # Load A* network (sumolib, not TraCI — safe to call any time after start)
        self.astar.load_network()

        # Try to restore pretrained weights
        self.predictive_model.load()
        # Seed SimState immediately so the dashboard shows loaded values
        # before the first loop iteration completes.
        self.state.update(
            train_steps   = self.predictive_model.train_steps,
            training_loss = self.predictive_model.last_loss,
        )

        # Build RSU zones (used for zone sensing / visualisation only)
        valid_edges = set(traci.edge.getIDList())
        zone_defs   = build_rsu_zones(verbose=True)

        self._zones = []
        for zd in zone_defs:
            z = build_zone_from_def(zd, valid_edges=valid_edges)
            self._zones.append(z)
        assign_radii(self._zones)

        # Use ALL map edges (full A* graph) for GRU+LSH — not just RSU zones.
        # Intersect with valid TraCI edge list to avoid subscribing phantom edges.
        self._all_edges = set(self.astar.get_all_edge_ids()) & valid_edges

        setup_edges(self._all_edges)

        # Speed map: A* sumolib values as baseline, TraCI-measured values override.
        astar_speeds = {
            eid: self.astar._edge_speed[eid]
            for eid in self._all_edges
            if eid in self.astar._edge_speed
        }
        combined_speeds = {**astar_speeds, **dict(_max_speed)}

        # Give TrafficManager the posted speed limits from edge_detector's cache
        self.traffic_manager.register_edges(
            self._all_edges,
            max_speeds=combined_speeds,
        )

        self.prediction_buffer = PredictionBuffer(
            self.traffic_manager, self.predictive_model
        )

        # Logging pipeline
        if self.enable_logging:
            self._twin = DigitalTwin()
            try:
                self._mqtt = mqtt_connect()
                print("[SimController] MQTT connected.")
            except Exception as e:
                print(f"[SimController] MQTT unavailable ({e}) — logging to terminal only.")
                self._mqtt = None

    def _loop(self):
        sim_step = 0
        import time

        while not self._stop.is_set():
            if self.max_steps and sim_step >= self.max_steps:
                break

            # ── Phase 1: advance SUMO ─────────────────────────────────────────
            vehicles    = sumo_step()
            edge_states = sense_edges_subscribed()

            if not self.headless:
                color_edges(edge_states)

            zone_states = sense_all_zones(self._zones, edge_states)
            sim_time    = traci.simulation.getTime()

            # ── Phase 6: update prediction pipeline ──────────────────────────
            self.traffic_manager.update(edge_states, vehicles)
            self.prediction_buffer.update(sim_step, list(self._all_edges))

            # ── Phase 8: process queued routing requests ──────────────────────
            while not self._q.empty():
                try:
                    self._handle_route_request(self._q.get_nowait(), sim_step)
                except queue.Empty:
                    break

            # ── Apply active routes to SUMO vehicles ──────────────────────────
            live_ids = {v["id"] for v in vehicles}
            for vid, ri in list(self.state.active_routes.items()):
                if vid not in live_ids:
                    # Vehicle left the sim — clean up highlight if GUI
                    if not self.headless:
                        try:
                            traci.vehicle.setColor(vid, (255, 255, 255, 255))
                        except Exception:
                            pass
                    continue

                if not ri.predictive_route:
                    continue

                # Highlight routed vehicle bright yellow in sumo-gui
                if not self.headless:
                    try:
                        traci.vehicle.setColor(vid, (255, 220, 0, 255))
                    except Exception:
                        pass

                try:
                    curr_edge = next(
                        (v["edge_id"] for v in vehicles if v["id"] == vid), None
                    )
                    if curr_edge and curr_edge in ri.predictive_route:
                        idx = ri.predictive_route.index(curr_edge)
                        remaining = ri.predictive_route[idx:]
                        if len(remaining) > 1:
                            traci.vehicle.setRoute(vid, remaining)
                except Exception:
                    pass

            # ── Logging pipeline (MQTT, classifier, twin, terminal) ───────────
            if self.enable_logging:
                self._log_step(sim_step, sim_time, vehicles, edge_states, zone_states)

            # ── Update shared state ────────────────────────────────────────────
            self.state.update(
                sim_step     = sim_step,
                sim_time     = sim_time,
                vehicles     = vehicles,
                edge_states  = edge_states,
                zone_states  = zone_states,
                training_loss= self.prediction_buffer.training_loss,
                n_samples    = self.prediction_buffer.n_samples,
                lsh_size     = self.prediction_buffer.lsh_size,
                train_steps  = self.prediction_buffer.train_steps,
            )

            if self.step_delay > 0:
                time.sleep(self.step_delay)

            sim_step += 1

    def _handle_route_request(self, req: dict, sim_step: int):
        vid          = req["vehicle_id"]
        dest_edge    = req["dest_edge"]
        vehicle_type = req.get("vehicle_type", "default")

        # Resolve vehicle's current edge
        vehicles   = self.state.vehicles
        curr_edge  = next(
            (v["edge_id"] for v in vehicles if v["id"] == vid), None
        )
        if not curr_edge or curr_edge.startswith(":"):
            print(f"[SimController] Cannot route {vid}: current edge unknown")
            return

        profile = VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["default"])

        pred_route   = self.astar.find_route(
            curr_edge, dest_edge, self.prediction_buffer,
            vehicle_type=vehicle_type, current_step=sim_step,
        )
        static_route = self.astar.find_static_route(curr_edge, dest_edge)

        pred_metrics   = self.astar.estimate_metrics(
            pred_route, self.prediction_buffer, vehicle_type, sim_step
        )
        static_metrics = self.astar.estimate_metrics(
            static_route, self.prediction_buffer, vehicle_type, sim_step
        )

        # Comparative savings
        pt = pred_metrics.get("travel_time_s", 0)
        st = static_metrics.get("travel_time_s", 0)
        pe = pred_metrics.get("emissions", 0)
        se = static_metrics.get("emissions", 1e-6)

        time_saved   = st - pt
        emit_pct     = (se - pe) / max(se, 1e-9) * 100.0

        ri = RouteInfo(
            vehicle_id         = vid,
            origin_edge        = curr_edge,
            dest_edge          = dest_edge,
            vehicle_type       = vehicle_type,
            predictive_route   = pred_route,
            static_route       = static_route,
            predictive_metrics = pred_metrics,
            static_metrics     = static_metrics,
            computed_at_step   = sim_step,
            time_saved_s       = round(time_saved, 1),
            emit_saved_pct     = round(emit_pct, 1),
        )
        self.state.set_route(ri)
        print(
            f"[SimController] Route for {vid}: "
            f"pred={len(pred_route)} edges, static={len(static_route)} edges, "
            f"time_saved={time_saved:.0f}s, emit_saved={emit_pct:.1f}%"
        )

    # ── Logging pipeline ──────────────────────────────────────────────────────

    def _log_step(
        self,
        sim_step:    int,
        sim_time:    float,
        vehicles:    list[dict],
        edge_states: dict,
        zone_states: list,
    ):
        """MQTT publish + event classify + digital twin + terminal dashboard."""
        for zs in zone_states:
            active_es = [s for s in zs.edge_states.values() if s.vehicle_count > 0]
            worst_es  = max(
                active_es,
                key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
                default=None,
            )
            zs_dict = {
                "zone_id":              zs.zone_id,
                "vehicle_count":        zs.vehicle_count,
                "avg_speed":            zs.avg_speed,
                "event":                zs.dominant_event,
                "density":              zs.vehicle_count,
                "worst_road":           worst_es.edge_id if worst_es else "",
                "worst_road_speed_kmh": worst_es.speed_kmh if worst_es else 0.0,
            }

            if self._mqtt:
                try:
                    publish_zone_state(self._mqtt, zs_dict)
                except Exception:
                    pass

            classify(zs_dict)

            if self._twin:
                self._twin.update_zone(zs.zone_id, zs_dict)

        if self._mqtt:
            try:
                for tl_id in get_all_traffic_light_ids():
                    publish_signal_phase(self._mqtt, tl_id, get_traffic_light_state(tl_id))
            except Exception:
                pass

        if sim_step % PRINT_INTERVAL == 0:
            self._print_dashboard(sim_step, sim_time, vehicles, edge_states, zone_states)

    def _print_dashboard(
        self,
        sim_step:    int,
        sim_time:    float,
        vehicles:    list[dict],
        edge_states: dict,
        zone_states: list,
    ):
        """Hierarchical terminal dashboard — identical output to main.py."""
        edge_veh: dict[str, list[dict]] = {}
        for v in vehicles:
            eid = v["edge_id"]
            if not eid.startswith(":"):
                edge_veh.setdefault(eid, []).append(v)

        active_edges = [s for s in edge_states.values() if s.vehicle_count > 0]
        n_cong = sum(1 for s in active_edges if s.event == "congestion")
        n_slow = sum(1 for s in active_edges if s.event == "slowdown")
        n_free = sum(1 for s in active_edges if s.event == "free_flow")

        print(f"\n{'━' * _W}")
        print(f"  GreenSync RSU Monitor │ Step {sim_step:>5} │ "
              f"t={sim_time:>7.1f}s │ 🚗 {len(vehicles):>3} vehicles │ "
              f"Roads: 🔴{n_cong} 🟡{n_slow} 🟢{n_free}")
        print(f"{'━' * _W}")

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
            print("\n  Waiting for vehicles to enter the network …\n")
        else:
            print(f"\n  ▸ RSU ZONES  "
                  f"(showing {len(sorted_zones)} of {len(zone_states)} — "
                  f"most congested first)\n")

        for zs in sorted_zones:
            z_icon = _ICON.get(zs.dominant_event, "⚪")
            z_spd  = round(zs.avg_speed * 3.6, 1)
            z_edges = len(zs.edge_states)
            active_in_zone = [s for s in zs.edge_states.values() if s.vehicle_count > 0]
            worst = max(active_in_zone,
                        key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
                        default=None)
            worst_str = (
                f"  │  worst: {str(worst.edge_id)[:22]} "
                f"{worst.speed_kmh:.1f} km/h {_ICON.get(worst.event,'⚪')}"
                if worst else ""
            )
            print(f"  {z_icon} {zs.zone_id:<10}  "
                  f"{z_edges:>3} roads │ {zs.vehicle_count:>3} vehs │ "
                  f"avg {z_spd:>6.1f} km/h │ {zs.dominant_event.upper()}"
                  f"{worst_str}")

            active_road_states = sorted(
                [s for s in zs.edge_states.values() if s.vehicle_count > 0],
                key=lambda s: (_RANK.get(s.event, 0), s.occupancy),
                reverse=True,
            )[:DASH_TOP_ROADS]

            for s in active_road_states:
                r_icon = _ICON.get(s.event, "⚪")
                print(f"  │  {r_icon} {str(s.edge_id):<26} "
                      f"{s.vehicle_count:>2} vehs │ {s.speed_kmh:>6.1f} km/h │ "
                      f"occ {s.occupancy:>5.1f}% │ halt {s.halting_count:>2} │ {s.event}")
                road_vehs = sorted(
                    edge_veh.get(s.edge_id, []),
                    key=lambda v: v.get("waiting_time", 0),
                    reverse=True,
                )[:DASH_TOP_VEHS]
                for v in road_vehs:
                    vspd = round(v["speed"] * 3.6, 1)
                    x, y = round(v["position"][0], 0), round(v["position"][1], 0)
                    wait = round(v.get("waiting_time", 0), 0)
                    print(f"  │  │  └ {str(v['id']):<10}  "
                          f"{vspd:>6.1f} km/h  ({x:>8.0f}, {y:>8.0f})  wait {wait:>5.0f}s")

            remaining = z_edges - len(active_road_states)
            if remaining > 0:
                print(f"  │     … +{remaining} more roads (no active traffic)")
            print("  │")

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
            print(hdr.format(str(s.edge_id)[:28], f"{s.speed_kmh:.1f}",
                             f"{s.occupancy:.1f}", str(s.halting_count),
                             f"{icon} {s.event}"))
        if not ranked_roads:
            print("  (no vehicles on monitored roads yet)")
        print(f"\n{'━' * _W}", flush=True)

    def _teardown(self):
        try:
            reset_edge_colors(self._all_edges)
        except Exception:
            pass
        # Reset highlighted vehicle colors before closing
        if not self.headless:
            for vid in list(self.state.active_routes.keys()):
                try:
                    traci.vehicle.setColor(vid, (255, 255, 255, 255))
                except Exception:
                    pass
        sumo_stop()
        try:
            self.predictive_model.save()
            print("[SimController] Model checkpoint saved.")
        except Exception:
            pass
        if self._mqtt:
            try:
                mqtt_disconnect(self._mqtt)
            except Exception:
                pass
        self.state.update(running=False)