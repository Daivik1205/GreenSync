# subscriber.py — Phase 3
# MQTT subscriber. Flutter app and backend components subscribe here.
# Topic subscription helpers for zone state and signal phase updates.

import json
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883


def connect(on_message_callback, host: str = BROKER_HOST, port: int = BROKER_PORT) -> mqtt.Client:
    client = mqtt.Client(client_id="greensyncq_subscriber")
    client.on_message = on_message_callback
    client.connect(host, port)
    return client


def subscribe_zone(client: mqtt.Client, zone_id: str):
    client.subscribe(f"greensyncq/rsu/{zone_id}/state", qos=1)


def subscribe_all_zones(client: mqtt.Client):
    client.subscribe("greensyncq/rsu/+/state", qos=1)


def subscribe_signal(client: mqtt.Client, tl_id: str):
    client.subscribe(f"greensyncq/signal/{tl_id}/phase", qos=1)


def parse_payload(msg) -> dict:
    return json.loads(msg.payload.decode())
