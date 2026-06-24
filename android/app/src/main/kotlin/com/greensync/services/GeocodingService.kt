package com.greensync.services

import com.google.gson.Gson
import com.google.gson.annotations.SerializedName
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/**
 * Forward-geocodes a free-text query into map locations using the public
 * Nominatim (OpenStreetMap) search API — the same OSM data the osmdroid map
 * renders. This lets the search bar find *anything* on the map (addresses,
 * landmarks, businesses, neighbourhoods) rather than a fixed catalog.
 *
 * Results are biased toward the Bengaluru viewbox but not restricted to it,
 * so a query that resolves elsewhere still returns something useful.
 *
 * Endpoint: GET /search?q={query}&format=jsonv2&addressdetails=1
 *               &limit={n}&countrycodes=in&viewbox={blr}&bounded=0
 */
class GeocodingService(
    private val baseUrl: String = NOMINATIM_BASE_URL,
) {
    companion object {
        private const val NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org"
        private const val MAX_RESULTS = 8

        // left-lon, top-lat, right-lon, bottom-lat — greater Bengaluru
        private const val BLR_VIEWBOX = "77.30,13.30,77.90,12.70"

        // Nominatim's usage policy requires an identifying User-Agent.
        private const val USER_AGENT = "GreenSync-Q/1.0 (greensync traffic demo)"

        private fun emojiFor(type: String?, category: String?): String = when (category) {
            "amenity" -> when (type) {
                "restaurant", "cafe", "fast_food" -> "🍽️"
                "hospital", "clinic", "doctors", "pharmacy" -> "🏥"
                "school", "college", "university" -> "🎓"
                "bank", "atm" -> "🏦"
                "fuel" -> "⛽"
                "place_of_worship" -> "🛕"
                "police" -> "👮"
                else -> "📍"
            }
            "shop" -> "🛍️"
            "tourism" -> "🏛️"
            "leisure" -> "🌿"
            "railway", "public_transport" -> "🚉"
            "aeroway" -> "✈️"
            "highway" -> "🛣️"
            "place" -> "📌"
            else -> "📍"
        }
    }

    /** A resolved map location. */
    data class Result(
        val name: String,
        val area: String,
        val emoji: String,
        val lat: Double,
        val lng: Double,
    )

    private val client = OkHttpClient.Builder()
        .connectTimeout(12, TimeUnit.SECONDS)
        .readTimeout(12, TimeUnit.SECONDS)
        .build()

    private val gson = Gson()

    /**
     * Returns up to [MAX_RESULTS] map locations matching [query].
     * Returns an empty list on any failure so the UI can fall back gracefully.
     */
    suspend fun search(query: String): List<Result> = withContext(Dispatchers.IO) {
        val q = query.trim()
        if (q.isBlank()) return@withContext emptyList()

        try {
            val url = "$baseUrl/search" +
                "?q=${URLEncoder.encode(q, "UTF-8")}" +
                "&format=jsonv2&addressdetails=1" +
                "&limit=$MAX_RESULTS&countrycodes=in" +
                "&viewbox=$BLR_VIEWBOX&bounded=0"

            val request = Request.Builder()
                .url(url)
                .header("User-Agent", USER_AGENT)
                .header("Accept-Language", "en")
                .build()

            val body = client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) return@withContext emptyList()
                response.body?.string() ?: return@withContext emptyList()
            }

            val raw = gson.fromJson(body, Array<NominatimPlace>::class.java) ?: return@withContext emptyList()
            raw.mapNotNull { it.toResult() }
        } catch (e: Exception) {
            emptyList()
        }
    }

    private fun NominatimPlace.toResult(): Result? {
        val latD = lat?.toDoubleOrNull() ?: return null
        val lngD = lon?.toDoubleOrNull() ?: return null

        // Primary label: explicit name, else first segment of display_name.
        val segments = displayName?.split(",")?.map { it.trim() }?.filter { it.isNotEmpty() }.orEmpty()
        val label = name?.takeIf { it.isNotBlank() } ?: segments.firstOrNull() ?: "Location"

        // Area: a useful locality hint from the address, else the next display segment.
        val areaHint = listOfNotNull(
            address?.suburb,
            address?.neighbourhood,
            address?.cityDistrict,
            address?.city,
            address?.town,
            address?.county,
        ).firstOrNull { it.isNotBlank() && !it.equals(label, ignoreCase = true) }
            ?: segments.getOrNull(1)
            ?: "Bengaluru"

        return Result(
            name  = label,
            area  = areaHint,
            emoji = emojiFor(type, category),
            lat   = latD,
            lng   = lngD,
        )
    }

    // ── Nominatim JSON models ────────────────────────────────────────────────

    private data class NominatimPlace(
        @SerializedName("display_name") val displayName: String? = null,
        val name:     String? = null,
        val lat:      String? = null,
        val lon:      String? = null,
        val type:     String? = null,
        val category: String? = null,
        val address:  NominatimAddress? = null,
    )

    private data class NominatimAddress(
        val suburb:       String? = null,
        val neighbourhood: String? = null,
        @SerializedName("city_district") val cityDistrict: String? = null,
        val city:         String? = null,
        val town:         String? = null,
        val county:       String? = null,
    )
}
