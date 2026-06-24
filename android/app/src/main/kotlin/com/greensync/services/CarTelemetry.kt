package com.greensync.services

import android.car.Car
import android.car.hardware.property.CarPropertyManager
import android.content.Context
import android.util.Log

/**
 * Thin best-effort reader for Android Automotive ECU properties, shared by the
 * vehicle dashboard. Mirrors the property IDs used by [EcuTelemetryService].
 *
 * On a plain phone [available] is false and all reads return null, so callers
 * fall back to simulated values.
 */
class CarTelemetry(context: Context) {

    companion object {
        private const val TAG = "CarTelemetry"
        private const val PROP_SPEED         = 0x11600207   // PERF_VEHICLE_SPEED (m/s)
        private const val PROP_FUEL_LEVEL    = 0x11600307   // FUEL_LEVEL
        private const val PROP_EV_BATTERY    = 0x11600309   // EV_BATTERY_LEVEL
        private const val PROP_FUEL_CAPACITY = 0x11600308   // INFO_FUEL_CAPACITY
        private const val PROP_EV_CAPACITY   = 0x11600310   // INFO_EV_BATTERY_CAPACITY
    }

    private var cpm: CarPropertyManager? = null
    val available: Boolean

    init {
        var ok = false
        if (context.packageManager.hasSystemFeature("android.hardware.type.automotive")) {
            try {
                val car = Car.createCar(context)
                cpm = car.getCarManager(Car.PROPERTY_SERVICE) as CarPropertyManager
                ok = cpm != null
            } catch (e: Exception) {
                Log.w(TAG, "CarPropertyManager init failed: ${e.message}")
            }
        }
        available = ok
    }

    /** Live speed in km/h, or null if unavailable. */
    fun speedKmh(): Double? = get(PROP_SPEED)?.let { it * 3.6 }

    /** Fuel level as a 0–1 fraction of capacity, or null. */
    fun fuelPct(): Float? {
        val level = get(PROP_FUEL_LEVEL) ?: return null
        val cap   = get(PROP_FUEL_CAPACITY) ?: return null
        return if (cap > 0) level / cap else null
    }

    /** EV state-of-charge as a 0–1 fraction, or null. */
    fun batteryPct(): Float? {
        val level = get(PROP_EV_BATTERY) ?: return null
        val cap   = get(PROP_EV_CAPACITY) ?: return null
        return if (cap > 0) level / cap else null
    }

    private fun get(propId: Int): Float? =
        try { cpm?.getFloatProperty(propId, 0) } catch (e: Exception) { null }
}
