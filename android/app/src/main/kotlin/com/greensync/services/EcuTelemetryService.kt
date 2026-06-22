package com.greensync.services

import android.app.Service
import android.car.Car
import android.car.hardware.CarPropertyValue
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import com.greensync.models.EcuTelemetryPayload
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID

/**
 * Reads vehicle ECU data via Android Automotive OS CarPropertyManager and
 * forwards it to MqttIntentService for publishing to the GreenSync backend.
 *
 * Properties accessed:
 *   VehiclePropertyIds.PERF_VEHICLE_SPEED  — real-time speed (m/s → km/h)
 *   VehiclePropertyIds.FUEL_LEVEL          — fuel level (litres; ICE vehicles)
 *   VehiclePropertyIds.EV_BATTERY_LEVEL    — state-of-charge (Wh; EV vehicles)
 *   VehiclePropertyIds.INFO_FUEL_CAPACITY   — capacity for normalising fuel_level to 0–1
 *   VehiclePropertyIds.INFO_EV_BATTERY_CAPACITY — capacity for normalising SoC
 *
 * On non-AAOS devices (phone-only testing), falls back to mock telemetry.
 *
 * Publishing interval: PUBLISH_INTERVAL_MS (default 5 seconds).
 */
class EcuTelemetryService : Service() {

    companion object {
        private const val TAG                = "EcuTelemetryService"
        private const val PUBLISH_INTERVAL_MS = 5_000L

        // CarPropertyManager property IDs (from android.car.VehiclePropertyIds)
        private const val PROP_SPEED         = 0x11600207   // PERF_VEHICLE_SPEED
        private const val PROP_FUEL_LEVEL    = 0x11600307   // FUEL_LEVEL
        private const val PROP_EV_BATTERY    = 0x11600309   // EV_BATTERY_LEVEL
        private const val PROP_FUEL_CAPACITY = 0x11600308   // INFO_FUEL_CAPACITY
        private const val PROP_EV_CAPACITY   = 0x11600310   // INFO_EV_BATTERY_CAPACITY

        private val USER_ID = "usr_${UUID.randomUUID().toString().take(8)}"
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var carPropertyManager: CarPropertyManager? = null
    private var isAaos = false

    override fun onCreate() {
        super.onCreate()
        tryInitCarPropertyManager()
        scope.launch { publishLoop() }
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ── Car property initialisation ───────────────────────────────────────────

    private fun tryInitCarPropertyManager() {
        if (!packageManager.hasSystemFeature("android.hardware.type.automotive")) {
            Log.i(TAG, "Not running on AAOS — using mock ECU telemetry")
            return
        }

        try {
            val car = Car.createCar(this)
            carPropertyManager = car.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
            isAaos = true
            Log.i(TAG, "CarPropertyManager initialised on AAOS")
        } catch (e: Exception) {
            Log.w(TAG, "CarPropertyManager init failed: ${e.message} — using mock")
        }
    }

    // ── Publish loop ──────────────────────────────────────────────────────────

    private suspend fun publishLoop() {
        while (true) {
            val payload = if (isAaos) readEcuTelemetry() else mockTelemetry()
            MqttIntentService.publishTelemetry(this, payload)
            delay(PUBLISH_INTERVAL_MS)
        }
    }

    private fun readEcuTelemetry(): EcuTelemetryPayload {
        val cpm = carPropertyManager!!

        val speedMs    = cpm.getFloatProperty(PROP_SPEED, 0)
        val speedKmh   = speedMs * 3.6

        val fuelLevel  = safeGetFloat(cpm, PROP_FUEL_LEVEL, 0)
        val fuelCap    = safeGetFloat(cpm, PROP_FUEL_CAPACITY, 0)
        val fuelFrac   = if (fuelCap > 0) fuelLevel / fuelCap else null

        val evLevel    = safeGetFloat(cpm, PROP_EV_BATTERY, 0)
        val evCap      = safeGetFloat(cpm, PROP_EV_CAPACITY, 0)
        val evFrac     = if (evCap > 0) evLevel / evCap else null

        return EcuTelemetryPayload(
            user_id    = USER_ID,
            speed_kmh  = speedKmh.toDouble(),
            fuel_level = fuelFrac?.toDouble(),
            battery_pct = evFrac?.toDouble(),
        )
    }

    private fun safeGetFloat(cpm: CarPropertyManager, propId: Int, areaId: Int): Float =
        try { cpm.getFloatProperty(propId, areaId) } catch (e: Exception) { -1f }

    private fun mockTelemetry(): EcuTelemetryPayload =
        EcuTelemetryPayload(
            user_id    = USER_ID,
            speed_kmh  = (20..60).random().toDouble(),
            fuel_level = 0.65,
            battery_pct = null,
        )
}
