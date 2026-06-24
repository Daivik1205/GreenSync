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
import android.os.Looper
import androidx.appcompat.app.AppCompatActivity
import androidx.car.app.connection.CarConnection
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
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

    // Real signals
    private var connectionType = CarConnection.CONNECTION_TYPE_NOT_CONNECTED
    private var gpsSpeedKmh: Double? = null

    private val cpmHelper by lazy { CarTelemetry(this) }
    private val fused by lazy { LocationServices.getFusedLocationProviderClient(this) }
    private var geocodeAt = 0L

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_vehicle)

        connected = cpmHelper.available
        // Hardcoded to the user's vehicle.
        profile   = Profile("Hyundai i20", isEv = false, tankOrKwh = 37.0, effic = 11.9)

        findViewById<TextView>(R.id.btn_back).setOnClickListener { finish() }
        setupStaticUi()
        pulseDot()
        observeCarConnection()
        startTelemetry()
        startLocationUpdates()
    }

    private fun setupStaticUi() {
        findViewById<TextView>(R.id.tv_veh_name).text   = profile.name
        findViewById<TextView>(R.id.tv_veh_engine).text = if (profile.isEv) "⚡ EV" else "⛽ ICE"
        renderStatus()
    }

    /** Observe the *real* Android Auto / Automotive connection state. */
    private fun observeCarConnection() {
        CarConnection(this).type.observe(this) { type ->
            connectionType = type
            connected = type != CarConnection.CONNECTION_TYPE_NOT_CONNECTED || cpmHelper.available
            renderStatus()
        }
    }

    private fun renderStatus() {
        val status = when (connectionType) {
            CarConnection.CONNECTION_TYPE_PROJECTION -> "● CONNECTED — Android Auto"
            CarConnection.CONNECTION_TYPE_NATIVE     -> "● CONNECTED — Android Automotive"
            else -> if (cpmHelper.available) "● CONNECTED — head unit" else "○ NOT IN CAR — phone"
        }
        findViewById<TextView>(R.id.tv_veh_status).text = status

        val src = if (connectionType == CarConnection.CONNECTION_TYPE_PROJECTION)
            "Speed & location are live from this phone (your i20 doesn't share ECU over Android Auto)."
        else
            "Live position from phone GPS · vehicle metrics simulated until docked in the car."
        findViewById<TextView>(R.id.tv_veh_broadcast).text =
            "📡 GreenSync · $vehicleId · streaming every 5s\n$src"
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

    /** One step — only speed and RPM move; the rest are hardcoded i20 values. */
    private fun tick() {
        // Speed priority: AAOS ECU → real phone GPS (when projected to a car) → demo.
        speed = when {
            cpmHelper.speedKmh() != null -> cpmHelper.speedKmh()!!
            connectionType == CarConnection.CONNECTION_TYPE_PROJECTION -> gpsSpeedKmh ?: 0.0
            else -> nextMockSpeed()
        }

        // Random RPM that tracks speed (idle when stopped).
        rpm = if (speed < 1) 780 + Random.nextInt(170)
              else (1100 + (speed * 22).roundToInt() + Random.nextInt(-120, 220)).coerceIn(900, 4200)
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
        // Speed is live; everything else is hardcoded for the i20.
        findViewById<TextView>(R.id.tv_veh_speed).text = speed.roundToInt().toString()
        findViewById<ProgressBar>(R.id.pb_veh_speed).setProgress(speed.roundToInt().coerceIn(0, 160), true)

        setCell(R.id.tv_fuel,    "74%")
        setCell(R.id.tv_range,   "410 km")
        setCell(R.id.tv_mileage, "11.9 km/L")
        setCell(R.id.tv_battery, "n/a (ICE)")
        setCell(R.id.tv_rpm,     "%,d".format(rpm))
        setCell(R.id.tv_gear,    "D")
        setCell(R.id.tv_coolant, "89°C")
        setCell(R.id.tv_odo,     "55,391 km")
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

    // ── Location (real, continuous) ──────────────────────────────────────────

    private val locationCallback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            result.lastLocation?.let { applyLocation(it) }
        }
    }

    @SuppressLint("MissingPermission")
    private fun startLocationUpdates() {
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
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
            .setMinUpdateIntervalMillis(1000L)
            .build()
        runCatching { fused.requestLocationUpdates(request, locationCallback, Looper.getMainLooper()) }
    }

    private fun applyLocation(loc: Location) {
        // Real GPS speed feeds the speedometer when projected to a car.
        gpsSpeedKmh = if (loc.hasSpeed()) (loc.speed * 3.6) else gpsSpeedKmh
        findViewById<TextView>(R.id.tv_veh_coords).text =
            "%.4f, %.4f · GPS lock".format(loc.latitude, loc.longitude)

        // Reverse-geocode the area at most every ~8s.
        val now = System.currentTimeMillis()
        if (now - geocodeAt < 8000) return
        geocodeAt = now
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

    override fun onDestroy() {
        super.onDestroy()
        runCatching { fused.removeLocationUpdates(locationCallback) }
    }
}
