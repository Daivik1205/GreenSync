package com.greensync.screens

import android.Manifest
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.os.Looper
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.info.EnergyLevel
import androidx.car.app.hardware.info.Mileage
import androidx.car.app.hardware.info.Model
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

/**
 * Android Auto vehicle dashboard, rendered on the car head unit.
 *
 * Shows live SPEED and LOCATION from the phone's GPS (works in any car,
 * including projection-only cars like the Hyundai i20), plus a best-effort
 * read of the car's own ECU via [CarHardwareManager] (model / fuel / range /
 * odometer). Most projection cars don't share ECU data with third-party apps,
 * so those rows are labelled honestly when the car stays silent.
 */
class CarInfoScreen(carContext: CarContext) : Screen(carContext), DefaultLifecycleObserver {

    private val executor = ContextCompat.getMainExecutor(carContext)
    private val fused = LocationServices.getFusedLocationProviderClient(carContext)

    private var carInfo = runCatching {
        carContext.getCarService(CarHardwareManager::class.java).carInfo
    }.getOrNull()

    // Phone-GPS values (the reliable ones)
    private var gpsSpeed = "waiting for GPS…"
    private var gpsLoc   = "—"

    // Car-reported values (often unavailable over projection)
    private var modelText  = "—"
    private var energyText = "—"
    private var rangeText  = "—"
    private var odoText    = "—"

    private var listening = false

    // ── Phone GPS ────────────────────────────────────────────────────────────

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            val loc = result.lastLocation ?: return
            gpsSpeed = if (loc.hasSpeed()) "%.0f km/h".format(loc.speed * 3.6f) else "0 km/h"
            gpsLoc   = "%.4f, %.4f".format(loc.latitude, loc.longitude)
            invalidate()
        }
    }

    private fun hasLocationPermission() = ContextCompat.checkSelfPermission(
        carContext, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED

    @SuppressLint("MissingPermission")
    private fun startGps() {
        if (!hasLocationPermission()) {
            gpsSpeed = "grant location in the phone app"
            invalidate()
            return
        }
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
            .setMinUpdateIntervalMillis(1000L)
            .build()
        runCatching { fused.requestLocationUpdates(request, locationCallback, Looper.getMainLooper()) }
    }

    // ── Lifecycle ────────────────────────────────────────────────────────────

    init {
        lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) {
        startGps()

        val info = carInfo ?: return
        val perms = listOf(
            "com.google.android.gms.permission.CAR_FUEL",
            "com.google.android.gms.permission.CAR_SPEED",
            "com.google.android.gms.permission.CAR_MILEAGE",
        )
        runCatching {
            carContext.requestPermissions(perms) { _, _ -> startCarListening() }
        }.onFailure { startCarListening() }
    }

    override fun onStop(owner: LifecycleOwner) {
        runCatching { fused.removeLocationUpdates(locationCallback) }
        val info = carInfo ?: return
        if (listening) runCatching {
            info.removeEnergyLevelListener(energyListener)
            info.removeMileageListener(mileageListener)
        }
        listening = false
    }

    // ── Car ECU (best effort) ────────────────────────────────────────────────

    private val energyListener = androidx.car.app.hardware.common.OnCarDataAvailableListener<EnergyLevel> { e ->
        val fuelOk = e.fuelPercent.status == CarValue.STATUS_SUCCESS
        val battOk = e.batteryPercent.status == CarValue.STATUS_SUCCESS
        energyText = when {
            fuelOk && battOk -> "%.0f%% fuel · %.0f%% batt".format(e.fuelPercent.value, e.batteryPercent.value)
            fuelOk           -> "%.0f%% fuel".format(e.fuelPercent.value)
            battOk           -> "%.0f%% battery".format(e.batteryPercent.value)
            else             -> e.fuelPercent.text { "%.0f%%".format(it) }
        }
        rangeText = e.rangeRemainingMeters.text { "%.0f km".format(it / 1000f) }
        invalidate()
    }

    private val mileageListener = androidx.car.app.hardware.common.OnCarDataAvailableListener<Mileage> { m ->
        odoText = m.odometerMeters.text { "%,.0f km".format(it / 1000f) }
        invalidate()
    }

    private fun startCarListening() {
        val info = carInfo ?: return
        runCatching {
            info.fetchModel(executor) { m: Model ->
                val parts = listOf(
                    m.manufacturer.text { it },
                    m.name.text { it },
                    m.year.text { it.toString() },
                ).filter { it.isNotBlank() && it != "—" && it != "not reported" && it != "unavailable" }
                modelText = parts.joinToString(" ").ifBlank { "not shared by car" }
                invalidate()
            }
            info.addEnergyLevelListener(executor, energyListener)
            info.addMileageListener(executor, mileageListener)
            listening = true
        }
    }

    // ── Template ─────────────────────────────────────────────────────────────

    override fun onGetTemplate(): Template {
        val list = ItemList.Builder()
            .addItem(row("Speed", "$gpsSpeed   · phone GPS"))
            .addItem(row("Location", gpsLoc))
            .addItem(row("Vehicle", modelText))
            .addItem(row("Fuel / Energy", energyText))
            .addItem(row("Range", rangeText))
            .addItem(row("Odometer", odoText))
            .build()

        val actions = ActionStrip.Builder()
            .addAction(
                Action.Builder()
                    .setTitle("Refresh")
                    .setOnClickListener { startCarListening() }
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
            .setTitle("GreenSync — Vehicle")
            .setSingleList(list)
            .setHeaderAction(Action.APP_ICON)
            .setActionStrip(actions)
            .build()
    }

    private fun row(label: String, value: String): Row =
        Row.Builder().setTitle(label).addText(value).build()

    /** Renders a CarValue as text, surfacing why it's missing when it is. */
    private fun <T> CarValue<T>.text(format: (T) -> String): String = when (status) {
        CarValue.STATUS_SUCCESS       -> value?.let(format) ?: "—"
        CarValue.STATUS_UNIMPLEMENTED -> "not shared by car"
        CarValue.STATUS_UNAVAILABLE   -> "unavailable"
        else                          -> "—"
    }
}
