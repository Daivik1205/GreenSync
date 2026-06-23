package com.greensync.viewmodels

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.google.android.gms.maps.model.LatLng
import com.greensync.models.IntentPayload
import com.greensync.models.Route
import com.greensync.models.VehicleType
import com.greensync.services.MqttIntentService
import com.greensync.services.OsrmService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import java.util.UUID

sealed class RouteUiState {
    object Idle       : RouteUiState()
    object Loading    : RouteUiState()
    data class Success(val routes: List<Route>) : RouteUiState()
    data class Error(val message: String)       : RouteUiState()
}

class RouteViewModel(application: Application) : AndroidViewModel(application) {

    private val osrmService = OsrmService()
    private val userId      = "usr_${UUID.randomUUID().toString().take(8)}"

    private val _uiState = MutableStateFlow<RouteUiState>(RouteUiState.Idle)
    val uiState: StateFlow<RouteUiState> = _uiState

    private val _selectedRoute = MutableStateFlow<Route?>(null)
    val selectedRoute: StateFlow<Route?> = _selectedRoute

    var vehicleType: VehicleType = VehicleType.ICE

    // ── Route fetching ────────────────────────────────────────────────────────

    fun fetchRoutes(origin: LatLng, destination: LatLng) {
        _uiState.value = RouteUiState.Loading
        viewModelScope.launch {
            try {
                val routes = osrmService.getRoutes(origin, destination)
                _uiState.value = RouteUiState.Success(routes)
            } catch (e: Exception) {
                _uiState.value = RouteUiState.Error("Route fetch failed: ${e.message}")
            }
        }
    }

    // ── Intent publishing ─────────────────────────────────────────────────────

    /**
     * Called when the user taps a route card.
     * Immediately publishes the intent to the MQTT broker so the backend
     * can adjust edge weights before congestion materialises.
     */
    fun selectRoute(route: Route, currentSpeedKmh: Double? = null, fuelLevel: Double? = null) {
        _selectedRoute.value = route

        val payload = IntentPayload(
            user_id           = userId,
            selected_route_id = route.id,
            waypoints         = route.waypoints.map { listOf(it.latitude, it.longitude) },
            timestamp_eta     = System.currentTimeMillis() / 1000 +
                                (route.durationMin * 60).toLong(),
            vehicle_type      = vehicleType.name,
            speed_kmh         = currentSpeedKmh,
            fuel_level        = fuelLevel,
        )

        MqttIntentService.publishIntent(getApplication(), payload)
    }
}
