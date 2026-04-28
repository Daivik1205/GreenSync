# routing_dashboard.py — GreenSync Phase 3
#
# Standalone MQTT subscriber dashboard.
# Run this in a SEPARATE terminal while main.py is running.
#
#   Terminal 1:  ./run.sh          (SUMO + main.py)
#   Terminal 2:  python routing_dashboard.py
#
# What it shows (refreshes every 2 s):
#   • Network snapshot  — total vehicles, active congested / slow / free roads
#   • Zone routing table — which zones to AVOID, which are CLEAR
#   • Top congested roads — ranked worst-first with speed + occupancy
#   • Signal phases      — current green/yellow/red state per traffic light
#   • Routing advice     — plain-language suggestions based on live data

import json
import os
import time
import threading
from collections import defaultdict
from datetime import datetime

from communication.subscriber import connect, subscribe_all_zones, subscribe_all_signals, parse_payload

# ── Display config ─────────────────────────────────────────────────────────────
REFRESH_HZ   = 0.5        # dashboard refresh rate (seconds)
W            = 88         # terminal width

# ── Shared state (updated by MQTT callbacks, read by display loop) ─────────────
_lock        = threading.Lock()
_zone_states: dict[str, dict] = {}    # zone_id → latest zone state payload
_signal_phases: dict[str, dict] = {}  # tl_id   → latest signal phase payload
_msg_count   = 0
_last_msg_at = None

# ── Event styling ──────────────────────────────────────────────────────────────
_ICON = {
    "free_flow":  "🟢",
    "slowdown":   "🟡",
    "congestion": "🔴",
    "unknown":    "⚪",
}
_RANK = {"congestion": 3, "slowdown": 2, "free_flow": 1, "unknown": 0}

_SIG_ICON = {
    "GREEN":  "🟢",
    "YELLOW": "🟡",
    "RED":    "🔴",
}


# ── MQTT callbacks ─────────────────────────────────────────────────────────────

def _on_message(client, userdata, msg):
    global _msg_count, _last_msg_at
    try:
        payload = parse_payload(msg)
        topic   = msg.topic

        with _lock:
            if "/rsu/" in topic:
                zone_id = topic.split("/")[2]
                _zone_states[zone_id] = payload
            elif "/signal/" in topic:
                tl_id = topic.split("/")[2]
                _signal_phases[tl_id] = payload
            _msg_count  += 1
            _last_msg_at = datetime.now()
    except Exception:
        pass


# ── Routing logic — derives advice from live zone states ──────────────────────

def _routing_advice(zone_states: dict) -> list[str]:
    """
    Simple rule-based routing advice derived from zone states.
    Will be replaced by GRU + LSH predictions in Phase 6.
    """
    avoid  = [zid for zid, z in zone_states.items() if z.get("event") == "congestion"]
    slow   = [zid for zid, z in zone_states.items() if z.get("event") == "slowdown"]
    clear  = [zid for zid, z in zone_states.items() if z.get("event") == "free_flow"]

    advice = []

    if avoid:
        advice.append(f"  🔴 AVOID  → {', '.join(sorted(avoid)[:5])}"
                      + (" …" if len(avoid) > 5 else ""))
    if slow:
        advice.append(f"  🟡 CAUTION → {', '.join(sorted(slow)[:5])}"
                      + (" …" if len(slow) > 5 else ""))
    if clear:
        advice.append(f"  🟢 CLEAR  → {', '.join(sorted(clear)[:5])}"
                      + (" …" if len(clear) > 5 else ""))

    if not advice:
        advice.append("  ⏳  Waiting for simulation data …")

    return advice


# ── Display ────────────────────────────────────────────────────────────────────

def _clear():
    os.system("clear")


def _bar(value: float, max_val: float = 100.0, width: int = 20) -> str:
    """Simple ASCII progress bar."""
    filled = int(width * min(value / max(max_val, 1), 1.0))
    return "█" * filled + "░" * (width - filled)


def _render(zones: dict, signals: dict, msg_count: int, last_msg):
    _clear()

    now      = datetime.now().strftime("%H:%M:%S")
    lag      = f"{(datetime.now() - last_msg).total_seconds():.1f}s ago" \
               if last_msg else "no data yet"

    # ── HEADER ────────────────────────────────────────────────────────────────
    print("━" * W)
    print(f"  GreenSync │ Routing Dashboard │ {now} │ "
          f"msgs: {msg_count} │ last: {lag}")
    print("━" * W)

    if not zones:
        print("\n  ⏳  No zone data received yet.")
        print("     Make sure main.py (SUMO simulation) is running.\n")
        print("━" * W)
        return

    # ── NETWORK SNAPSHOT ──────────────────────────────────────────────────────
    n_cong  = sum(1 for z in zones.values() if z.get("event") == "congestion")
    n_slow  = sum(1 for z in zones.values() if z.get("event") == "slowdown")
    n_free  = sum(1 for z in zones.values() if z.get("event") == "free_flow")
    n_unk   = len(zones) - n_cong - n_slow - n_free
    total_v = sum(z.get("vehicle_count", 0) for z in zones.values())

    print(f"\n  ▸ NETWORK SNAPSHOT   "
          f"🚗 {total_v} vehicles   "
          f"🔴 {n_cong} congested   "
          f"🟡 {n_slow} slow   "
          f"🟢 {n_free} free   "
          f"⚪ {n_unk} idle")

    # ── ZONE ROUTING TABLE ────────────────────────────────────────────────────
    print(f"\n  ▸ ZONE ROUTING TABLE  ({len(zones)} zones)\n")
    print(f"  {'Zone':<14} {'Event':<12} {'Vehicles':>8} {'Avg Speed':>10} {'Action'}")
    print("  " + "─" * (W - 2))

    sorted_zones = sorted(
        zones.items(),
        key=lambda kv: _RANK.get(kv[1].get("event", "unknown"), 0),
        reverse=True,
    )

    for zone_id, z in sorted_zones:
        event  = z.get("event", "unknown")
        icon   = _ICON.get(event, "⚪")
        count  = z.get("vehicle_count", 0)
        speed  = z.get("avg_speed", 0.0)
        spd_kh = round(speed * 3.6, 1) if speed else 0.0

        action = {
            "congestion": "⛔  AVOID — reroute around this zone",
            "slowdown":   "⚠️  CAUTION — expect delays",
            "free_flow":  "✅  CLEAR — preferred route",
            "unknown":    "   monitoring …",
        }.get(event, "")

        print(f"  {icon} {zone_id:<12}  {event:<12} {count:>7}   {spd_kh:>7.1f} km/h  {action}")

    # ── ROUTING ADVICE ────────────────────────────────────────────────────────
    print(f"\n  ▸ ROUTING ADVICE  (rule-based — GRU+LSH predictions in Phase 6)\n")
    for line in _routing_advice(zones):
        print(line)

    # ── SIGNAL PHASES ─────────────────────────────────────────────────────────
    if signals:
        print(f"\n  ▸ SIGNAL PHASES  ({len(signals)} junctions)\n")
        sig_cols = 4
        items    = sorted(signals.items())
        for i in range(0, min(len(items), 20), sig_cols):
            row = items[i:i + sig_cols]
            parts = []
            for tl_id, ph in row:
                label = ph.get("phase_label", "?")
                rem   = ph.get("duration_remaining", 0)
                icon  = _SIG_ICON.get(label, "⚪")
                parts.append(f"  {icon} {str(tl_id)[:16]:<16} {rem:>5.1f}s")
            print("".join(parts))
        if len(signals) > 20:
            print(f"  … +{len(signals) - 20} more junctions")

    print(f"\n{'━' * W}", flush=True)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    print("🔌 Connecting to MQTT broker (localhost:1883)…")
    client = connect(_on_message, client_id="greensyncq_routing_dashboard")
    subscribe_all_zones(client)
    subscribe_all_signals(client)
    client.loop_start()
    print("✅ Subscribed to greensyncq/rsu/+/state and greensyncq/signal/+/phase")
    print("   Waiting for simulation data … (start main.py in another terminal)\n")

    try:
        while True:
            with _lock:
                zones   = dict(_zone_states)
                signals = dict(_signal_phases)
                count   = _msg_count
                last    = _last_msg_at

            _render(zones, signals, count, last)
            time.sleep(REFRESH_HZ)

    except KeyboardInterrupt:
        print("\n\n  Dashboard stopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
