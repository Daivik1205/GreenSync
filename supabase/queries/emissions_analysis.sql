-- emissions_analysis.sql — GreenSync V2
-- ChemE team queries for emissions and congestion impact analysis.
-- Run in Supabase SQL editor or connect via psql.

-- ── 1. Total CO₂ and NOₓ per junction (last 24 h) ────────────────────────────
select
    j.name                                   as junction,
    round(sum(e.co2_kg)::numeric, 3)         as total_co2_kg,
    round(sum(e.nox_g)::numeric, 2)          as total_nox_g,
    round(sum(e.pm25_ug)::numeric, 1)        as total_pm25_ug,
    sum(e.vehicle_count)                     as total_vehicles,
    round(avg(e.idle_time_s)::numeric, 1)    as avg_idle_time_s
from emissions_estimates e
join junctions j on j.id = e.junction_id
where e.recorded_at >= now() - interval '24 hours'
group by j.name
order by total_co2_kg desc;

-- ── 2. Emissions vs queue length correlation ───────────────────────────────────
-- Useful for validating that GreenSync routing reduces idle emissions.
select
    q.queue_length,
    round(avg(e.co2_kg)::numeric, 4)      as avg_co2_kg,
    round(avg(e.idle_time_s)::numeric, 1) as avg_idle_s,
    count(*)                               as samples
from queue_snapshots q
join emissions_estimates e on e.junction_id = q.junction_id
    and abs(extract(epoch from (e.recorded_at - q.recorded_at))) < 60
group by q.queue_length
order by q.queue_length;

-- ── 3. Hourly CO₂ trend (last 7 days) ────────────────────────────────────────
select
    date_trunc('hour', recorded_at) as hour,
    round(sum(co2_kg)::numeric, 3)  as co2_kg,
    sum(vehicle_count)              as vehicles
from emissions_estimates
where recorded_at >= now() - interval '7 days'
group by hour
order by hour;

-- ── 4. Vehicle mix contribution to emissions ───────────────────────────────────
-- vehicle_mix JSONB: {"ICE": 80, "EV": 20}
select
    j.name                                          as junction,
    round(avg((e.vehicle_mix->>'ICE')::numeric), 1) as avg_ice_pct,
    round(avg((e.vehicle_mix->>'EV')::numeric), 1)  as avg_ev_pct,
    round(sum(e.co2_kg)::numeric, 3)                as total_co2_kg
from emissions_estimates e
join junctions j on j.id = e.junction_id
where e.vehicle_mix is not null
  and e.recorded_at >= now() - interval '24 hours'
group by j.name
order by total_co2_kg desc;

-- ── 5. Intent-driven congestion shift (V2 key metric) ─────────────────────────
-- Compare emissions for routes that received high intent pressure vs. low.
-- Requires joining route_intents with emissions via junction proximity.
with intent_counts as (
    select
        selected_route_id,
        count(*) as selection_count,
        date_trunc('hour', received_at) as hour
    from route_intents
    where received_at >= now() - interval '24 hours'
    group by selected_route_id, hour
),
hourly_emissions as (
    select
        date_trunc('hour', recorded_at) as hour,
        sum(co2_kg)     as co2_kg,
        sum(nox_g)      as nox_g,
        sum(idle_time_s) as idle_s
    from emissions_estimates
    where recorded_at >= now() - interval '24 hours'
    group by hour
)
select
    h.hour,
    coalesce(sum(i.selection_count), 0) as total_intents,
    round(h.co2_kg::numeric, 3)         as co2_kg,
    round(h.nox_g::numeric, 2)          as nox_g,
    round(h.idle_s::numeric, 1)         as idle_s
from hourly_emissions h
left join intent_counts i on i.hour = h.hour
group by h.hour, h.co2_kg, h.nox_g, h.idle_s
order by h.hour;

-- ── 6. Busiest corridors (geospatial — requires PostGIS) ──────────────────────
select
    j.name,
    ST_AsText(j.geom)                         as location,
    sum(e.vehicle_count)                       as total_vehicles,
    round(sum(e.co2_kg)::numeric, 3)           as co2_kg
from emissions_estimates e
join junctions j on j.id = e.junction_id
where e.recorded_at >= now() - interval '24 hours'
  and ST_Within(
        j.geom,
        ST_MakeEnvelope(77.58, 12.96, 77.60, 12.97, 4326)   -- Bengaluru bbox
      )
group by j.name, j.geom
order by co2_kg desc
limit 10;
