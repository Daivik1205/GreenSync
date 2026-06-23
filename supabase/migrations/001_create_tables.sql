-- 001_create_tables.sql — GreenSync V2 schema
-- Run via: supabase db push  OR  paste into Supabase SQL editor.

-- ── Extensions ────────────────────────────────────────────────────────────────
create extension if not exists "uuid-ossp";
create extension if not exists "postgis";

-- ── 1. Junctions ─────────────────────────────────────────────────────────────
create table if not exists junctions (
    id           uuid primary key default uuid_generate_v4(),
    name         text not null,
    lat          double precision not null,
    lng          double precision not null,
    osm_node_id  bigint unique,
    sumo_tl_id   text,
    geom         geometry(Point, 4326) generated always as
                     (ST_SetSRID(ST_Point(lng, lat), 4326)) stored,
    created_at   timestamptz default now()
);
create index if not exists junctions_geom_idx on junctions using gist(geom);

-- ── 2. Signal events ─────────────────────────────────────────────────────────
create table if not exists signal_events (
    id                  uuid primary key default uuid_generate_v4(),
    junction_id         uuid references junctions(id) on delete cascade,
    phase               text not null,
    duration_predicted  double precision,
    duration_actual     double precision,
    prediction_error    double precision generated always as
                            (abs(duration_actual - duration_predicted)) stored,
    source              text default 'sumo',
    recorded_at         timestamptz default now()
);
create index if not exists signal_events_junction_idx
    on signal_events(junction_id, recorded_at desc);

-- ── 3. Queue snapshots ────────────────────────────────────────────────────────
create table if not exists queue_snapshots (
    id                   uuid primary key default uuid_generate_v4(),
    junction_id          uuid references junctions(id) on delete cascade,
    queue_length         integer not null,
    halting_count        integer default 0,
    avg_speed_kmh        double precision,
    occupancy_pct        double precision,
    clearance_time_est   double precision,
    tomtom_current_speed double precision,
    recorded_at          timestamptz default now()
);
create index if not exists queue_snapshots_junction_idx
    on queue_snapshots(junction_id, recorded_at desc);

-- ── 4. Advisory log ───────────────────────────────────────────────────────────
create table if not exists advisory_logs (
    id               uuid primary key default uuid_generate_v4(),
    junction_id      uuid references junctions(id) on delete cascade,
    advisory_type    text not null check (advisory_type in ('STOP', 'COAST', 'PROCEED')),
    speed_suggested  integer,
    zone_event       text,
    signal_secs_left double precision,
    recorded_at      timestamptz default now()
);

-- ── 5. Emissions estimates (ChemE team) ───────────────────────────────────────
create table if not exists emissions_estimates (
    id             uuid primary key default uuid_generate_v4(),
    junction_id    uuid references junctions(id) on delete cascade,
    vehicle_count  integer not null,
    idle_time_s    double precision,
    co2_kg         double precision,
    nox_g          double precision,
    pm25_ug        double precision,
    vehicle_mix    jsonb,
    recorded_at    timestamptz default now()
);
create index if not exists emissions_junction_idx
    on emissions_estimates(junction_id, recorded_at desc);

-- ── 6. User route intents (V2) ────────────────────────────────────────────────
create table if not exists route_intents (
    id                  uuid primary key default uuid_generate_v4(),
    user_id             text not null,
    selected_route_id   text not null,
    waypoints           jsonb not null,
    timestamp_eta       bigint,
    vehicle_type        text default 'ICE',
    speed_kmh           double precision,
    fuel_level          double precision,
    received_at         timestamptz default now()
);
create index if not exists route_intents_route_idx
    on route_intents(selected_route_id, received_at desc);

-- ── 7. ECU telemetry (V2) ─────────────────────────────────────────────────────
create table if not exists ecu_telemetry (
    id          uuid primary key default uuid_generate_v4(),
    user_id     text not null,
    speed_kmh   double precision not null,
    fuel_level  double precision,
    battery_pct double precision,
    recorded_at timestamptz default now()
);
create index if not exists ecu_telemetry_user_idx
    on ecu_telemetry(user_id, recorded_at desc);

-- ── Row-level security ────────────────────────────────────────────────────────
alter table junctions           enable row level security;
alter table signal_events       enable row level security;
alter table queue_snapshots     enable row level security;
alter table advisory_logs       enable row level security;
alter table emissions_estimates enable row level security;
alter table route_intents       enable row level security;
alter table ecu_telemetry       enable row level security;

create policy "public read junctions"
    on junctions for select using (true);

create policy "public read emissions"
    on emissions_estimates for select using (true);
