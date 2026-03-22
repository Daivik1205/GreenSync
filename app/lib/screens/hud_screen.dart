// hud_screen.dart
// Speed Advisory HUD — main screen.
// Shows: real-time advisory (coast/proceed/stop), current signal phase,
// queue severity indicator, and suggested speed.

import 'package:flutter/material.dart';

class HudScreen extends StatefulWidget {
  const HudScreen({super.key});

  @override
  State<HudScreen> createState() => _HudScreenState();
}

class _HudScreenState extends State<HudScreen> {
  // TODO: inject MqttService, subscribe to nearest junction on GPS update

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Text('Speed Advisory HUD — coming soon'),
      ),
    );
  }
}
