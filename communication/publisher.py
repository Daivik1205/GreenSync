# publisher.py — Phase 3
# MQTT publisher. RSU zone states and signal events are published here.
# Inspired by V2X communication architecture (low-latency pub/sub).
#
# Topics:
#   greensyncq/rsu/{zone_id}/state      -> ZoneState payload
#   greensyncq/signal/{tl_id}/phase     -> signal phase payload
#   greensyncq/routing/{vehicle_id}     -> new route for a vehicle

import json
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883


def connect(host: str = BROKER_HOST, port: int = BROKER_PORT) -> mqtt.Client:
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id="greensyncq_publisher",
    )
    client.connect(host, port)
    client.loop_start()
    return client


def publish_zone_state(client: mqtt.Client, zone_state: dict):
    topic = f"greensyncq/rsu/{zone_state['zone_id']}/state"
    client.publish(topic, json.dumps(zone_state), qos=1)


def publish_signal_phase(client: mqtt.Client, tl_id: str, payload: dict):
    topic = f"greensyncq/signal/{tl_id}/phase"
    client.publish(topic, json.dumps(payload), qos=1)


def publish_route(client: mqtt.Client, vehicle_id: str, new_edges: list[str]):
    topic = f"greensyncq/routing/{vehicle_id}"
    client.publish(topic, json.dumps({"edges": new_edges}), qos=1)


def disconnect(client: mqtt.Client):
    client.loop_stop()
    client.disconnect()
