package com.greensync.screens

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.Looper
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.ActionStrip
import androidx.car.app.model.ItemList
import androidx.car.app.model.ListTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlin.random.Random

/**
 * Android Auto vehicle dashboard, rendered on the car head unit.
 *
 * SPEED and LOCATION are real, from the phone's GPS (the only data a
 * projection car like the Hyundai i20 actually exposes). The remaining ECU
 * figures are simulated for the i20 so the screen reads like a full dashboard.
 */
class CarInfoScreen(carContext: CarContext) : Screen(carContext), DefaultLifecycleObserver {

    private val fused = LocationServices.getFusedLocationProviderClient(carContext)

    // Real (phone GPS)
    private var gpsSpeedKmh = 0.0
    private var gpsLoc      = "waiting for GPS…"
    private var gpsReady    = false

    // Simulated Hyundai i20 values
    private val vehicle   = "Hyundai i20"
    private val petrolPct = 74
    private val rangeKm    = 410
    private val mileage    = "11.9 km/L"
    private val odometerKm = 55_391
    private val gear       = "D"

    init {
        lifecycle.addObserver(this)
    }

    // ── Phone GPS (real) ─────────────────────────────────────────────────────

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val loc = result.lastLocation ?: return
            gpsReady = true
            gpsSpeedKmh = if (loc.hasSpeed()) loc.speed * 3.6 else gpsSpeedKmh
            gpsLoc = "%.4f, %.4f".format(loc.latitude, loc.longitude)
            invalidate()
        }
    }

    private fun hasLocationPermission() = ContextCompat.checkSelfPermission(
        carContext, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    override fun onStart(owner: LifecycleOwner) {
        if (!hasLocationPermission()) {
            gpsLoc = "grant location in the phone app"
            invalidate()
            return
        }
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
            .setMinUpdateIntervalMillis(1000L)
            .build()
        runCatching { fused.requestLocationUpdates(request, locationCallback, Looper.getMainLooper()) }
    }

    override fun onStop(owner: LifecycleOwner) {
        runCatching { fused.removeLocationUpdates(locationCallback) }
    }

    // ── Simulated engine RPM (varies with real speed) ────────────────────────

    private fun rpm(): Int = if (gpsSpeedKmh < 1)
        780 + Random.nextInt(170)                                   // idle
    else
        (1100 + (gpsSpeedKmh * 22).toInt() + Random.nextInt(-120, 220)).coerceIn(900, 4200)

    // ── Template ─────────────────────────────────────────────────────────────

    override fun onGetTemplate(): Template {
        val speedText = if (gpsReady) "%.0f km/h".format(gpsSpeedKmh) else "waiting for GPS…"

        val list = ItemList.Builder()
            .addItem(row("Speed", "$speedText   · live"))
            .addItem(row("Vehicle", vehicle))
            .addItem(row("Petrol", "$petrolPct%   ·   $rangeKm km range"))
            .addItem(row("Engine", "${"%,d".format(rpm())} rpm   ·   Gear $gear   ·   $mileage"))
            .addItem(row("Odometer", "%,d km".format(odometerKm)))
            .addItem(row("Location", gpsLoc))
            .build()

        val actions = ActionStrip.Builder()
            .addAction(
                Action.Builder()
                    .setTitle("Refresh")
                    .setOnClickListener { invalidate() }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setTitle("Routes")
                    .setOnClickListener { screenManager.push(RouteSelectionCarScreen(carContext)) }
                    .build()
            )
            .build()

        return ListTemplate.Builder()
            .setTitle("GreenSync — Hyundai i20")
            .setSingleList(list)
            .setHeaderAction(Action.APP_ICON)
            .setActionStrip(actions)
            .build()
    }

    private fun row(label: String, value: String): Row =
        Row.Builder().setTitle(label).addText(value).build()
}
