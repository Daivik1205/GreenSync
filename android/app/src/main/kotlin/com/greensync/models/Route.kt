package com.greensync.models

data class Route(
    val id:           String,            // "route_alternative_0/1/2"
    val waypoints:    List<LatLng>,
    val distanceKm:   Double,
    val durationMin:  Double,
    val summary:      String,            // e.g. "via Outer Ring Road"
    val geometry:     List<LatLng>,      // decoded polyline for map rendering
)

data class IntentPayload(
    val user_id:           String,
    val selected_route_id: String,
    val waypoints:         List<List<Double>>,   // [[lat, lon], ...]
    val timestamp_eta:     Long,
    val vehicle_type:      String = "ICE",
    val speed_kmh:         Double? = null,
    val fuel_level:        Double? = null,
)

data class EcuTelemetryPayload(
    val user_id:     String,
    val speed_kmh:   Double,
    val fuel_level:  Double?,
    val battery_pct: Double?,
)

enum class VehicleType { ICE, EV }
