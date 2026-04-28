# subscriber.py — Phase 3
# MQTT subscriber with paho-mqtt v2 compatibility.
# Used by the routing dashboard and any downstream consumer.

import json
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT  = 1883


def connect(on_message_callback,
            host: str = BROKER_HOST,
            port: int = BROKER_PORT,
            client_id: str = "greensyncq_subscriber") -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )
    client.on_message = on_message_callback
    client.connect(host, port)
    return client


def subscribe_all_zones(client: mqtt.Client):
    client.subscribe("greensyncq/rsu/+/state", qos=1)


def subscribe_all_signals(client: mqtt.Client):
    client.subscribe("greensyncq/signal/+/phase", qos=1)


def subscribe_routing(client: mqtt.Client):
    client.subscribe("greensyncq/routing/+", qos=1)


def parse_payload(msg) -> dict:
    return json.loads(msg.payload.decode())
