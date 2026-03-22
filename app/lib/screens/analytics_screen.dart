// analytics_screen.dart
// Journey Analytics — historical trip data, estimated fuel/emissions saved.
// Data source: Supabase advisory_logs + emissions_estimates tables.

import 'package:flutter/material.dart';

class AnalyticsScreen extends StatefulWidget {
  const AnalyticsScreen({super.key});

  @override
  State<AnalyticsScreen> createState() => _AnalyticsScreenState();
}

class _AnalyticsScreenState extends State<AnalyticsScreen> {
  // TODO: fetch from SupabaseService, display trip history and emissions summary

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      body: Center(
        child: Text('Journey Analytics — coming soon'),
      ),
    );
  }
}
