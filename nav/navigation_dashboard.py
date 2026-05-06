import streamlit as st
import time
import pandas as pd
import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from nav.sim_controller import SimController
from nav.modified_astar import VEHICLE_PROFILES

st.set_page_config(page_title="GreenSync Navigation", layout="wide")

# Read headless flag set by run.sh (0 = GUI, 1 = headless)
_HEADLESS = os.environ.get("GREENSYNC_HEADLESS", "0") == "1"

@st.cache_resource
def get_sim_controller():
    ctrl = SimController(headless=_HEADLESS, step_delay=0.0)
    ctrl.start()
    return ctrl

ctrl = get_sim_controller()
state = ctrl.state.snapshot()

st.title("GreenSync Predictive Navigation Dashboard")
st.markdown("Temporally-aware eco-routing with GRU+LSH traffic forecasting.")

# ── Guard: only show live data when SUMO is running ───────────────────────────
if state["error"]:
    st.error(f"Simulation error: {state['error']}")
    st.stop()

if not state["running"]:
    st.warning("Simulation is not running. Start it via `run.sh` and wait for SUMO to initialise.")
    st.stop()

# ── Simulation State ──────────────────────────────────────────────────────────
st.header("Simulation State")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Sim Step", state["sim_step"])
c2.metric("Sim Time (s)", round(state["sim_time"], 1))
c3.metric("Vehicles", len(state["vehicles"]))
c4.metric("Tracked Edges", len(state["edge_states"]))

# ── Prediction Model ──────────────────────────────────────────────────────────
st.header("Prediction Model (GRU + LSH)")
p1, p2, p3, p4 = st.columns(4)
loss_str = f"{state['training_loss']:.4f}" if state["training_loss"] is not None else "N/A"
p1.metric("Training Loss", loss_str)
p2.metric("Train Steps", state["train_steps"])
p3.metric("Training Samples", state["n_samples"])
p4.metric("LSH Size", state["lsh_size"])

# ── Route Request ─────────────────────────────────────────────────────────────
st.header("Request Predictive Route")

if not ctrl.astar._loaded:
    st.info("Loading road network… please wait.")
    time.sleep(1.0)
    st.rerun()

# Filter to vehicles on real (non-junction) edges only
routable = [v for v in state["vehicles"] if v["edge_id"] and not v["edge_id"].startswith(":")]

if not routable:
    st.info("No routable vehicles right now (all are on junctions). Will refresh.")
else:
    vehicle_map = {v["id"]: v for v in routable}

    with st.form("route_request"):
        col_v, col_d, col_t = st.columns(3)

        selected_vid = col_v.selectbox(
            "Vehicle",
            list(vehicle_map.keys()),
            help="Only vehicles on a real edge are shown.",
        )
        selected_v  = vehicle_map.get(selected_vid, {})
        origin_edge = selected_v.get("edge_id", "")
        col_v.text_input("Origin (current edge)", value=origin_edge, disabled=True)

        all_edges = sorted(ctrl.astar.get_all_edge_ids())
        dest_edge = col_d.selectbox(
            "Destination Edge",
            all_edges,
            help="Type to search. All map edges are listed.",
        )

        vtype = col_t.selectbox("Vehicle Profile", list(VEHICLE_PROFILES.keys()))

        submitted = st.form_submit_button("Find Eco-Route")
        if submitted:
            if not selected_vid or not dest_edge:
                st.error("Select both a vehicle and a destination edge.")
            elif origin_edge == dest_edge:
                st.error("Origin and destination are the same edge.")
            else:
                ctrl.request_route(selected_vid, dest_edge, vtype)
                st.success(f"Routing {selected_vid}  {origin_edge} -> {dest_edge}  ({vtype})")

# ── Active Routes ─────────────────────────────────────────────────────────────
st.header("Active Routes & Savings")
routes = state["active_routes"]

if not routes:
    st.info("No active predictive routes. Request one above.")
else:
    for vid, ri in routes.items():
        st.subheader(f"Vehicle: {vid}  ({ri.vehicle_type.upper()})")
        st.write(f"**Origin:** `{ri.origin_edge}`  ->  **Destination:** `{ri.dest_edge}`")

        if not ri.predictive_route:
            st.warning(f"No route found for {vid}. The vehicle may be on a disconnected edge.")
        else:
            s1, s2 = st.columns(2)
            s1.metric("Time Saved vs Static", f"{ri.time_saved_s} s",
                      delta=f"{ri.time_saved_s} s", delta_color="normal")
            s2.metric("Emissions Saved vs Static", f"{ri.emit_saved_pct} %",
                      delta=f"{ri.emit_saved_pct} %", delta_color="normal")

            pm = ri.predictive_metrics
            sm = ri.static_metrics
            if pm and sm:
                df = pd.DataFrame({
                    "Metric": ["Travel Time (s)", "Delay (s)", "Emissions", "Fuel",
                               "Length (m)", "Avg Speed (km/h)"],
                    "Predictive (A*)": [
                        pm.get("travel_time_s", 0), pm.get("delay_s", 0),
                        pm.get("emissions", 0),     pm.get("fuel", 0),
                        pm.get("length_m", 0),      pm.get("avg_speed_kmh", 0),
                    ],
                    "Static (Baseline)": [
                        sm.get("travel_time_s", 0), sm.get("delay_s", 0),
                        sm.get("emissions", 0),     sm.get("fuel", 0),
                        sm.get("length_m", 0),      sm.get("avg_speed_kmh", 0),
                    ],
                })
                st.table(df)

            with st.expander(
                f"Route edges — Predictive: {len(ri.predictive_route)}  |  Static: {len(ri.static_route)}"
            ):
                ec1, ec2 = st.columns(2)
                with ec1:
                    st.write("**Predictive Route**")
                    for i, e in enumerate(ri.predictive_route, 1):
                        st.write(f"{i}. `{e}`")
                with ec2:
                    st.write("**Static Baseline**")
                    for i, e in enumerate(ri.static_route, 1):
                        st.write(f"{i}. `{e}`")

        st.divider()

# ── Auto-refresh at bottom so all content renders first ───────────────────────
if state["running"]:
    time.sleep(1.0)
    st.rerun()
