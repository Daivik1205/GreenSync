// heatmap_screen.dart
// Zonal Fluidity Heatmap — map overlay showing congestion zones
// using live queue data from MQTT per junction.

import 'package:flutter/material.dart';

class HeatmapScreen extends StatefulWidget {
  const HeatmapScreen({super.key});

  @override
  State<HeatmapScreen> createState() => _HeatmapScreenState();
}

class _HeatmapScreenState extends State<HeatmapScreen> {
  // TODO: GoogleMap widget with heatmap overlay driven by queue_length per junction

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Text('Zonal Fluidity Heatmap — coming soon'),
      ),
    );
  }
}
