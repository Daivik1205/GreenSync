# GreenSync — V2I Eco-Routing Engine for Bengaluru

GreenSync is a **Vehicle-to-Infrastructure (V2I) eco-routing engine** built on real Bengaluru road data. Traffic signals and road sensors communicate with vehicles in real time to suggest the most fuel-efficient, least-congested routes — reducing idle time, CO₂ emissions, and urban congestion.

Started as an academic IDP (Interdisciplinary Project) spanning CS, Electronics & Instrumentation, and Chemical Engineering. The ChemE component uses GreenSync's traffic data to quantify actual CO₂/NOₓ/PM2.5 reductions from smarter routing.

---

## Architecture

### V1 — Pure Simulation

Everything synthetic. SUMO on a real Bengaluru OSM map (lat 12.96–12.97, lon 77.58–77.60), 1000 simulated vehicles, 35 real signal junctions.

```
SUMO (TraCI) → RSU zone sensing → MQTT publish → Event classification
             → Digital Twin update → A* routing → route back into SUMO
```

### V2 — Hybrid Real-World Engine

Real users' route choices become inputs to the simulation, not just outputs.

```
TomTom Live Traffic  ──(60s poll)──┐
Crowdsourced Android Intents ───────┼──▶ HybridDigitalTwin ──▶ A* Eco-routing
SUMO TraCI (per step) ──────────────┘           │
                                                 ▼
                                    Shadow Vehicles injected into SUMO
                                    (real user routes mirrored in simulation)
```

When 50 people pick Route A on the Android app, that intent pressure is factored into the routing cost for the next person. SUMO mirrors those real routes as blue "shadow vehicles."

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Simulation | SUMO + TraCI (Python) | Urban traffic sim on real Bengaluru OSM map |
| Map data | OpenStreetMap (netconvert + duarouter) | Real road geometry, 35 signal junctions |
| RSU sensing | TraCI subscriptions | Queue length, speed, occupancy per edge |
| Communication | MQTT (paho-mqtt, Mosquitto) | Push-based real-time pub/sub |
| Event classification | Rule-based (Python) | free_flow / slowdown / congestion per zone |
| Digital Twin | NetworkX DiGraph | Graph-based real-time road state |
| AI models | XGBoost + GRU (scaffolded) | Signal phase prediction, speed forecasting |
| Real traffic | TomTom Traffic Flow API | Live currentSpeed / freeFlowSpeed per corridor |
| Routing | A* on NetworkX graph | Cost = time + congestion + intent pressure + CO₂ |
| Android app | Kotlin + Jetpack | Route selection, HUD advisory, ECU telemetry |
| Android Auto | Car App Library (Jetpack) | DHU-compatible in-car interface |
| Route alternatives | OSRM (public demo server) | 3 route alternatives, encoded polyline |
| ECU telemetry | CarPropertyManager | Speed, fuel level, battery % from CAN bus |
| Database | Supabase (PostgreSQL + PostGIS) | Emissions logging, RLS, geospatial queries |
| Emissions analysis | SQL (6 ChemE queries) | CO₂/NOₓ/PM2.5 trends, vehicle mix, corridor ranking |

---

## Project Structure

```
GreenSync/
├── greensync_phase1/        SUMO map files (map.net.xml, routes, .sumocfg)
├── simulation/              TraCI interface — start/stop/step SUMO
├── rsu/                     RSU zone sensing, edge detector, zone builder
│   ├── zone_builder.py      Voronoi-style zones from 35 TL positions
│   ├── rsu_manager.py       Adaptive radius per zone, sense_all_zones()
│   └── edge_detector.py     TraCI subscriptions, color_edges() for GUI
├── communication/           MQTT publisher (paho)
├── event_classifier/        Rule-based: congestion / slowdown / free_flow
├── digital_twin/            Base DigitalTwin — NetworkX DiGraph
├── ai/                      GRU + XGBoost (scaffolded, not trained)
├── propagation/             BFS event propagation across zones
├── routing/                 A* router (V1 weights: time 0.4, cong 0.3, CO₂ 0.3)
├── supabase/
│   ├── migrations/001_create_tables.sql   7-table schema + PostGIS + RLS
│   └── queries/emissions_analysis.sql     6 ChemE analysis queries
├── backend/                 V2 additions
│   ├── tomtom_poller.py     TomTom Traffic Flow API, 13 Bengaluru points, mock mode
│   ├── intent_aggregator.py MQTT subscriber, RouteIntentStore (30-min TTL)
│   ├── hybrid_twin.py       Extends DigitalTwin, blended edge costs
│   ├── shadow_vehicle_injector.py  TraCI shadow vehicle injection
│   └── v2_main.py           V2 orchestrator
├── android/                 V2 additions
│   └── app/src/main/kotlin/com/greensync/
│       ├── models/          Route, IntentPayload, EcuTelemetryPayload
│       ├── screens/         RouteSelectionActivity, HUDActivity
│       │                    RouteSelectionCarScreen, HUDCarScreen (Auto)
│       ├── services/        OsrmService, MqttIntentService, EcuTelemetryService
│       ├── viewmodels/      RouteViewModel
│       └── MainActivity.kt
└── main.py                  V1 orchestrator (standalone)
```

---

## How It Works

### RSU Zone Sensing
35 traffic signal junctions each become an RSU zone with adaptive radius — dense city junctions get small zones, isolated arterial junctions get large ones. Each zone monitors road edges via TraCI subscriptions (batch read, one round trip per step).

### MQTT Communication
Zone states and signal phases are published every simulation step:
- `greensyncq/rsu/{zone_id}/state` — vehicle count, avg speed, event, worst road
- `greensyncq/signal/{tl_id}/phase` — current signal phase string

### Hybrid Digital Twin (V2)
`HybridDigitalTwin.edge_cost()` blends α=0.4 SUMO + 0.6 TomTom speed, then adds an intent pressure term from `RouteIntentStore`. A* weights: time=0.35, congestion=0.30, intent=0.20, CO₂=0.15.

### Shadow Vehicles (V2)
`ShadowVehicleInjector` mirrors each active user intent into SUMO as a blue vehicle (RGBA 0,120,255,200). GPS waypoints → SUMO edges via `sumolib`. ECU speed applied via `traci.vehicle.setSpeed()`. Vehicles expire when intent TTL (30 min) expires.

### Android App
- **Route selection**: OSRM for 3 alternatives (Yelahanka → Mysore Road corridor), rendered on Google Maps
- **Intent publishing**: On route tap, publishes JSON to `greensync/user/intent` via MQTT
- **HUD**: Subscribes to RSU/signal topics, shows fullscreen STOP / COAST / PROCEED advisory
- **Android Auto**: Full Car App Library — same route selection and HUD as ListTemplate + MessageTemplate
- **ECU telemetry**: CarPropertyManager reads speed, fuel, battery from Android Automotive OS CAN bus every 5s; falls back to mock values on a regular phone

### Supabase Schema (7 tables)
`junctions`, `signal_events`, `queue_snapshots`, `advisory_logs`, `emissions_estimates`, `route_intents`, `ecu_telemetry`. All tables have RLS enabled. ChemE member runs 6 SQL queries: total emissions per junction, emissions vs queue correlation, hourly CO₂ trend, vehicle mix (ICE vs EV), intent-driven congestion shift, geospatial corridor ranking.

---

## Setup

### Prerequisites
- Python 3.12
- macOS with XQuartz (for sumo-gui) or Linux
- Mosquitto MQTT broker
- Supabase account (for DB logging)
- TomTom API key (optional — `tomtom_poller.py` has a mock mode)

### Installation

```bash
git clone https://github.com/Daivik1205/GreenSync.git
cd GreenSync

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### macOS SUMO binary fix

```bash
SUMO_BIN="venv/lib/python3.12/site-packages/sumo/bin"
rm venv/bin/sumo venv/bin/sumo-gui
ln -s "$(pwd)/$SUMO_BIN/sumo" venv/bin/sumo
ln -s "$(pwd)/$SUMO_BIN/sumo-gui" venv/bin/sumo-gui
```

### Environment variables (`~/.zshrc`)

```bash
export SUMO_HOME="$VIRTUAL_ENV/lib/python3.12/site-packages/sumo"
export PROJ_DATA="$SUMO_HOME/data/proj"
export FONTCONFIG_FILE=/opt/homebrew/etc/fonts/fonts.conf
export DISPLAY=:0
export XAUTHORITY=~/.Xauthority
```

### Start Mosquitto

```bash
brew services start mosquitto
```

---

## Running

### V1 (headless)

```bash
source venv/bin/activate
python main.py
```

### V2 (hybrid engine)

```bash
source venv/bin/activate
python backend/v2_main.py
```

### With SUMO GUI (macOS — two terminals)

**Terminal 1:**
```bash
export DISPLAY=:0 XAUTHORITY=~/.Xauthority
source venv/bin/activate
sumo-gui -c greensync_phase1/map.sumocfg
```

**Terminal 2:**
```bash
source venv/bin/activate
python main.py   # or backend/v2_main.py
```

---

## Scope Notes

- **"6G"**: Not simulated. MQTT is the communication layer — V2X-inspired pub/sub.
- **"Digital Twin"**: Software state graph, not a physics-based twin.
- **ECU telemetry on phone**: CarPropertyManager only works on Android Automotive OS. Regular phone falls back to mock values (speed 20–60 random, fuel=0.65).
- **OSRM**: Public demo server — rate-limited. Self-host with Karnataka OSM extract for production.
- **AI models (GRU + XGBoost)**: Scaffolded, not yet trained on real data.

---

## Branch Strategy

Active development on `dev`. PRs merged into `main` at milestone checkpoints.

```bash
git checkout dev
git pull origin dev
```
