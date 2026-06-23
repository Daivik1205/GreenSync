package com.greensync.screens

import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.CarText
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import com.google.android.gms.maps.model.LatLng
import com.greensync.models.IntentPayload
import com.greensync.models.Route
import com.greensync.services.MqttIntentService
import com.greensync.services.OsrmService
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Android Auto Car App Library screen — rendered on the DHU display.
 *
 * Shows a ListTemplate with 3 route alternatives (fetched from OSRM).
 * Selecting a row:
 *   1. Publishes MQTT intent payload.
 *   2. Pushes HUDCarScreen onto the screen stack.
 *
 * Car App Library constrains rendering to safety-compliant templates —
 * no arbitrary Views. ListTemplate is appropriate for route selection.
 */
class RouteSelectionCarScreen(carContext: CarContext) : Screen(carContext) {

    // Bengaluru corridor: Yelahanka → Mysore Road
    private val ORIGIN      = LatLng(13.1007, 77.5963)
    private val DESTINATION = LatLng(12.9121, 77.5590)

    private val osrmService = OsrmService()
    private val scope       = CoroutineScope(Dispatchers.Main)
    private val userId      = "usr_${UUID.randomUUID().toString().take(8)}"

    private var routes: List<Route> = emptyList()
    private var isLoading = true
    private var errorMsg: String? = null

    init {
        fetchRoutes()
    }

    override fun onGetTemplate(): Template {
        if (isLoading) {
            return ListTemplate.Builder()
                .setTitle("GreenSync — Loading routes…")
                .setLoading(true)
                .setHeaderAction(Action.BACK)
                .build()
        }

        if (errorMsg != null) {
            return ListTemplate.Builder()
                .setTitle("GreenSync")
                .setSingleList(
                    ItemList.Builder()
                        .addItem(Row.Builder().setTitle(errorMsg!!).build())
                        .build()
                )
                .setHeaderAction(Action.BACK)
                .build()
        }

        val listBuilder = ItemList.Builder()
        routes.forEachIndexed { i, route ->
            listBuilder.addItem(
                Row.Builder()
                    .setTitle("Route ${i + 1}  •  ${route.summary}")
                    .addText("%.1f km  •  %.0f min".format(route.distanceKm, route.durationMin))
                    .setOnClickListener { onRouteSelected(route) }
                    .build()
            )
        }

        return ListTemplate.Builder()
            .setTitle("GreenSync — Choose a route")
            .setSingleList(listBuilder.build())
            .setHeaderAction(Action.BACK)
            .build()
    }

    // ── Route fetching ────────────────────────────────────────────────────────

    private fun fetchRoutes() {
        scope.launch {
            try {
                routes    = osrmService.getRoutes(ORIGIN, DESTINATION)
                isLoading = false
            } catch (e: Exception) {
                isLoading = false
                errorMsg  = "Route fetch failed: ${e.message}"
            }
            invalidate()   // request Car App Library re-render
        }
    }

    // ── Selection ─────────────────────────────────────────────────────────────

    private fun onRouteSelected(route: Route) {
        val payload = IntentPayload(
            user_id           = userId,
            selected_route_id = route.id,
            waypoints         = route.waypoints.map { listOf(it.latitude, it.longitude) },
            timestamp_eta     = System.currentTimeMillis() / 1000 + (route.durationMin * 60).toLong(),
            vehicle_type      = "ICE",
        )
        MqttIntentService.publishIntent(carContext, payload)

        // Navigate to HUD screen on the DHU
        screenManager.push(HUDCarScreen(carContext, route))
    }
}
