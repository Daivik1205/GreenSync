// supabase_service.dart
// Fetches historical data from Supabase for analytics and insights screens.

import 'package:supabase_flutter/supabase_flutter.dart';

class SupabaseService {
  final _client = Supabase.instance.client;

  Future<List<Map<String, dynamic>>> getJunctions() async {
    // TODO: fetch all junctions
    throw UnimplementedError();
  }

  Future<List<Map<String, dynamic>>> getQueueHistory(String junctionId) async {
    // TODO: fetch queue_snapshots for a junction, ordered by timestamp desc
    throw UnimplementedError();
  }

  Future<List<Map<String, dynamic>>> getAdvisoryLog({int limit = 50}) async {
    // TODO: fetch recent advisory_logs
    throw UnimplementedError();
  }

  Future<Map<String, dynamic>> getEmissionsSummary() async {
    // TODO: aggregate emissions_estimates — total co2_kg, nox_g saved
    throw UnimplementedError();
  }

  Future<List<Map<String, dynamic>>> getSignalAccuracy(String junctionId) async {
    // TODO: fetch signal_events to compare duration_predicted vs duration_actual
    throw UnimplementedError();
  }
}
