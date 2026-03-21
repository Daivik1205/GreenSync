// insights_screen.dart
// Signal Timing Insights — per-junction phase prediction accuracy
// and historical timing patterns.
// Data source: Supabase signal_events table.

import 'package:flutter/material.dart';

class InsightsScreen extends StatefulWidget {
  const InsightsScreen({super.key});

  @override
  State<InsightsScreen> createState() => _InsightsScreenState();
}

class _InsightsScreenState extends State<InsightsScreen> {
  // TODO: fetch signal_events per junction, compute predicted vs actual delta

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Text('Signal Timing Insights — coming soon'),
      ),
    );
  }
}
