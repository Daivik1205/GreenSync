# GreenSync-Q — Project Context for Claude Code

## What This Project Is

**GreenSync-Q** is an Edge AI-powered V2I (Vehicle-to-Infrastructure) framework designed for urban traffic optimization. The core idea: a Raspberry Pi acts as a simulated smart intersection, running an XGBoost model to predict signal phase timing, and broadcasting both signal timing *and* queue length over MQTT. A Flutter app consumes this data to give drivers a **queue-aware speed advisory** — telling them whether to coast or proceed based on actual queue conditions, not just signal state.

This is an Interdisciplinary Project (IDP) with team members from CS, EIE, and Chemical Engineering. Architectural decisions reflect all three disciplines.

---

## Problem Being Solved

Existing green-wave / speed advisory systems only broadcast signal phase timing. In dense urban traffic (e.g., Bengaluru), a green signal ahead means nothing if there's a 200m queue at that junction. Rushing to catch a green light into a heavy queue wastes fuel, increases emissions, and provides no travel time benefit.

**GreenSync-Q solves this** by broadcasting queue length alongside phase timing, so the advisory can say "don't rush — heavy queue ahead even though light is green."

---

## Full System Architecture

```
[Raspberry Pi — Edge Server + Simulator]
        |
        |-- Overpass API (OpenStreetMap) --> fetch real signal coordinates in Bengaluru
        |-- Synthetic traffic data generator --> queue length, time-of-day
        |-- XGBoost model (local inference) --> predict signal phase timing
        |-- MQTT Broker (Mosquitto) --> publish phase + queue data
        |
[MQTT Topics]
  greensyncq/signal/{junction_id}/phase     --> { phase: "GREEN"/"RED"/"YELLOW", duration_remaining: int }
  greensyncq/signal/{junction_id}/queue     --> { queue_length: int, estimated_clearance_time: float }
        |
[Supabase — PostgreSQL Backend]
  - Stores historical signal + queue + advisory data
  - Enables SQL-based emissions analysis (for Chemical Engineering team member)
  - Tables: junctions, signal_events, queue_snapshots, advisory_logs, emissions_estimates
        |
[Flutter App — Primary Deliverable]
  - Speed Advisory HUD (main screen)
  - Zonal Fluidity Heatmap
  - Journey Analytics dashboard
  - Signal Timing Insights panel
```

---

## Component Breakdown

### 1. Raspberry Pi (Simulation + Edge)
- Runs **Mosquitto MQTT broker**
- Fetches junction coordinates from **Overpass API** (OpenStreetMap)
- Simulates traffic: generates queue length and time-of-day features
- Runs **XGBoost regression model** locally for signal phase timing prediction
- Publishes predictions + queue data to MQTT topics
- Language: **Python**

### 2. XGBoost Model
- **Input features**: queue_length, time_of_day (hour + minute), day_of_week, junction_id (encoded)
- **Output**: predicted phase duration remaining (regression), phase label (classification variant)
- Training data: synthetic dataset mimicking Bengaluru peak/off-peak patterns
- Model saved as `.pkl` / `.ubj` and loaded at RPi startup
- No cloud inference — fully local

### 3. MQTT (Mosquitto)
- Broker runs on the RPi
- Flutter app subscribes to relevant junction topics based on GPS proximity
- Lightweight, low-latency — appropriate for real-time advisory

### 4. Supabase (PostgreSQL)
- RPi Python script inserts rows after each prediction cycle
- Key tables:
  - `junctions(id, name, lat, lng, osm_node_id)`
  - `signal_events(id, junction_id, phase, duration_predicted, duration_actual, timestamp)`
  - `queue_snapshots(id, junction_id, queue_length, clearance_time_est, timestamp)`
  - `advisory_logs(id, junction_id, advisory_type, speed_suggested, timestamp)`
  - `emissions_estimates(id, junction_id, vehicle_count, idle_time, co2_kg, nox_g, timestamp)`
- ChemE team member uses SQL queries directly on Supabase dashboard for emissions analysis

### 5. Flutter App
Four main screens:
1. **Speed Advisory HUD** — Real-time advisory (coast / proceed / stop), current signal phase, queue severity indicator, suggested speed
2. **Zonal Fluidity Heatmap** — Map overlay showing congestion zones using junction queue data
3. **Journey Analytics** — Historical trip data, estimated fuel/emissions saved
4. **Signal Timing Insights** — Per-junction phase prediction accuracy, historical timing patterns

Flutter subscribes to MQTT via `mqtt_client` package. GPS used to determine nearest junction. Supabase Flutter SDK used for analytics screens.

---

## Tech Stack Summary

| Layer | Technology |
|---|---|
| Edge hardware | Raspberry Pi (any model with WiFi) |
| Edge language | Python 3.x |
| ML model | XGBoost (scikit-learn wrapper) |
| Map data | OpenStreetMap via Overpass API |
| Messaging | MQTT (Mosquitto broker) |
| Mobile app | Flutter (Dart) |
| Backend/DB | Supabase (PostgreSQL) |
| MQTT Flutter pkg | `mqtt_client` |
| Supabase Flutter pkg | `supabase_flutter` |

---

## Key Design Decisions (and Why)

- **Supabase over Firebase**: PostgreSQL enables relational queries for emissions analysis. Firebase's NoSQL structure would make cross-table emissions calculations awkward. The ChemE team member can write SQL directly.
- **XGBoost over deep learning**: Runs efficiently on a single RPi without GPU. Fast inference, interpretable, works well on tabular data.
- **MQTT over REST polling**: Lower latency, push-based — appropriate for real-time traffic advisory. REST polling would introduce unacceptable lag.
- **Simulation on RPi**: No live city infrastructure access. The RPi simulates a smart junction using real coordinates from OSM and synthetic traffic patterns calibrated to Bengaluru conditions.
- **Queue length broadcast**: The critical differentiator. Signal timing alone is insufficient in dense traffic. Broadcasting queue length allows the app to advise coasting rather than accelerating into a backed-up intersection.

---

## What Has Been Done

- [x] Project ideation and direction finalized
- [x] Architecture designed
- [x] Formal project proposal document written (includes research objectives, scalability discussion)
- [ ] Codebase — not started yet

---

## What Needs to Be Built

### RPi Python Backend (`/rpi/`)
- `overpass_fetcher.py` — fetch junction coordinates for a bounding box (e.g., central Bengaluru)
- `traffic_simulator.py` — generate synthetic queue + timing data per junction
- `model_trainer.py` — train XGBoost on synthetic dataset, save model
- `inference_engine.py` — load model, run predictions per cycle
- `mqtt_publisher.py` — publish phase + queue payloads to MQTT topics
- `supabase_logger.py` — insert prediction + queue data into Supabase
- `main.py` — orchestrates all modules, runs event loop

### ML (`/model/`)
- `generate_dataset.py` — synthetic dataset generation
- `train.py` — XGBoost training + evaluation
- `model.ubj` — saved model artifact

### Flutter App (`/app/`)
- MQTT subscription service
- GPS + nearest junction logic
- HUD screen
- Heatmap screen
- Analytics screen
- Signal insights screen
- Supabase integration for historical data

### Database (`/supabase/`)
- SQL migration files for all tables
- Example emissions analysis queries (for ChemE documentation)

---

## Constraints

- **Single Raspberry Pi** — no distributed edge infrastructure. All simulation, inference, and MQTT brokering runs on one device.
- **No live traffic feeds** — data is simulated. OSM provides real coordinates; queue/timing data is synthetic but calibrated.
- **Flutter is the primary deliverable** — the RPi backend exists to feed the app.
- **Project must be research-worthy** — needs to demonstrate measurable outcomes (prediction accuracy, emissions delta, advisory effectiveness).

---

## Folder Structure (Suggested)

```
greensyncq/
├── rpi/
│   ├── overpass_fetcher.py
│   ├── traffic_simulator.py
│   ├── inference_engine.py
│   ├── mqtt_publisher.py
│   ├── supabase_logger.py
│   └── main.py
├── model/
│   ├── generate_dataset.py
│   ├── train.py
│   └── model.ubj
├── app/                  # Flutter project root
│   ├── lib/
│   │   ├── services/
│   │   │   ├── mqtt_service.dart
│   │   │   └── supabase_service.dart
│   │   └── screens/
│   │       ├── hud_screen.dart
│   │       ├── heatmap_screen.dart
│   │       ├── analytics_screen.dart
│   │       └── insights_screen.dart
│   └── pubspec.yaml
├── supabase/
│   ├── migrations/
│   └── queries/
└── CLAUDE.md             # ← this file
```

---

## Good First Tasks for Claude Code

1. **"Set up the RPi Python project structure and implement `overpass_fetcher.py` to pull junction coordinates for central Bengaluru using the Overpass API."**
2. **"Generate a synthetic training dataset for XGBoost: features = [queue_length, hour, minute, day_of_week, junction_id], target = phase_duration_remaining. Calibrate to Bengaluru peak hour patterns."**
3. **"Train an XGBoost regression model on the synthetic dataset and save it. Print MAE and RMSE."**
4. **"Write the Supabase SQL migrations for all five tables listed in the architecture."**
5. **"Scaffold the Flutter app with bottom navigation across the four screens and wire up the MQTT client service."**