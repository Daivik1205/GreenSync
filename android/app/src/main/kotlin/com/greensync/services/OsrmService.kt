package com.greensync.services

import com.google.gson.Gson
import com.greensync.models.LatLng
import com.google.gson.annotations.SerializedName
import com.greensync.models.Route
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

/**
 * Fetches up to 3 alternative routes from the public OSRM demo server
 * (or a self-hosted instance) using the Bengaluru OSM bounding box.
 *
 * Endpoint: GET /route/v1/driving/{lon1},{lat1};{lon2},{lat2}
 *           ?alternatives=3&steps=false&geometries=polyline&overview=full
 *
 * For production, replace OSRM_BASE_URL with a self-hosted OSRM instance
 * pre-loaded with the Karnataka OSM extract.
 */
class OsrmService(
    private val baseUrl: String = OSRM_BASE_URL,
) {
    companion object {
        private const val OSRM_BASE_URL = "https://router.project-osrm.org"
        private const val MAX_ALTERNATIVES = 3
    }

    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    /**
     * Returns up to 3 Route alternatives between [origin] and [destination].
     * Throws IOException on network failure.
     */
    suspend fun getRoutes(origin: LatLng, destination: LatLng): List<Route> =
        withContext(Dispatchers.IO) {
            val url = buildUrl(origin, destination)
            val request = Request.Builder().url(url).build()

            val body = client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) error("OSRM error: ${response.code}")
                response.body?.string() ?: error("Empty OSRM response")
            }

            val osrmResponse = gson.fromJson(body, OsrmResponse::class.java)
            if (osrmResponse.code != "Ok") error("OSRM code: ${osrmResponse.code}")

            osrmResponse.routes.mapIndexed { index, route ->
                Route(
                    id          = "route_alternative_$index",
                    waypoints   = listOf(origin, destination),
                    distanceKm  = route.distance / 1000.0,
                    durationMin = route.duration / 60.0,
                    summary     = route.legs.firstOrNull()?.summary ?: "Route ${index + 1}",
                    geometry    = decodePolyline(route.geometry),
                )
            }
        }

    private fun buildUrl(origin: LatLng, destination: LatLng): String {
        // OSRM uses lon,lat ordering
        val coords = "${origin.longitude},${origin.latitude};${destination.longitude},${destination.latitude}"
        return "$baseUrl/route/v1/driving/$coords" +
               "?alternatives=$MAX_ALTERNATIVES&steps=false&geometries=polyline&overview=full"
    }

    // ── Polyline decoder (Google encoded polyline format) ────────────────────

    private fun decodePolyline(encoded: String): List<LatLng> {
        val poly = mutableListOf<LatLng>()
        var index = 0
        val len = encoded.length
        var lat = 0
        var lng = 0

        while (index < len) {
            var b: Int
            var shift = 0
            var result = 0
            do {
                b = encoded[index++].code - 63
                result = result or (b and 0x1f shl shift)
                shift += 5
            } while (b >= 0x20)
            val dlat = if (result and 1 != 0) (result shr 1).inv() else result shr 1
            lat += dlat

            shift = 0; result = 0
            do {
                b = encoded[index++].code - 63
                result = result or (b and 0x1f shl shift)
                shift += 5
            } while (b >= 0x20)
            val dlng = if (result and 1 != 0) (result shr 1).inv() else result shr 1
            lng += dlng

            poly.add(LatLng(lat / 1e5, lng / 1e5))
        }
        return poly
    }

    // ── OSRM JSON models ─────────────────────────────────────────────────────

    private data class OsrmResponse(
        val code:   String,
        val routes: List<OsrmRoute> = emptyList(),
    )

    private data class OsrmRoute(
        val distance: Double,
        val duration: Double,
        val geometry: String,
        val legs:     List<OsrmLeg> = emptyList(),
    )

    private data class OsrmLeg(
        val summary: String,
    )
}
