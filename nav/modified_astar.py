# nav/modified_astar.py
# ModifiedAStar — temporally-aware, multi-objective A* on the SUMO road network.
#
# Key properties:
#   • Time-dependent: as A* explores a node it estimates the arrival time and
#     queries PredictionBuffer for the traffic state at that future moment.
#   • Multi-objective cost: W_time·time + W_delay·delay + W_emit·emissions + W_fuel·fuel
#   • Vehicle profiles: EV (favour low-emission/regen paths) vs ICE (favour time+idle).
#   • Returns SUMO edge IDs for direct TraCI rerouting.
#   • Separate find_static_route() provides the baseline comparison route.

from __future__ import annotations

import math
import os
from typing import Optional

import networkx as nx
import numpy as np
import sumolib

from .prediction_buffer import PredictionBuffer

# ── Network file path ─────────────────────────────────────────────────────────
_NET_XML = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "greensync_phase1", "map.net.xml")
)

# ── Default cost weights ──────────────────────────────────────────────────────
W_TIME   = 0.35
W_DELAY  = 0.25
W_EMIT   = 0.20
W_FUEL   = 0.20

SIM_STEP_S = 1.0   # simulation step duration in real seconds

# ── Vehicle profiles ──────────────────────────────────────────────────────────
VEHICLE_PROFILES: dict[str, dict] = {
    "ev": {
        "w_time":  0.20,
        "w_delay": 0.20,
        "w_emit":  0.35,
        "w_fuel":  0.25,
        "regen":   True,   # reward slow-down zones (regenerative braking)
    },
    "ice": {
        "w_time":  0.40,
        "w_delay": 0.30,
        "w_emit":  0.15,
        "w_fuel":  0.15,
        "regen":   False,
    },
    "default": {
        "w_time":  W_TIME,
        "w_delay": W_DELAY,
        "w_emit":  W_EMIT,
        "w_fuel":  W_FUEL,
        "regen":   False,
    },
}


class ModifiedAStar:
    """
    Temporally-aware eco-routing engine on the full SUMO junction graph.

    Usage:
        router = ModifiedAStar()
        ok = router.load_network()
        route = router.find_route(origin_edge, dest_edge, buffer, vehicle_type="ice")
        static = router.find_static_route(origin_edge, dest_edge)
        metrics = router.estimate_metrics(route, buffer)
    """

    def __init__(self, net_xml: str = _NET_XML):
        self._net_xml = net_xml
        self.net: Optional[sumolib.net.Net] = None
        self.graph: nx.DiGraph = nx.DiGraph()
        # Cached per-edge geometry and limits
        self._edge_len:   dict[str, float] = {}   # metres
        self._edge_speed: dict[str, float] = {}   # m/s (posted limit)
        self._edge_mid:   dict[str, tuple[float, float]] = {}  # (x, y) midpoint
        self._edge_shape: dict[str, list[tuple[float, float]]] = {}  # full shape
        # Node → (x, y) for heuristic
        self._node_coord: dict[str, tuple[float, float]] = {}
        self._loaded = False

    # ── Network loading ───────────────────────────────────────────────────────

    def load_network(self) -> bool:
        """
        Parse map.net.xml with sumolib and build a NetworkX junction graph.
        Must be called once before any routing calls.
        """
        if self._loaded:
            return True
        if not os.path.exists(self._net_xml):
            print(f"[ModifiedAStar] net.xml not found: {self._net_xml}")
            return False
        try:
            print(f"[ModifiedAStar] Loading {self._net_xml} …")
            self.net = sumolib.net.readNet(self._net_xml, withInternal=False)
            self._build_graph()
            self._loaded = True
            print(
                f"[ModifiedAStar] Graph ready — "
                f"{self.graph.number_of_nodes()} junctions, "
                f"{self.graph.number_of_edges()} road edges"
            )
            return True
        except Exception as exc:
            print(f"[ModifiedAStar] Load failed: {exc}")
            return False

    def _build_graph(self):
        for edge in self.net.getEdges():
            eid = edge.getID()
            if eid.startswith(":"):
                continue

            length = max(edge.getLength(), 1.0)
            speed  = max(edge.getSpeed(), 1.0)
            shape  = edge.getShape()

            # Midpoint for visualisation
            if shape:
                mid = shape[len(shape) // 2]
            else:
                fn = edge.getFromNode().getCoord()
                tn = edge.getToNode().getCoord()
                mid = ((fn[0] + tn[0]) / 2, (fn[1] + tn[1]) / 2)

            self._edge_len[eid]   = length
            self._edge_speed[eid] = speed
            self._edge_mid[eid]   = mid
            self._edge_shape[eid] = list(shape) if shape else [mid]

            fn_id = edge.getFromNode().getID()
            tn_id = edge.getToNode().getID()
            self._node_coord[fn_id] = edge.getFromNode().getCoord()
            self._node_coord[tn_id] = edge.getToNode().getCoord()

            self.graph.add_node(fn_id)
            self.graph.add_node(tn_id)
            self.graph.add_edge(
                fn_id, tn_id,
                edge_id=eid,
                length=length,
                speed=speed,
            )
    def _edge_cost(
        self,
        edge_id:     str,
        arrival_t:   int,    # estimated arrival time (sim steps from now)
        buf:         PredictionBuffer,
        profile:     dict,
    ) -> float:
        """
        Multi-objective weighted cost of traversing edge_id.
        Uses predicted traffic state at arrival_t from PredictionBuffer.
        """
        length      = self._edge_len.get(edge_id, 10.0)
        speed_limit = self._edge_speed.get(edge_id, 13.9)

        # ── Fetch predicted (or current) state ────────────────────────────────
        pred = buf.get_prediction(edge_id, arrival_t)
        if pred is None:
            sv = buf.get_current_state(edge_id)
            pred = sv.to_array() if sv else np.array([0.5, 0.1, 0.0, 0.0], dtype=np.float32)

        speed_norm  = float(np.clip(pred[0], 0.02, 1.0))
        density     = float(np.clip(pred[1], 0.0,  1.0))
        delay_norm  = float(np.clip(pred[2], 0.0,  1.0))
        congestion  = float(np.clip(pred[3], 0.0,  1.0))

        actual_speed = speed_norm * speed_limit   # m/s
        travel_time  = length / max(actual_speed, 0.5)     # seconds

        # ── Emission proxy (VT-Micro inspired) ───────────────────────────────
        speed_kmh = actual_speed * 3.6
        # Emissions peak at standstill and at highway speeds
        emit_factor = 1.0 + 3.5 * congestion + max(0.0, (speed_kmh - 80.0) / 40.0)
        emissions   = (travel_time * emit_factor * (1.0 + density)) / 100.0

        # ── Fuel proxy ────────────────────────────────────────────────────────
        fuel_cost = (travel_time * (1.0 + 2.0 * delay_norm + density)) / 100.0

        # ── Regen braking bonus for EVs ───────────────────────────────────────
        regen_credit = 0.0
        if profile.get("regen") and congestion > 0.3:
            regen_credit = -0.05 * congestion

        cost = (
            profile["w_time"]  * travel_time / 60.0
            + profile["w_delay"] * delay_norm
            + profile["w_emit"]  * emissions
            + profile["w_fuel"]  * fuel_cost
            + regen_credit
        )
        return max(cost, 1e-4)

    # ── A* heuristic ─────────────────────────────────────────────────────────

    def _heuristic(self, node: str, goal: str) -> float:
        """Euclidean-distance lower bound in cost units (minutes at free-flow)."""
        nc = self._node_coord.get(node)
        gc = self._node_coord.get(goal)
        if nc is None or gc is None:
            return 0.0
        dist = math.hypot(nc[0] - gc[0], nc[1] - gc[1])
        return dist / 14.0 / 60.0  # 14 m/s ≈ 50 km/h free-flow

    # ── Public routing API ────────────────────────────────────────────────────

    def find_route(
        self,
        origin_edge:   str,
        dest_edge:     str,
        buf:           PredictionBuffer,
        vehicle_type:  str = "default",
        current_step:  int = 0,
    ) -> list[str]:
        """
        Predictive eco-optimal route.  Returns ordered list of SUMO edge IDs.

        The weight function is evaluated lazily by nx.astar_path; arrival time
        for each edge is tracked in a closure dict so future predictions can be
        queried at the right temporal offset.
        """
        if not self._loaded:
            return []

        try:
            o_edge = self.net.getEdge(origin_edge)
            d_edge = self.net.getEdge(dest_edge)
        except Exception:
            return []

        if o_edge is None or d_edge is None:
            return []

        origin_node = o_edge.getFromNode().getID()
        dest_node   = d_edge.getToNode().getID()

        if origin_node not in self.graph or dest_node not in self.graph:
            return []

        profile      = VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["default"])
        arrival: dict[str, int] = {origin_node: current_step}

        def weight(u: str, v: str, data: dict) -> float:
            eid    = data.get("edge_id", "")
            t_arr  = arrival.get(u, current_step)
            cost   = self._edge_cost(eid, t_arr, buf, profile)
            # Propagate estimated arrival time forward
            spd    = self._edge_speed.get(eid, 13.9) * 0.7   # assume 70% of limit
            dt     = int(self._edge_len.get(eid, 10.0) / max(spd, 0.1) / SIM_STEP_S)
            arrival[v] = t_arr + dt
            return cost

        try:
            node_path = nx.astar_path(
                self.graph, origin_node, dest_node,
                heuristic=lambda u, g: self._heuristic(u, g),
                weight=weight,
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

        return self._nodes_to_edges(node_path)

    def find_static_route(
        self, origin_edge: str, dest_edge: str
    ) -> list[str]:
        """
        Classic shortest-path by road length (no prediction, no cost model).
        Used as the baseline comparison route shown in the dashboard.
        """
        if not self._loaded:
            return []
        try:
            o_edge = self.net.getEdge(origin_edge)
            d_edge = self.net.getEdge(dest_edge)
        except Exception:
            return []
        if o_edge is None or d_edge is None:
            return []

        origin_node = o_edge.getFromNode().getID()
        dest_node   = d_edge.getToNode().getID()

        if origin_node not in self.graph or dest_node not in self.graph:
            return []
        try:
            node_path = nx.shortest_path(
                self.graph, origin_node, dest_node, weight="length"
            )
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []
        return self._nodes_to_edges(node_path)
    def estimate_metrics(
        self,
        route:        list[str],
        buf:          PredictionBuffer,
        vehicle_type: str = "default",
        start_step:   int = 0,
    ) -> dict:
        """
        Estimate travel-time, delay, emissions, fuel, and length for a route.
        Uses the same prediction queries as A* for consistency.
        """
        if not route:
            return {
                "travel_time_s": 0, "travel_time_min": 0,
                "delay_s": 0, "emissions": 0, "fuel": 0, "length_m": 0,
                "avg_speed_kmh": 0,
            }

        profile = VEHICLE_PROFILES.get(vehicle_type, VEHICLE_PROFILES["default"])
        t = start_step
        total_time = total_delay = total_emit = total_fuel = total_len = 0.0

        for eid in route:
            length      = self._edge_len.get(eid, 10.0)
            speed_limit = self._edge_speed.get(eid, 13.9)

            pred = buf.get_prediction(eid, t)
            if pred is None:
                sv = buf.get_current_state(eid)
                pred = sv.to_array() if sv else np.array([0.5, 0.1, 0.0, 0.0])

            speed_norm = float(np.clip(pred[0], 0.02, 1.0))
            density    = float(np.clip(pred[1], 0.0,  1.0))
            delay_norm = float(np.clip(pred[2], 0.0,  1.0))
            congestion = float(np.clip(pred[3], 0.0,  1.0))

            actual_speed = speed_norm * speed_limit
            travel_time  = length / max(actual_speed, 0.5)
            delay        = delay_norm * travel_time
            speed_kmh    = actual_speed * 3.6
            emit_factor  = 1.0 + 3.5 * congestion + max(0.0, (speed_kmh - 80) / 40)

            total_time  += travel_time
            total_delay += delay
            total_emit  += (travel_time * emit_factor * (1.0 + density)) / 100.0
            total_fuel  += (travel_time * (1.0 + 2.0 * delay_norm + density)) / 100.0
            total_len   += length

            dt = int(length / max(actual_speed * 0.7, 0.1) / SIM_STEP_S)
            t += dt

        avg_spd = (total_len / max(total_time, 1.0)) * 3.6

        return {
            "travel_time_s":   round(total_time, 1),
            "travel_time_min": round(total_time / 60.0, 2),
            "delay_s":         round(total_delay, 1),
            "emissions":       round(total_emit, 4),
            "fuel":            round(total_fuel, 4),
            "length_m":        round(total_len, 0),
            "avg_speed_kmh":   round(avg_spd, 1),
        }

    # ── Geometry helpers (used by dashboard map) ──────────────────────────────

    def get_edge_shape(self, edge_id: str) -> list[tuple[float, float]]:
        return self._edge_shape.get(edge_id, [])

    def get_all_edge_ids(self) -> list[str]:
        return list(self._edge_len.keys())

    def get_edge_midpoint(self, edge_id: str) -> tuple[float, float] | None:
        return self._edge_mid.get(edge_id)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _nodes_to_edges(self, node_path: list[str]) -> list[str]:
        """Convert a list of junction IDs to the SUMO edge IDs connecting them."""
        route = []
        for i in range(len(node_path) - 1):
            data = self.graph.get_edge_data(node_path[i], node_path[i + 1])
            if data:
                route.append(data["edge_id"])
        return route