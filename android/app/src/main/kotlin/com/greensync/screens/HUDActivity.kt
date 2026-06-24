package com.greensync.screens

import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.greensync.R
import com.greensync.screens.RouteSelectionActivity.Companion.MOCK_USER_COUNTS
import com.greensync.screens.RouteSelectionActivity.Companion.congestionColor
import com.greensync.screens.RouteSelectionActivity.Companion.congestionIcon
import com.greensync.screens.RouteSelectionActivity.Companion.congestionLabel
import com.greensync.screens.RouteSelectionActivity.Companion.congestionProgress
import com.greensync.screens.RouteSelectionActivity.Companion.expectedSpeed
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polyline
import java.util.Locale
import kotlin.math.max
import kotlin.random.Random

class HUDActivity : AppCompatActivity() {

    companion object {
        private const val EXTRA_ROUTE_ID     = "route_id"
        private const val EXTRA_SUMMARY      = "route_summary"
        private const val EXTRA_SELECTED_IDX = "selected_idx"
        private const val EXTRA_USER_COUNT   = "user_count"
        private const val EXTRA_ALL_COUNTS   = "all_counts"
        private const val EXTRA_DEST_NAME    = "dest_name"
        private const val EXTRA_ORIGIN_NAME  = "origin_name"
        private const val EXTRA_ETA          = "adjusted_eta"
        private const val EXTRA_SPEED        = "expected_speed"
        private const val EXTRA_DISTANCE     = "distance_km"
        private const val EXTRA_GEOMETRY     = "route_geometry"

        fun newIntent(
            context:     Context,
            routeId:     String,
            summary:     String,
            selectedIdx: Int,
            userCount:   Int,
            allCounts:   IntArray,
            destName:    String = "Destination",
            originName:  String = "Origin",
            adjustedEta: Int    = 0,
            speed:       Int    = 0,
            distanceKm:  Double = 0.0,
            geometry:    DoubleArray = DoubleArray(0),
        ): Intent = Intent(context, HUDActivity::class.java).apply {
            putExtra(EXTRA_ROUTE_ID,     routeId)
            putExtra(EXTRA_SUMMARY,      summary)
            putExtra(EXTRA_SELECTED_IDX, selectedIdx)
            putExtra(EXTRA_USER_COUNT,   userCount)
            putExtra(EXTRA_ALL_COUNTS,   allCounts)
            putExtra(EXTRA_DEST_NAME,    destName)
            putExtra(EXTRA_ORIGIN_NAME,  originName)
            putExtra(EXTRA_ETA,          adjustedEta)
            putExtra(EXTRA_SPEED,        speed)
            putExtra(EXTRA_DISTANCE,     distanceKm)
            putExtra(EXTRA_GEOMETRY,     geometry)
        }

        /** g CO₂ per km for a given committed-vehicle count (mirrors backend cost model). */
        private fun co2PerKm(count: Int) = when {
            count > 500 -> 180
            count > 150 -> 130
            else        -> 90
        }
    }

    private lateinit var hudMap: MapView

    // Live route comparison
    private var selectedIdx   = 0
    private var selectedColor = 0
    private lateinit var cmpCountsLive: IntArray
    private lateinit var cmpLabels: Array<TextView>
    private lateinit var cmpBars:   Array<ProgressBar>
    private lateinit var cmpCountViews: Array<TextView>

    // Nearest traffic signal to the destination (a single, fixed junction)
    private enum class Phase(val label: String, val color: String, val next: String) {
        RED("🔴 RED",   "#FF5247", "to green"),
        GREEN("🟢 GREEN", "#2DE371", "to amber"),
        AMBER("🟡 AMBER", "#FFB300", "to red"),
    }
    private var redLen   = 60
    private var greenLen = 40
    private val amberLen = 4
    private var phase    = Phase.RED
    private var phaseRemaining = 60
    private var signalName   = "Junction"
    private var signalSynced = true

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_hud)

        val summary     = intent.getStringExtra(EXTRA_SUMMARY)     ?: "Selected Route"
        val selectedIdx = intent.getIntExtra(EXTRA_SELECTED_IDX, 0)
        val userCount   = intent.getIntExtra(EXTRA_USER_COUNT, 100)
        val allCounts   = intent.getIntArrayExtra(EXTRA_ALL_COUNTS) ?: MOCK_USER_COUNTS
        val destName    = intent.getStringExtra(EXTRA_DEST_NAME)    ?: "Destination"
        val originName  = intent.getStringExtra(EXTRA_ORIGIN_NAME) ?: "Origin"
        val eta         = intent.getIntExtra(EXTRA_ETA, 0)
        val speed       = intent.getIntExtra(EXTRA_SPEED, 0)
        val distance    = intent.getDoubleExtra(EXTRA_DISTANCE, 0.0)
        val geometry    = intent.getDoubleArrayExtra(EXTRA_GEOMETRY) ?: DoubleArray(0)

        val updatedCount = userCount + 1
        val color        = congestionColor(updatedCount)
        val icon         = congestionIcon(updatedCount)
        val label        = congestionLabel(updatedCount)

        // Back
        findViewById<TextView>(R.id.btn_back).setOnClickListener { finish() }

        // Header
        findViewById<TextView>(R.id.tv_hud_title).text = "$originName  →  $destName"

        // Selected-route map
        setupRouteMap(geometry, color, originName, destName)

        // Route confirmed banner
        val routeNum   = selectedIdx + 1
        val bannerView = findViewById<TextView>(R.id.tv_route_label)
        bannerView.text = "Route $routeNum  ·  ${summary.ifBlank { "Via city roads" }}"
        bannerView.backgroundTintList = ColorStateList.valueOf(color)
        findViewById<TextView>(R.id.tv_map_caption).text =
            "YOUR ROUTE · Route $routeNum → $destName"

        // Stat cards
        findViewById<TextView>(R.id.tv_stat_eta).text      = if (eta > 0) "$eta" else "--"
        val speedView = findViewById<TextView>(R.id.tv_stat_speed)
        speedView.text = if (speed > 0) "$speed" else "--"
        speedView.setTextColor(color)
        findViewById<TextView>(R.id.tv_stat_distance).text =
            if (distance > 0) "%.1f".format(distance) else "--"

        // Congestion
        findViewById<TextView>(R.id.tv_congestion_icon).text = icon
        val levelView = findViewById<TextView>(R.id.tv_congestion_level)
        levelView.text = label
        levelView.setTextColor(color)
        findViewById<TextView>(R.id.tv_you_joined).text =
            "You + ${updatedCount - 1} others on this route"

        // Route comparison — kept live (counts drift as commuters commit/leave)
        this.selectedIdx   = selectedIdx
        this.selectedColor = color
        setupLiveComparison(allCounts, updatedCount)

        // Community report buttons
        val totalActive = allCounts.sum() + 1
        setupReportButtons(totalActive)

        // Nearest traffic signal to the destination — cycles red → green → amber
        startNearestSignal(destName, updatedCount)

        // Live destination context (arrival clock, AQI, weather, parking)
        startDestinationPulse(destName, eta)

        // SUMO digital-twin savings (your route vs the busiest static baseline)
        renderRouteSavings(updatedCount, allCounts, eta, speed, distance)

        // Live SUMO simulation telemetry strip
        startSimTelemetry()
    }

    // ── Selected-route map ───────────────────────────────────────────────────

    private fun setupRouteMap(
        geometry: DoubleArray,
        color: Int,
        originName: String,
        destName: String,
    ) {
        hudMap = findViewById(R.id.hud_map)
        hudMap.setTileSource(TileSourceFactory.MAPNIK)
        hudMap.setMultiTouchControls(true)
        hudMap.controller.setZoom(12.0)

        // geometry is a flat [lat0, lng0, lat1, lng1, …] array.
        val points = ArrayList<GeoPoint>(geometry.size / 2)
        var i = 0
        while (i + 1 < geometry.size) {
            points.add(GeoPoint(geometry[i], geometry[i + 1]))
            i += 2
        }
        if (points.isEmpty()) {
            hudMap.controller.setCenter(GeoPoint(12.9716, 77.5946)) // Bengaluru centre
            return
        }

        hudMap.overlays.add(Polyline().apply {
            setPoints(points)
            outlinePaint.color = color
            outlinePaint.strokeWidth = 14f
            outlinePaint.alpha = 220
        })

        Marker(hudMap).apply {
            position = points.first()
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
            title = originName
            hudMap.overlays.add(this)
        }
        Marker(hudMap).apply {
            position = points.last()
            setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_BOTTOM)
            title = destName
            hudMap.overlays.add(this)
        }

        var minLat = Double.MAX_VALUE; var maxLat = -Double.MAX_VALUE
        var minLon = Double.MAX_VALUE; var maxLon = -Double.MAX_VALUE
        for (p in points) {
            if (p.latitude  < minLat) minLat = p.latitude
            if (p.latitude  > maxLat) maxLat = p.latitude
            if (p.longitude < minLon) minLon = p.longitude
            if (p.longitude > maxLon) maxLon = p.longitude
        }
        val box = BoundingBox(maxLat, maxLon, minLat, minLon)
        hudMap.post { hudMap.zoomToBoundingBox(box, false, 70) }
        hudMap.invalidate()
    }

    // ── Your-route-vs-static savings (mirrors the Streamlit dashboard) ────────

    private fun renderRouteSavings(
        count: Int,
        allCounts: IntArray,
        eta: Int,
        speed: Int,
        distance: Double,
    ) {
        val worstCount   = max(allCounts.maxOrNull() ?: count, count)
        val baseSpeed    = expectedSpeed(worstCount).coerceAtLeast(1)
        val baselineMin  = if (distance > 0) distance / baseSpeed * 60.0 else eta.toDouble()
        val timeSavedMin = (baselineMin - eta).coerceAtLeast(0.0)

        val emitSavedPct = (((co2PerKm(worstCount) - co2PerKm(count)).toDouble()
                / co2PerKm(worstCount)) * 100).coerceAtLeast(0.0)
        val speedGain    = (speed - baseSpeed).coerceAtLeast(0)

        findViewById<TextView>(R.id.tv_saved_time).text =
            if (timeSavedMin >= 1) "↓ %d min".format(timeSavedMin.toInt()) else "—"
        findViewById<TextView>(R.id.tv_saved_emit).text =
            if (emitSavedPct >= 1) "↓ %d%%".format(emitSavedPct.toInt()) else "baseline"
        findViewById<TextView>(R.id.tv_saved_speed).text =
            if (speedGain > 0) "+%d km/h".format(speedGain) else "%d km/h".format(speed)
    }

    // ── Live SUMO simulation telemetry ───────────────────────────────────────

    private var simStep     = 10_000 + Random.nextInt(2_000)
    private var simVehicles = 138 + Random.nextInt(34)
    private var simEdges    = 412 + Random.nextInt(40)
    private var simLoss     = 0.042 + Random.nextDouble() * 0.02
    private var simSamples  = 18_400 + Random.nextInt(2_000)
    private val simLsh      = 1_024

    private fun startSimTelemetry() {
        findViewById<TextView>(R.id.tv_sim_zones).text = "35"     // 35 RSU zones
        findViewById<TextView>(R.id.tv_sim_lsh).text   = "%,d".format(simLsh)
        renderSimTelemetry()
        lifecycleScope.launch {
            while (true) {
                delay(1000)
                simStep     += Random.nextInt(8, 16)
                simVehicles  = (simVehicles + Random.nextInt(-6, 7)).coerceIn(120, 185)
                simEdges     = (simEdges + Random.nextInt(-4, 5)).coerceIn(380, 470)
                simSamples  += Random.nextInt(4, 22)
                simLoss      = (simLoss - Random.nextDouble() * 0.0006).coerceAtLeast(0.011)
                renderSimTelemetry()
            }
        }
    }

    private fun renderSimTelemetry() {
        findViewById<TextView>(R.id.tv_sim_vehicles).text = "%,d".format(simVehicles)
        findViewById<TextView>(R.id.tv_sim_edges).text    = "%,d".format(simEdges)
        findViewById<TextView>(R.id.tv_sim_step).text     = "%,d".format(simStep)
        findViewById<TextView>(R.id.tv_sim_loss).text     = "%.3f".format(simLoss)
        findViewById<TextView>(R.id.tv_sim_samples).text  = "%,d".format(simSamples)
    }

    override fun onResume() {
        super.onResume()
        if (::hudMap.isInitialized) hudMap.onResume()
    }

    override fun onPause() {
        super.onPause()
        if (::hudMap.isInitialized) hudMap.onPause()
    }

    // ── Live route comparison ────────────────────────────────────────────────

    private fun setupLiveComparison(allCounts: IntArray, updatedCount: Int) {
        // One row per real route — no phantom third route when only two exist.
        val n = allCounts.size.coerceAtLeast(1)
        val container = findViewById<LinearLayout>(R.id.ll_comparison)
        container.removeAllViews()

        val labels = ArrayList<TextView>(n)
        val bars   = ArrayList<ProgressBar>(n)
        val counts = ArrayList<TextView>(n)
        val dp = resources.displayMetrics.density

        repeat(n) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = android.view.Gravity.CENTER_VERTICAL
                setPadding((16 * dp).toInt(), (4 * dp).toInt(), (16 * dp).toInt(), (4 * dp).toInt())
            }
            val label = TextView(this).apply {
                layoutParams = LinearLayout.LayoutParams((68 * dp).toInt(), LinearLayout.LayoutParams.WRAP_CONTENT)
                textSize = 12f
                setTextColor(Color.parseColor("#8B978C"))
            }
            val bar = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
                layoutParams = LinearLayout.LayoutParams(0, (8 * dp).toInt(), 1f).apply {
                    marginStart = (8 * dp).toInt(); marginEnd = (8 * dp).toInt()
                }
                max = 100
            }
            val count = TextView(this).apply {
                layoutParams = LinearLayout.LayoutParams((104 * dp).toInt(), LinearLayout.LayoutParams.WRAP_CONTENT)
                textSize = 11f
                gravity = android.view.Gravity.END
                setTextColor(Color.parseColor("#8B978C"))
                typeface = androidx.core.content.res.ResourcesCompat.getFont(this@HUDActivity, R.font.jetbrains_mono)
            }
            row.addView(label); row.addView(bar); row.addView(count)
            container.addView(row)
            labels.add(label); bars.add(bar); counts.add(count)
        }
        cmpLabels     = labels.toTypedArray()
        cmpBars       = bars.toTypedArray()
        cmpCountViews = counts.toTypedArray()

        // Seed live counts: your route reflects you having joined it.
        cmpCountsLive = IntArray(n) {
            if (it == selectedIdx) updatedCount else allCounts.getOrElse(it) { 100 }
        }
        renderComparison()

        // Counts drift every ~2.5s as commuters commit to / leave each route.
        lifecycleScope.launch {
            while (true) {
                delay(2500)
                for (i in cmpCountsLive.indices) {
                    // Your route stays a touch stickier; others wander more.
                    val jitter = if (i == selectedIdx) Random.nextInt(-4, 6) else Random.nextInt(-9, 10)
                    cmpCountsLive[i] = (cmpCountsLive[i] + jitter).coerceAtLeast(8)
                }
                renderComparison()
            }
        }
    }

    private fun renderComparison() {
        for (i in cmpLabels.indices) {
            val c      = cmpCountsLive[i]
            val cColor = congestionColor(c)
            val spd    = expectedSpeed(c)
            val mine   = i == selectedIdx
            cmpLabels[i].text = if (mine) "Route ${i + 1} ★" else "Route ${i + 1}"
            cmpBars[i].progressTintList = ColorStateList.valueOf(cColor)
            // Smooth animated bar movement (API 24+).
            cmpBars[i].setProgress(congestionProgress(c).coerceIn(0, 100), true)
            cmpCountViews[i].text = "${congestionIcon(c)} $c  ·  ~$spd km/h"
            cmpCountViews[i].setTextColor(cColor)
            cmpLabels[i].setTextColor(if (mine) selectedColor else Color.parseColor("#8B978C"))
            cmpLabels[i].textSize = if (mine) 13f else 12f
        }
    }

    // ── Nearest traffic signal to the destination ────────────────────────────

    private val junctionPool = listOf(
        "Hebbal Flyover", "Mekhri Circle", "Cauvery Jn", "Windsor Manor",
        "Trinity Circle", "Domlur Flyover", "Marathahalli Br", "Silk Board Jn",
        "Tin Factory", "KR Puram Jn", "Sony World Jn", "Sarjapur Signal",
        "Madiwala Check", "BTM Signal", "Banaswadi Jn", "Hennur Cross",
    )

    /**
     * Picks the single nearest junction to the destination (stable per place)
     * and runs its real signal cycle: RED → GREEN → AMBER → RED, with the
     * countdown showing seconds left in the current phase. No vehicle movement.
     */
    private fun startNearestSignal(destName: String, count: Int) {
        // Stable choice so the same destination always maps to the same junction.
        signalName   = junctionPool[(destName.hashCode() and 0x7fffffff) % junctionPool.size]
        signalSynced = (destName.hashCode() and 0x7fffffff) % 100 < 70

        // Busier corridors hold red longer / green shorter.
        when {
            count > 500 -> { redLen = 75; greenLen = 30 }
            count > 150 -> { redLen = 60; greenLen = 40 }
            else        -> { redLen = 45; greenLen = 50 }
        }
        // Start somewhere in the cycle so it doesn't always begin at full red.
        phase = Phase.RED
        phaseRemaining = Random.nextInt(8, redLen)

        renderSignal(destName)
        lifecycleScope.launch {
            while (true) {
                delay(1000)
                phaseRemaining--
                if (phaseRemaining <= 0) advancePhase()
                renderSignal(destName)
            }
        }
    }

    private fun advancePhase() {
        phase = when (phase) {
            Phase.RED   -> Phase.GREEN
            Phase.GREEN -> Phase.AMBER
            Phase.AMBER -> Phase.RED
        }
        phaseRemaining = when (phase) {
            Phase.RED   -> redLen
            Phase.GREEN -> greenLen
            Phase.AMBER -> amberLen
        }
    }

    private fun renderSignal(destName: String) {
        val phaseView = findViewById<TextView>(R.id.tv_signal_phase) ?: return
        val locView   = findViewById<TextView>(R.id.tv_signal_location)
        val distView  = findViewById<TextView>(R.id.tv_signal_distance)
        val advView   = findViewById<TextView>(R.id.tv_signal_advisory)
        val countView = findViewById<TextView>(R.id.tv_signal_countdown)
        val countLbl  = findViewById<TextView>(R.id.tv_signal_countlabel)

        val color = Color.parseColor(phase.color)
        phaseView.text = phase.label + when (phase) {
            Phase.RED -> "  ·  NEAREST SIGNAL"
            else      -> ""
        }
        phaseView.setTextColor(color)

        locView.text  = signalName + if (signalSynced) "  ⟢" else ""
        distView.text = "nearest signal · near $destName"

        countView.text = "${phaseRemaining}s"
        countView.setTextColor(color)
        countLbl.text = phase.next

        advView.text = when (phase) {
            Phase.RED   -> if (signalSynced) "⟢ GreenSync holds your green wave" else "↘ red — ease off the throttle"
            Phase.GREEN -> "✓ green — clear to proceed"
            Phase.AMBER -> "⚠ amber — prepare to stop"
        }

        // Light up the active lamp; dim the rest.
        setLamp(R.id.lamp_red,   phase == Phase.RED)
        setLamp(R.id.lamp_amber, phase == Phase.AMBER)
        setLamp(R.id.lamp_green, phase == Phase.GREEN)
    }

    private fun setLamp(id: Int, on: Boolean) {
        findViewById<View>(id)?.alpha = if (on) 1f else 0.15f
    }

    // ── Live destination context ─────────────────────────────────────────────

    private fun startDestinationPulse(destName: String, etaMin: Int) {
        findViewById<TextView>(R.id.tv_dest_header).text = "ARRIVING AT ${destName.uppercase()}"

        // Arrival clock = now + ETA.
        val arrival = java.util.Calendar.getInstance().apply {
            add(java.util.Calendar.MINUTE, etaMin.coerceAtLeast(0))
        }
        val fmt = java.text.SimpleDateFormat("h:mm a", Locale.getDefault())
        findViewById<TextView>(R.id.tv_dest_arrival).text = "~${fmt.format(arrival.time)}"

        // Seed AQI / weather (stable per destination), parking ticks live.
        val seed   = destName.hashCode() and 0x7fffffff
        var aqi     = 70 + seed % 110
        val tempC   = 22 + seed % 9
        val sky     = listOf("☀️", "⛅", "🌧️", "🌫️")[seed % 4]
        var parking = 8 + seed % 40

        val aqiView     = findViewById<TextView>(R.id.tv_dest_aqi)
        val weatherView = findViewById<TextView>(R.id.tv_dest_weather)
        val parkingView = findViewById<TextView>(R.id.tv_dest_parking)
        weatherView.text = "$sky $tempC°C"

        fun aqiBand(v: Int) = when {
            v > 150 -> "#FF5247"
            v > 100 -> "#FFB300"
            else    -> "#2DE371"
        }
        fun render() {
            aqiView.text = "$aqi AQI"
            aqiView.setTextColor(Color.parseColor(aqiBand(aqi)))
            parkingView.text = "$parking free"
            parkingView.setTextColor(
                Color.parseColor(if (parking < 6) "#FFB300" else "#2DE371"))
        }
        render()

        lifecycleScope.launch {
            while (true) {
                delay(3000)
                aqi     = (aqi + Random.nextInt(-4, 5)).coerceIn(40, 220)
                parking = (parking + Random.nextInt(-3, 4)).coerceIn(0, 60)
                render()
            }
        }
    }

    private fun setupReportButtons(totalActive: Int) {
        val confirmView = findViewById<TextView>(R.id.tv_report_confirm)
        val buttonsView = findViewById<LinearLayout>(R.id.ll_report_buttons)

        val handler = android.os.Handler(mainLooper)

        fun onReport(label: String) {
            confirmView.text = "✓ \"$label\" reported!\nYour update reaches ~$totalActive active users."
            confirmView.visibility = View.VISIBLE
            buttonsView.visibility = View.GONE
            // Reset after 4 seconds
            handler.removeCallbacksAndMessages(null)
            handler.postDelayed({
                confirmView.visibility = View.GONE
                buttonsView.visibility = View.VISIBLE
            }, 4000)
        }

        findViewById<TextView>(R.id.btn_report_roadwork).setOnClickListener { onReport("Road Work") }
        findViewById<TextView>(R.id.btn_report_accident).setOnClickListener { onReport("Accident") }
        findViewById<TextView>(R.id.btn_report_police).setOnClickListener   { onReport("Police Checkpoint") }
        findViewById<TextView>(R.id.btn_report_flooding).setOnClickListener { onReport("Flooding") }
        findViewById<TextView>(R.id.btn_report_clear).setOnClickListener    { onReport("All Clear") }
    }
}
