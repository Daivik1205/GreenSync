# intent_aggregator.py — Phase A backend: User route intent ingestion
#
# Subscribes to greensync/user/intent (MQTT) and aggregates routing choices
# from all connected Kotlin clients. The RouteIntentStore exposes per-route
# selection counts, which HybridDigitalTwin uses to penalise edge weights
# BEFORE physical congestion materialises.
#
# MQTT payload schema (published by Android client):
# {
#   "user_id":           "usr_9921",
#   "selected_route_id": "route_alternative_2",
#   "waypoints":         [[12.9601, 77.5813], ...],
#   "timestamp_eta":     1718103600,
#   "vehicle_type":      "ICE" | "EV",
#   "speed_kmh":         42.5,       # from CarPropertyManager (optional)
#   "fuel_level":        0.73         # 0–1 fraction (optional)
# }

import json
import threading
import time
import logging
from collections import defaultdict
from dataclasses import dataclass, field

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

BROKER_HOST    = "localhost"
BROKER_PORT    = 1883
INTENT_TOPIC   = "greensync/user/intent"
TELEMETRY_TOPIC = "greensync/ecu/telemetry"

# Window for intent expiry — selections older than this are discounted
INTENT_TTL_SECONDS = 1800   # 30 minutes


@dataclass
class UserIntent:
    user_id:           str
    selected_route_id: str
    waypoints:         list[tuple[float, float]]
    timestamp_eta:     int
    vehicle_type:      str = "ICE"
    speed_kmh:         float | None = None
    fuel_level:        float | None = None
    received_at:       float = field(default_factory=time.time)


@dataclass
class EcuTelemetry:
    user_id:      str
    speed_kmh:    float
    fuel_level:   float | None
    battery_pct:  float | None
    received_at:  float = field(default_factory=time.time)


class RouteIntentStore:
    """
    Thread-safe store for live route intents.

    Key concept: if N users select "route_alternative_2", the twin
    preemptively penalises that route's edges by N * INTENT_WEIGHT.
    """

    INTENT_WEIGHT = 0.001   # congestion penalty per additional user on a route

    def __init__(self):
        self._intents: dict[str, UserIntent] = {}   # user_id → latest intent
        self._telemetry: dict[str, EcuTelemetry] = {}
        self._lock = threading.Lock()

    def record_intent(self, intent: UserIntent):
        with self._lock:
            self._intents[intent.user_id] = intent
        logger.debug("Intent recorded: %s → %s", intent.user_id, intent.selected_route_id)

    def record_telemetry(self, telemetry: EcuTelemetry):
        with self._lock:
            self._telemetry[telemetry.user_id] = telemetry

    def route_selection_counts(self) -> dict[str, int]:
        """Returns {route_id: count} for non-expired intents."""
        cutoff = time.time() - INTENT_TTL_SECONDS
        counts: dict[str, int] = defaultdict(int)
        with self._lock:
            for intent in self._intents.values():
                if intent.received_at >= cutoff:
                    counts[intent.selected_route_id] += 1
        return dict(counts)

    def route_pressure_factor(self, route_id: str) -> float:
        """
        Returns an additive edge-weight penalty for a given route based on
        how many users have selected it relative to all active intents.

        Returns 0.0 when no intents; proportional congestion share otherwise.
        """
        counts = self.route_selection_counts()
        total  = sum(counts.values())
        if total == 0:
            return 0.0
        count  = counts.get(route_id, 0)
        return (count / total) * self.INTENT_WEIGHT * total

    def active_waypoints(self) -> list[list[tuple[float, float]]]:
        """All active (non-expired) waypoint sequences — for SUMO shadow injection."""
        cutoff = time.time() - INTENT_TTL_SECONDS
        with self._lock:
            return [i.waypoints for i in self._intents.values() if i.received_at >= cutoff]

    def latest_telemetry(self) -> list[EcuTelemetry]:
        with self._lock:
            return list(self._telemetry.values())

    def stats(self) -> dict:
        counts = self.route_selection_counts()
        return {
            "active_intents": sum(counts.values()),
            "route_counts":   counts,
            "active_users_with_telemetry": len(self._telemetry),
        }


class IntentAggregator:
    """
    MQTT subscriber that populates a RouteIntentStore from live Kotlin clients.
    Runs in a background thread via paho loop_start().
    """

    def __init__(self, store: RouteIntentStore,
                 broker_host: str = BROKER_HOST,
                 broker_port: int = BROKER_PORT):
        self.store       = store
        self._client     = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="greensync_intent_aggregator",
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._broker_host = broker_host
        self._broker_port = broker_port

    def start(self):
        self._client.connect(self._broker_host, self._broker_port)
        self._client.loop_start()
        logger.info("IntentAggregator connected to %s:%d", self._broker_host, self._broker_port)

    def stop(self):
        self._client.loop_stop()
        self._client.disconnect()

    # ── MQTT callbacks ────────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            client.subscribe(INTENT_TOPIC,    qos=1)
            client.subscribe(TELEMETRY_TOPIC, qos=1)
            logger.info("Subscribed to %s and %s", INTENT_TOPIC, TELEMETRY_TOPIC)
        else:
            logger.error("MQTT connect failed: reason_code=%s", reason_code)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage):
        try:
            payload = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Bad MQTT payload on %s: %s", msg.topic, exc)
            return

        if msg.topic == INTENT_TOPIC:
            self._handle_intent(payload)
        elif msg.topic == TELEMETRY_TOPIC:
            self._handle_telemetry(payload)

    def _handle_intent(self, payload: dict):
        try:
            raw_wps = payload.get("waypoints", [])
            intent = UserIntent(
                user_id           = str(payload["user_id"]),
                selected_route_id = str(payload["selected_route_id"]),
                waypoints         = [(float(p[0]), float(p[1])) for p in raw_wps],
                timestamp_eta     = int(payload.get("timestamp_eta", 0)),
                vehicle_type      = payload.get("vehicle_type", "ICE"),
                speed_kmh         = payload.get("speed_kmh"),
                fuel_level        = payload.get("fuel_level"),
            )
            self.store.record_intent(intent)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning("Malformed intent payload: %s — %s", payload, exc)

    def _handle_telemetry(self, payload: dict):
        try:
            telemetry = EcuTelemetry(
                user_id     = str(payload["user_id"]),
                speed_kmh   = float(payload.get("speed_kmh", 0)),
                fuel_level  = payload.get("fuel_level"),
                battery_pct = payload.get("battery_pct"),
            )
            self.store.record_telemetry(telemetry)
        except (KeyError, ValueError) as exc:
            logger.warning("Malformed telemetry payload: %s — %s", payload, exc)
