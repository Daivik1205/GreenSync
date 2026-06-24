package com.greensync.screens

import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.hardware.CarHardwareManager
import androidx.car.app.hardware.common.CarValue
import androidx.car.app.hardware.info.EnergyLevel
import androidx.car.app.hardware.info.Mileage
import androidx.car.app.hardware.info.Model
import androidx.car.app.hardware.info.Speed
import androidx.car.app.model.Action
import androidx.car.app.model.Pane
import androidx.car.app.model.PaneTemplate
import androidx.car.app.model.Row
import androidx.car.app.model.Template
import androidx.core.content.ContextCompat
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner

/**
 * Android Auto car-info dashboard, rendered on the head unit.
 *
 * Reads live vehicle data through the Car App Library's [CarHardwareManager]
 * (CarInfo: model, energy level, speed, odometer). Whatever the connected car
 * actually exposes is shown; anything the car doesn't report is labelled
 * clearly rather than faked.
 *
 * Note: over Android Auto *projection* most cars only expose a subset of this
 * data (often just model / energy). Full ECU access requires the app to run on
 * Android Automotive OS.
 */
class CarInfoScreen(carContext: CarContext) : Screen(carContext), DefaultLifecycleObserver {

    private val executor = ContextCompat.getMainExecutor(carContext)
    private var carInfo = runCatching {
        carContext.getCarService(CarHardwareManager::class.java).carInfo
    }.getOrNull()

    private var modelText  = "Reading…"
    private var energyText = "—"
    private var rangeText  = "—"
    private var speedText  = "—"
    private var odoText    = "—"
    private var note       = "Connecting to vehicle…"
    private var listening  = false

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

    private val speedListener = androidx.car.app.hardware.common.OnCarDataAvailableListener<Speed> { s ->
        speedText = s.displaySpeedMetersPerSecond.text { "%.0f km/h".format(it * 3.6f) }
        invalidate()
    }

    private val mileageListener = androidx.car.app.hardware.common.OnCarDataAvailableListener<Mileage> { m ->
        odoText = m.odometerMeters.text { "%,.0f km".format(it / 1000f) }
        invalidate()
    }

    init {
        lifecycle.addObserver(this)
    }

    override fun onStart(owner: LifecycleOwner) {
        val info = carInfo
        if (info == null) {
            note = "Car hardware service unavailable on this host."
            invalidate()
            return
        }
        // CarInfo needs the projected car-data permissions at runtime.
        val perms = listOf(
            "com.google.android.gms.permission.CAR_FUEL",
            "com.google.android.gms.permission.CAR_SPEED",
            "com.google.android.gms.permission.CAR_MILEAGE",
        )
        runCatching {
            carContext.requestPermissions(perms) { _, _ -> startListening() }
        }.onFailure { startListening() }
    }

    override fun onStop(owner: LifecycleOwner) {
        val info = carInfo ?: return
        if (listening) runCatching {
            info.removeEnergyLevelListener(energyListener)
            info.removeSpeedListener(speedListener)
            info.removeMileageListener(mileageListener)
        }
        listening = false
    }

    private fun startListening() {
        val info = carInfo ?: return
        note = "Live from your vehicle"
        runCatching {
            info.fetchModel(executor) { m: Model ->
                val name = m.name.text { it }
                val make = m.manufacturer.text { it }
                val year = m.year.text { it.toString() }
                modelText = listOf(make, name, year)
                    .filter { it.isNotBlank() && it != "—" }
                    .joinToString(" ")
                    .ifBlank { "Vehicle connected" }
                invalidate()
            }
            info.addEnergyLevelListener(executor, energyListener)
            info.addSpeedListener(executor, speedListener)
            info.addMileageListener(executor, mileageListener)
            listening = true
        }.onFailure {
            note = "This car doesn't expose live data over Android Auto."
            invalidate()
        }
    }

    override fun onGetTemplate(): Template {
        val pane = Pane.Builder()
            .addRow(infoRow("Vehicle", modelText))
            .addRow(infoRow("Speed", speedText))
            .addRow(infoRow("Energy", energyText))
            .addRow(infoRow("Range", rangeText))
            .addRow(infoRow("Odometer", odoText))
            .addAction(
                Action.Builder()
                    .setTitle("Refresh")
                    .setOnClickListener { startListening() }
                    .build()
            )
            .addAction(
                Action.Builder()
                    .setTitle("Routes")
                    .setOnClickListener { screenManager.push(RouteSelectionCarScreen(carContext)) }
                    .build()
            )
            .build()

        return PaneTemplate.Builder(pane)
            .setTitle("GreenSync — Vehicle  ·  $note")
            .setHeaderAction(Action.APP_ICON)
            .build()
    }

    private fun infoRow(label: String, value: String): Row =
        Row.Builder().setTitle(label).addText(value).build()

    /** Renders a CarValue as text, surfacing why it's missing when it is. */
    private fun <T> CarValue<T>.text(format: (T) -> String): String = when (status) {
        CarValue.STATUS_SUCCESS       -> value?.let(format) ?: "—"
        CarValue.STATUS_UNIMPLEMENTED -> "not reported"
        CarValue.STATUS_UNAVAILABLE   -> "unavailable"
        else                          -> "—"
    }
}
