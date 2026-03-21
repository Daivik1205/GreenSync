// mqtt_service.dart
// Manages MQTT subscription to GreenSync-Q broker.
// Subscribes to junction topics based on GPS proximity.
// Topics:
//   greensyncq/signal/{junction_id}/phase
//   greensyncq/signal/{junction_id}/queue

import 'package:mqtt_client/mqtt_client.dart';
import 'package:mqtt_client/mqtt_server_client.dart';

class MqttService {
  MqttServerClient? _client;

  // TODO: make configurable via env / build config
  static const String _brokerHost = '192.168.1.100';
  static const int _brokerPort = 1883;
  static const String _clientId = 'greensyncq_app';

  Future<void> connect() async {
    // TODO: initialise client, set up callbacks, connect to broker
  }

  void subscribeToJunction(String junctionId) {
    // Subscribe to phase + queue topics for this junction
  }

  void unsubscribeFromJunction(String junctionId) {
    // Unsubscribe when junction is no longer nearby
  }

  Stream<Map<String, dynamic>> get phaseUpdates {
    // TODO: return stream of parsed phase payloads
    throw UnimplementedError();
  }

  Stream<Map<String, dynamic>> get queueUpdates {
    // TODO: return stream of parsed queue payloads
    throw UnimplementedError();
  }

  void disconnect() {
    _client?.disconnect();
  }
}
