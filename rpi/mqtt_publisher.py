# mqtt_publisher.py
# Publishes signal phase and queue data to MQTT broker (Mosquitto).
# Topics:
#   greensyncq/signal/{junction_id}/phase  -> { phase, duration_remaining }
#   greensyncq/signal/{junction_id}/queue  -> { queue_length, estimated_clearance_time }

BROKER_HOST = "localhost"
BROKER_PORT = 1883


def connect(host: str = BROKER_HOST, port: int = BROKER_PORT):
    """
    Connect to the Mosquitto MQTT broker.
    Returns: mqtt client instance
    """
    pass


def publish_phase(client, junction_id: str, phase: str, duration_remaining: int):
    """
    Publish signal phase payload for a junction.
    """
    pass


def publish_queue(client, junction_id: str, queue_length: int, clearance_time: float):
    """
    Publish queue length payload for a junction.
    """
    pass


def disconnect(client):
    pass
