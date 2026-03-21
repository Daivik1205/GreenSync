# supabase_logger.py
# Inserts prediction and queue data into Supabase (PostgreSQL) after each cycle.
# Tables: signal_events, queue_snapshots, advisory_logs, emissions_estimates

SUPABASE_URL = ""   # set via env var SUPABASE_URL
SUPABASE_KEY = ""   # set via env var SUPABASE_KEY


def get_client():
    """
    Initialise and return Supabase client using env vars.
    """
    pass


def log_signal_event(client, junction_id: str, phase: str,
                     duration_predicted: float, timestamp):
    pass


def log_queue_snapshot(client, junction_id: str, queue_length: int,
                       clearance_time_est: float, timestamp):
    pass


def log_advisory(client, junction_id: str, advisory_type: str,
                 speed_suggested: float, timestamp):
    pass


def log_emissions(client, junction_id: str, vehicle_count: int,
                  idle_time: float, co2_kg: float, nox_g: float, timestamp):
    pass
