package com.greensync.screens

import android.Manifest
import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.os.Bundle
import android.view.View
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.greensync.R
import com.greensync.services.CarTelemetry
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import java.util.UUID
import kotlin.math.roundToInt
import kotlin.random.Random

/**
 * Vehicle / Android-Auto telemetry dashboard.
 *
 * When the phone is docked in an Android Automotive head unit, this reads the
 * car's real ECU via CarPropertyManager (speed, fuel, battery). On a plain
 * phone it shows a believable simulated drive so the screen is never empty.
 *
 * This is also the "communicator" surface for the backend: the same telemetry
 * is streamed by [com.greensync.services.EcuTelemetryService] over MQTT, so
 * once real users connect, the routing engine can factor each vehicle's range,
 * fuel and engine type when picking the best route.
 */
class VehicleActivity : AppCompatActivity() {

    // ── Vehicle profile (stable for the session) ─────────────────────────────
    private data class Profile(val name: String, val isEv: Boolean, val tankOrKwh: Double, val effic: Double)

    private val iceFleet = listOf(
        Profile("Tata Nexon",    false, 44.0, 16.5),
        Profile("Maruti Swift",  false, 37.0, 22.0),
        Profile("Hyundai Creta", false, 50.0, 17.0),
        Profile("Mahindra XUV",  false, 57.0, 14.5),
    )
    private val evFleet = listOf(
        Profile("Tata Nexon EV", true, 40.5, 6.4),
        Profile("MG ZS EV",      true, 50.3, 5.8),
    )
    private lateinit var profile: Profile
    private val vehicleId = "veh_${UUID.randomUUID().toString().take(6)}"

    // ── Live state ───────────────────────────────────────────────────────────
    private var connected   = false
    private var speed       = 0.0
    private var fuelPct     = 62.0
    private var batteryPct  = 74.0
    private var odometerKm  = 18_400 + Random.nextInt(40_000)
    private var coolantC    = 86
    private var rpm         = 820
    private var streamCount = 0

    private val cpmHelper by lazy { CarTelemetry(this) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_vehicle)

        connected = cpmHelper.available
        profile   = if (Random.nextInt(3) == 0) evFleet.random() else iceFleet.random()
        // A connected car reports its real make/model; mock just shows our pick.

        findViewById<TextView>(R.id.btn_back).setOnClickListener { finish() }
        setupStaticUi()
        pulseDot()
        startTelemetry()
        fetchLocation()
    }

    private fun setupStaticUi() {
        findViewById<TextView>(R.id.tv_veh_status).text =
            if (connected) "● CONNECTED — head unit" else "● SIMULATED — phone not docked"
        findViewById<TextView>(R.id.tv_veh_name).text   = profile.name
        findViewById<TextView>(R.id.tv_veh_engine).text = if (profile.isEv) "⚡ EV" else "⛽ ICE"
        findViewById<TextView>(R.id.tv_veh_broadcast).text =
            "📡 Streaming to GreenSync · $vehicleId · every 5s\n" +
            "Route engine factors your ${if (profile.isEv) "charge & range" else "fuel & range"}, " +
            "engine type and live position."
    }

    private fun pulseDot() {
        val dot = findViewById<View>(R.id.dot_veh)
        ValueAnimator.ofFloat(1f, 0.25f, 1f).apply {
            duration = 1500
            repeatCount = ValueAnimator.INFINITE
            addUpdateListener { dot.alpha = it.animatedValue as Float }
            start()
        }
    }

    // ── Telemetry loop ───────────────────────────────────────────────────────

    private fun startTelemetry() {
        render()
        lifecycleScope.launch {
            while (true) {
                delay(1000)
                tick()
                render()
            }
        }
    }

    /** One simulation/read step. */
    private fun tick() {
        // Speed: prefer the real ECU value when docked, else a smooth drive cycle.
        val realSpeed = if (connected) cpmHelper.speedKmh() else null
        speed = realSpeed ?: nextMockSpeed()

        // RPM tracks speed (idle ~820, ~ +85 per km/h, capped).
        rpm = if (speed < 1) 800 + Random.nextInt(60) else (900 + speed * 85).roundToInt().coerceAtMost(6200)

        // Fuel / battery slowly deplete with use; real value overrides when present.
        if (profile.isEv) {
            batteryPct = (cpmHelper.batteryPct()?.times(100)?.toDouble()
                ?: (batteryPct - speed / 4000.0)).coerceIn(2.0, 100.0)
        } else {
            fuelPct = (cpmHelper.fuelPct()?.times(100)?.toDouble()
                ?: (fuelPct - speed / 6000.0)).coerceIn(1.0, 100.0)
        }

        coolantC   = (86 + (speed / 12).toInt()).coerceIn(80, 104)
        odometerKm += if (speed > 0) ((speed / 3600.0) * 1000).roundToInt().coerceAtLeast(0) else 0
        streamCount++
    }

    private var cruising = 0
    private fun nextMockSpeed(): Double {
        // Occasionally stop at a signal, otherwise drift toward a cruising speed.
        if (cruising <= 0) {
            cruising = Random.nextInt(4, 12)
            return if (Random.nextInt(5) == 0) 0.0 else (18 + Random.nextInt(46)).toDouble()
        }
        cruising--
        val drift = Random.nextInt(-6, 7)
        return (speed + drift).coerceIn(0.0, 92.0)
    }

    private fun render() {
        findViewById<TextView>(R.id.tv_veh_speed).text = speed.roundToInt().toString()
        findViewById<ProgressBar>(R.id.pb_veh_speed).setProgress(speed.roundToInt().coerceIn(0, 160), true)

        // Range = remaining energy fraction × usable tank/pack × efficiency.
        val frac  = if (profile.isEv) batteryPct / 100.0 else fuelPct / 100.0
        val range = (frac * profile.tankOrKwh * profile.effic).roundToInt()
        val litres = frac * profile.tankOrKwh

        setCell(R.id.tv_fuel,
            if (profile.isEv) "${batteryPct.roundToInt()}%" else "%.0f%%".format(fuelPct),
            warn = frac < 0.15)
        setCell(R.id.tv_range, "$range km", warn = range < 40)
        setCell(R.id.tv_mileage,
            if (profile.isEv) "%.1f km/kWh".format(profile.effic) else "%.1f km/l".format(profile.effic))
        setCell(R.id.tv_battery, if (profile.isEv) "${batteryPct.roundToInt()}%" else "n/a (ICE)")
        setCell(R.id.tv_rpm, "%,d".format(rpm))
        setCell(R.id.tv_gear, gearFor(speed))
        setCell(R.id.tv_coolant, "$coolantC°C", warn = coolantC > 100)
        setCell(R.id.tv_odo, "%,d km".format(odometerKm))

        // Petrol cell label already says "petrol left"; for EV repurpose value text.
        if (profile.isEv) {
            setCell(R.id.tv_fuel, "${batteryPct.roundToInt()}%", warn = batteryPct < 15)
        } else {
            setCell(R.id.tv_fuel, "%.0f%% · %.0f L".format(fuelPct, litres), warn = fuelPct < 12)
        }
    }

    private fun gearFor(s: Double): String = when {
        s < 1   -> "P"
        s < 18  -> "D1"
        s < 32  -> "D2"
        s < 50  -> "D3"
        s < 70  -> "D4"
        else    -> "D5"
    }

    private fun setCell(id: Int, value: String, warn: Boolean = false) {
        findViewById<TextView>(id).apply {
            text = value
            setTextColor(
                if (warn) android.graphics.Color.parseColor("#FFB300")
                else androidx.core.content.ContextCompat.getColor(this@VehicleActivity, R.color.text_primary)
            )
        }
    }

    // ── Location ─────────────────────────────────────────────────────────────

    @SuppressLint("MissingPermission")
    private fun fetchLocation() {
        val granted = ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED ||
            ContextCompat.checkSelfPermission(
                this, Manifest.permission.ACCESS_COARSE_LOCATION
            ) == PackageManager.PERMISSION_GRANTED
        if (!granted) {
            findViewById<TextView>(R.id.tv_veh_location).text = "Location permission off"
            return
        }
        val client = LocationServices.getFusedLocationProviderClient(this)
        try {
            client.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, CancellationTokenSource().token)
                .addOnSuccessListener { loc -> loc?.let { applyLocation(it) } }
        } catch (e: Exception) { /* leave "Locating…" */ }
    }

    private fun applyLocation(loc: Location) {
        findViewById<TextView>(R.id.tv_veh_coords).text =
            "%.4f, %.4f · GPS lock".format(loc.latitude, loc.longitude)
        lifecycleScope.launch {
            val name = withContext(Dispatchers.IO) {
                try {
                    @Suppress("DEPRECATION")
                    Geocoder(this@VehicleActivity, Locale.getDefault())
                        .getFromLocation(loc.latitude, loc.longitude, 1)
                        ?.firstOrNull()?.let { it.subLocality ?: it.locality ?: it.adminArea }
                } catch (e: Exception) { null }
            } ?: "On the move"
            findViewById<TextView>(R.id.tv_veh_location).text = name
        }
    }
}
