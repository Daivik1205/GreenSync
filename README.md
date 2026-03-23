# GreenSync — Intelligent Traffic Management System

GreenSync is a simulation-based intelligent traffic management system built on real-world road data from Bengaluru, India. It combines SUMO traffic simulation, RSU zone sensing, MQTT communication, AI-based prediction, and eco-routing into a unified pipeline — with a Flutter app as the visualisation layer.

---

## System Architecture

```
SUMO Simulation (TraCI)
        │
        ▼
RSU Zone Sensing          ← Phase 2: RADAR/zone-based density & speed
        │
        ▼
MQTT Communication        ← Phase 3: V2X-inspired pub/sub data flow
        │
        ▼
Event Classifier          ← Phase 4: congestion / slowdown / free_flow
        │
        ▼
Digital Twin              ← Phase 5: real-time city state graph
        │
        ▼
AI Prediction (GRU)       ← Phase 6: future speed & congestion forecast
        │
        ▼
Routing Engine (A*)       ← Phase 8: eco-optimal path computation
        │
        ▼
Flutter App               ← Phase 9: live map, hazards, CO₂ savings
```

---

## Project Structure

```
GreenSync/
├── main.py                    # Phase 10 — full system entry point
├── greensync_phase1/          # SUMO map files (Bengaluru OSM)
│   ├── map.net.xml
│   ├── map.rou.xml
│   ├── map.sumocfg
│   └── test_sumo.py           # Standalone SUMO sanity check
├── simulation/                # Phase 1 — TraCI interface
│   └── traci_interface.py
├── rsu/                       # Phase 2 — RSU zone sensing
│   └── rsu_manager.py
├── communication/             # Phase 3 — MQTT pub/sub
│   ├── publisher.py
│   └── subscriber.py
├── event_classifier/          # Phase 4 — event detection
│   └── classifier.py
├── digital_twin/              # Phase 5 — city state graph
│   └── twin.py
├── ai/                        # Phase 6 — GRU + XGBoost models
├── propagation/               # Phase 7 — cascading event modelling
├── routing/                   # Phase 8 — A* eco-routing
│   └── router.py
├── app/                       # Phase 9 — Flutter app
├── supabase/                  # DB schema + queries
├── model/                     # Saved model artefacts
├── explore_network.py         # One-time utility: dump TL + edge IDs
├── run.sh                     # Launcher: sets X11 env vars + runs pipeline
├── requirements.txt
└── rsu/
    ├── zones_config.py        # 6 RSU zone definitions (TL IDs + extra edges)
    └── rsu_manager.py         # Zone sensing, event detection, GUI polygon overlay
```

---

## Phases

| Phase | Module | Status | Description |
|-------|--------|--------|-------------|
| 1 | `simulation/` | ✅ Done | SUMO + TraCI interface, Bengaluru map, signal states, edge data |
| 2 | `rsu/` | ✅ Done | 6 RSU zones, auto edge discovery, GUI polygon overlay, event detection |
| 3 | `communication/` | 🔧 In progress | MQTT pub/sub |
| 4 | `event_classifier/` | ⏳ Pending | Rule-based event detection |
| 5 | `digital_twin/` | ⏳ Pending | Real-time city state graph |
| 6 | `ai/` | ⏳ Pending | GRU speed prediction |
| 7 | `propagation/` | ⏳ Pending | Cascading event modelling |
| 8 | `routing/` | ⏳ Pending | A* eco-routing engine |
| 9 | `app/` | ⏳ Pending | Flutter visualisation app |
| 10 | `main.py` | 🔧 In progress | Full system integration loop |

---

## Setup

### Prerequisites

- Python 3.12
- macOS with XQuartz (for sumo-gui) or Linux
- Mosquitto MQTT broker
- Supabase account (for Phase 5+)

### Installation

```bash
git clone https://github.com/Daivik1205/GreenSync.git
cd GreenSync

python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Fix SUMO binaries (macOS only)

The `eclipse-sumo` pip package installs real arm64 binaries but wraps them in broken Python scripts. Fix with symlinks:

```bash
SUMO_BIN="venv/lib/python3.12/site-packages/sumo/bin"
rm venv/bin/sumo venv/bin/sumo-gui
ln -s "$(pwd)/$SUMO_BIN/sumo" venv/bin/sumo
ln -s "$(pwd)/$SUMO_BIN/sumo-gui" venv/bin/sumo-gui
```

### Environment Variables

Add to your `~/.zshrc`:

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

### Headless (default — RPi / CI)

```bash
source venv/bin/activate
python main.py
```

Terminal output every 50 steps shows up to 20 live vehicles with speed (km/h), coordinates (x, y) and edge ID:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Step   100 | Total vehicles:  81 | Zones: 0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ID       Speed (km/h)          X          Y  Edge
  -------- ------------ ---------- ----------  --------------------
  0              42.3   77423.12  14231.88   132191814#3
  1               0.0   77198.44  14109.23   763175325#1
```

### With SUMO GUI (macOS dev — two terminals)

**Terminal 1** — open the visual map:

```bash
export DISPLAY=:0 XAUTHORITY=~/.Xauthority
export PROJ_DATA="venv/lib/python3.12/site-packages/sumo/data/proj"
export FONTCONFIG_FILE=/opt/homebrew/etc/fonts/fonts.conf
source venv/bin/activate
sumo-gui -c greensync_phase1/map.sumocfg
```

Click ▶ Play to watch vehicles moving on Bengaluru roads.

**Terminal 2** — run the data pipeline:

```bash
source venv/bin/activate
python main.py
```

> Note: on macOS the GUI and pipeline run as independent processes due to XQuartz subprocess constraints. For RPi deployment both run headlessly in a single process.

### Explore the SUMO network

```bash
python explore_network.py
# Dumps all 35 traffic light IDs and 2841 edge IDs from the Bengaluru map
```

---

## Map Data

| Property | Value |
|----------|-------|
| Source | OpenStreetMap (Bengaluru, India) |
| Conversion | `netconvert` (OSM → SUMO network) |
| Traffic lights | 35 junctions |
| Road edges | 2841 |
| Vehicles | Generated via `randomTrips` |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Traffic simulation | SUMO 1.26.0 + TraCI |
| Communication | MQTT (Mosquitto / paho-mqtt) |
| Database | Supabase (PostgreSQL) |
| AI models | XGBoost, GRU (PyTorch) |
| Routing | NetworkX (A*) |
| Mobile app | Flutter |
| Backend runtime | Raspberry Pi (target) |

---

## Contributing

All active development happens on the `dev` branch. PRs are merged into `main` at milestone checkpoints.

```bash
git checkout dev
git pull origin dev
# make your changes
git push origin dev
```
