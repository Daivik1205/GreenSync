package com.greensync.screens

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomsheet.BottomSheetDialog
import com.greensync.R
import com.greensync.models.LatLng
import com.greensync.models.Route
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_DEST_LAT
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_DEST_LNG
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_DEST_NAME
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_ORIGIN_LAT
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_ORIGIN_LNG
import com.greensync.screens.DestinationPickerActivity.Companion.EXTRA_ORIGIN_NAME
import com.greensync.viewmodels.RouteUiState
import com.greensync.viewmodels.RouteViewModel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.BoundingBox
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Polyline
import kotlin.math.roundToInt
import kotlin.random.Random

class RouteSelectionActivity : AppCompatActivity() {

    enum class Mode { BALANCED, FASTEST, GREENEST, SMOOTHEST }

    companion object {
        val ORIGIN = LatLng(13.1007, 77.5963)
        val MOCK_USER_COUNTS = intArrayOf(312, 89, 641)

        private const val PREFS       = "greensync_prefs"
        private const val KEY_POINTS  = "green_points"

        private val TICKER_ALERTS = listOf(
            "⚠️  Priya reported minor accident near Hebbal overpass",
            "🚧  Road work active on Outer Ring Road exit 12",
            "👮  Police checkpoint at Silk Board junction",
            "✅  NH44 corridor — all clear, signals updated",
            "🌊  Minor waterlogging reported near KR Puram bridge",
            "🚦  Signal down at Tin Factory junction — expect delays",
            "🟢  12 users just switched from Route 3 to Route 2",
            "⚠️  Rahul flagged pothole near Hebbal flyover",
            "✅  Expressway ramp open — Route 2 moving well",
        )

        fun congestionLabel(count: Int) = when {
            count > 500 -> "HIGH"
            count > 150 -> "MEDIUM"
            else        -> "LOW"
        }

        fun congestionColor(count: Int) = when {
            count > 500 -> Color.parseColor("#FF5247")
            count > 150 -> Color.parseColor("#FFB300")
            else        -> Color.parseColor("#2DE371")
        }

        fun congestionIcon(count: Int) = when {
            count > 500 -> "🔴"
            count > 150 -> "🟡"
            else        -> "🟢"
        }

        fun congestionProgress(count: Int): Int {
            val max = MOCK_USER_COUNTS.max()
            return ((count.toFloat() / max) * 100).toInt()
        }

        fun adjustedEta(rawMin: Double, count: Int): Int = (rawMin * when {
            count > 500 -> 1.8
            count > 150 -> 1.3
            else        -> 1.0
        }).toInt()

        fun expectedSpeed(count: Int) = when {
            count > 500 -> 16
            count > 150 -> 28
            else        -> 45
        }

        private fun co2PerKm(count: Int) = when {
            count > 500 -> 180
            count > 150 -> 130
            else        -> 90
        }

        fun co2Grams(distKm: Double, count: Int) = co2PerKm(count) * distKm

        fun ecoSavedKg(distKm: Double, count: Int, counts: IntArray): Double {
            val worst = counts.maxOf { co2PerKm(it) } * distKm
            return (worst - co2Grams(distKm, count)) / 1000.0
        }

        /** Total signals along a route + how many GreenSync has synced into a green wave. */
        fun signals(distKm: Double, count: Int): Pair<Int, Int> {
            val total = (distKm / 2.0).roundToInt().coerceIn(4, 9)
            val frac  = when { count > 500 -> 0.30; count > 150 -> 0.60; else -> 0.90 }
            val synced = (total * frac).roundToInt().coerceIn(1, total)
            return synced to total
        }

        /** Reward for taking a route that helps balance the network — clearer = more. */
        fun greenPoints(count: Int, counts: IntArray): Int {
            val maxC = counts.max()
            return 5 + ((maxC - count) / 18)
        }
    }

    private val viewModel: RouteViewModel by viewModels()
    private lateinit var mapView: MapView
    private lateinit var adapter: RouteAdapter

    private lateinit var destName: String
    private lateinit var destination: LatLng
    private lateinit var origin: LatLng
    private lateinit var originName: String

    private lateinit var prefs: android.content.SharedPreferences
    private var mode = Mode.BALANCED
    private var currentRoutes: List<Route> = emptyList()
    private var networkOptimal = 73

    private val liveCounts = MOCK_USER_COUNTS.copyOf()
    private val liveHandler = Handler(Looper.getMainLooper())
    private var tickerAlertIdx = 0
    private val liveRunnable = object : Runnable {
        override fun run() {
            for (i in liveCounts.indices) {
                liveCounts[i] = (liveCounts[i] + Random.nextInt(-8, 9)).coerceAtLeast(10)
            }
            networkOptimal = (networkOptimal + Random.nextInt(-2, 3)).coerceIn(64, 88)
            adapter.notifyDataSetChanged()
            updateMeta()
            updateTicker()
            liveHandler.postDelayed(this, 7000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_route_selection)

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        destName   = intent.getStringExtra(EXTRA_DEST_NAME)   ?: "Destination"
        originName = intent.getStringExtra(EXTRA_ORIGIN_NAME) ?: "Yelahanka"
        val destLat   = intent.getDoubleExtra(EXTRA_DEST_LAT,   12.9121)
        val destLng   = intent.getDoubleExtra(EXTRA_DEST_LNG,   77.5590)
        val originLat = intent.getDoubleExtra(EXTRA_ORIGIN_LAT, ORIGIN.latitude)
        val originLng = intent.getDoubleExtra(EXTRA_ORIGIN_LNG, ORIGIN.longitude)
        destination   = LatLng(destLat, destLng)
        origin        = LatLng(originLat, originLng)

        findViewById<TextView>(R.id.tv_route_header).text = "$originName → $destName"

        mapView = findViewById(R.id.map_view)
        mapView.setTileSource(TileSourceFactory.MAPNIK)
        mapView.setMultiTouchControls(true)
        mapView.controller.setZoom(11.0)
        mapView.controller.setCenter(GeoPoint(origin.latitude, origin.longitude))

        val ticker = findViewById<TextView>(R.id.tv_ticker)
        ticker.isSelected = true
        updateTicker()

        adapter = RouteAdapter(emptyList(), liveCounts) { card -> showCommitSheet(card) }
        findViewById<RecyclerView>(R.id.rv_routes).apply {
            layoutManager = LinearLayoutManager(this@RouteSelectionActivity)
            adapter = this@RouteSelectionActivity.adapter
        }

        setupModeChips()
        updateMeta()
        observeViewModel()
        viewModel.fetchRoutes(origin, destination)
    }

    override fun onResume() {
        super.onResume()
        mapView.onResume()
        renderPoints()
        liveHandler.postDelayed(liveRunnable, 7000)
    }

    override fun onPause() {
        super.onPause()
        mapView.onPause()
        liveHandler.removeCallbacks(liveRunnable)
    }

    // ── Header meta ─────────────────────────────────────────────────────────

    private fun renderPoints() {
        val pts = prefs.getInt(KEY_POINTS, 1180)
        findViewById<TextView>(R.id.tv_green_points).text = "⬢ %,d".format(pts)
    }

    private fun updateMeta() {
        findViewById<TextView>(R.id.tv_network_status).text =
            "◇ NETWORK $networkOptimal% OPTIMAL · ${liveCounts.size} routes balanced"
        findViewById<TextView>(R.id.tv_total_users).text =
            "%,d commuters live on these routes".format(liveCounts.sum())
        renderPoints()
    }

    // ── Mode chips ──────────────────────────────────────────────────────────

    private fun setupModeChips() {
        val chips = mapOf(
            Mode.BALANCED  to R.id.chip_balanced,
            Mode.FASTEST   to R.id.chip_fastest,
            Mode.GREENEST  to R.id.chip_greenest,
            Mode.SMOOTHEST to R.id.chip_smoothest,
        )
        chips.forEach { (m, id) ->
            findViewById<TextView>(id).setOnClickListener {
                mode = m
                styleChips(chips)
                applyMode()
            }
        }
        styleChips(chips)
    }

    private fun styleChips(chips: Map<Mode, Int>) {
        chips.forEach { (m, id) ->
            val selected = m == mode
            val chip = findViewById<TextView>(id)
            chip.backgroundTintList = ColorStateList.valueOf(
                Color.parseColor(if (selected) "#13301E" else "#1B241D"))
            chip.setTextColor(Color.parseColor(if (selected) "#2DE371" else "#8B978C"))
        }
    }

    private fun rankedCards(): List<RouteCard> {
        val indices = currentRoutes.indices.toList()
        val sorted = when (mode) {
            Mode.FASTEST -> indices.sortedBy {
                adjustedEta(currentRoutes[it].durationMin, liveCounts.getOrElse(it){100})
            }
            Mode.GREENEST -> indices.sortedBy {
                co2Grams(currentRoutes[it].distanceKm, liveCounts.getOrElse(it){100})
            }
            Mode.SMOOTHEST -> indices.sortedByDescending {
                signals(currentRoutes[it].distanceKm, liveCounts.getOrElse(it){100}).first
            }
            Mode.BALANCED -> indices.sortedBy {
                val c = liveCounts.getOrElse(it){100}
                val r = currentRoutes[it]
                val (synced, total) = signals(r.distanceKm, c)
                adjustedEta(r.durationMin, c) + c * 0.04 + (total - synced) * 1.5
            }
        }
        return sorted.map { RouteCard(currentRoutes[it], it + 1) }
    }

    private fun applyMode() {
        if (currentRoutes.isNotEmpty()) adapter.submit(rankedCards(), mode)
    }

    // ── Live ticker ─────────────────────────────────────────────────────────

    private fun updateTicker() {
        val a = TICKER_ALERTS[tickerAlertIdx % TICKER_ALERTS.size]
        tickerAlertIdx++
        val b = TICKER_ALERTS[tickerAlertIdx % TICKER_ALERTS.size]
        val c = TICKER_ALERTS[(tickerAlertIdx + 1) % TICKER_ALERTS.size]
        findViewById<TextView>(R.id.tv_ticker).text = "$a        ·        $b        ·        $c"
    }

    private fun observeViewModel() {
        lifecycleScope.launch {
            viewModel.uiState.collectLatest { state ->
                when (state) {
                    is RouteUiState.Loading -> showLoading(true)
                    is RouteUiState.Success -> {
                        showLoading(false)
                        currentRoutes = state.routes
                        drawRoutes(state.routes)
                        applyMode()
                    }
                    is RouteUiState.Error -> {
                        showLoading(false)
                        Toast.makeText(this@RouteSelectionActivity, state.message, Toast.LENGTH_LONG).show()
                    }
                    else -> Unit
                }
            }
        }
    }

    private fun drawRoutes(routes: List<Route>) {
        mapView.overlays.clear()
        var minLat = Double.MAX_VALUE; var maxLat = -Double.MAX_VALUE
        var minLon = Double.MAX_VALUE; var maxLon = -Double.MAX_VALUE

        routes.forEachIndexed { i, route ->
            val count = liveCounts.getOrElse(i) { 100 }
            val color = congestionColor(count)
            val width = when {
                count > 500 -> 16f
                count > 150 -> 10f
                else        -> 6f
            }
            mapView.overlays.add(Polyline().apply {
                setPoints(route.geometry.map { GeoPoint(it.latitude, it.longitude) })
                outlinePaint.color = color
                outlinePaint.strokeWidth = width
                outlinePaint.alpha = 200
            })
            route.geometry.forEach { pt ->
                if (pt.latitude  < minLat) minLat = pt.latitude
                if (pt.latitude  > maxLat) maxLat = pt.latitude
                if (pt.longitude < minLon) minLon = pt.longitude
                if (pt.longitude > maxLon) maxLon = pt.longitude
            }
        }
        if (minLat < Double.MAX_VALUE) {
            val box = BoundingBox(maxLat, maxLon, minLat, minLon)
            mapView.post { mapView.zoomToBoundingBox(box, true, 80) }
        }
        mapView.invalidate()
    }

    // ── Commit-intent bottom sheet ──────────────────────────────────────────

    private fun showCommitSheet(card: RouteCard) {
        val idx   = card.routeNo - 1
        val route = card.route
        val count = liveCounts.getOrElse(idx) { 100 }
        val eta   = adjustedEta(route.durationMin, count)
        val speed = expectedSpeed(count)
        val (synced, total) = signals(route.distanceKm, count)
        val savedKg = ecoSavedKg(route.distanceKm, count, liveCounts)
        val pts     = greenPoints(count, liveCounts)

        val sheet = BottomSheetDialog(this)
        val v = layoutInflater.inflate(R.layout.sheet_commit, null)
        sheet.setContentView(v)

        v.findViewById<TextView>(R.id.tv_sheet_title).text =
            "Route ${card.routeNo} · ${route.summary.ifBlank { "via city roads" }}"
        v.findViewById<TextView>(R.id.tv_sheet_eta).text =
            "~$eta min  ·  ~$speed km/h  ·  %.1f km".format(route.distanceKm)
        v.findViewById<TextView>(R.id.tv_impact_help).text =
            "📡  Your intent helps $count commuters behind you reroute smarter"
        v.findViewById<TextView>(R.id.tv_impact_signals).text =
            "🚦  $synced/$total signals will green-wave to your arrival"

        val ecoView = v.findViewById<TextView>(R.id.tv_impact_eco)
        ecoView.text = if (savedKg > 0.05)
            "🍃  Saves ~%.1f kg CO₂ vs the busiest route".format(savedKg)
        else
            "🍃  Standard emissions on this corridor"

        val bal = prefs.getInt(KEY_POINTS, 1180)
        v.findViewById<TextView>(R.id.tv_reward_line).text =
            "Earns +$pts GreenPoints · balance becomes %,d".format(bal + pts)

        val broadcasting = v.findViewById<TextView>(R.id.tv_broadcasting)
        val btn = v.findViewById<TextView>(R.id.btn_commit)
        btn.setOnClickListener {
            btn.isEnabled = false
            btn.alpha = 0.5f
            broadcasting.visibility = View.VISIBLE
            broadcasting.text = "📡 Broadcasting intent to $count commuters…"
            // Award points
            prefs.edit().putInt(KEY_POINTS, bal + pts).apply()
            Handler(Looper.getMainLooper()).postDelayed({
                broadcasting.text = "✓ Intent committed — network rebalancing"
                Handler(Looper.getMainLooper()).postDelayed({
                    sheet.dismiss()
                    launchHud(card, eta, speed)
                }, 700)
            }, 1300)
        }
        sheet.show()
    }

    private fun launchHud(card: RouteCard, eta: Int, speed: Int) {
        val idx = card.routeNo - 1
        viewModel.selectRoute(card.route)
        startActivity(
            HUDActivity.newIntent(
                context     = this,
                routeId     = card.route.id,
                summary     = card.route.summary,
                selectedIdx = idx,
                userCount   = liveCounts.getOrElse(idx) { 100 },
                allCounts   = liveCounts,
                destName    = destName,
                originName  = originName,
                adjustedEta = eta,
                speed       = speed,
                distanceKm  = card.route.distanceKm,
            )
        )
    }

    private fun showLoading(show: Boolean) {
        findViewById<View>(R.id.progress_bar)?.visibility =
            if (show) View.VISIBLE else View.GONE
    }

    // ── Adapter ─────────────────────────────────────────────────────────────

    data class RouteCard(val route: Route, val routeNo: Int)

    private class RouteAdapter(
        private var cards: List<RouteCard>,
        private val liveCounts: IntArray,
        private val onSelect: (RouteCard) -> Unit,
    ) : RecyclerView.Adapter<RouteAdapter.VH>() {

        private var mode = Mode.BALANCED

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val strip:   View        = view.findViewById(R.id.congestion_strip)
            val label:   TextView    = view.findViewById(R.id.tv_route_label)
            val rank:    TextView    = view.findViewById(R.id.tv_rank)
            val eta:     TextView    = view.findViewById(R.id.tv_eta)
            val trend:   TextView    = view.findViewById(R.id.tv_trend)
            val badge:   TextView    = view.findViewById(R.id.tv_congestion_badge)
            val speed:   TextView    = view.findViewById(R.id.tv_speed)
            val details: TextView    = view.findViewById(R.id.tv_details)
            val signals: TextView    = view.findViewById(R.id.tv_signals)
            val pb:      ProgressBar = view.findViewById(R.id.pb_congestion)
            val why:     TextView    = view.findViewById(R.id.tv_why)
            val eco:     TextView    = view.findViewById(R.id.tv_eco)
            val points:  TextView    = view.findViewById(R.id.tv_points)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_route, parent, false))

        override fun getItemCount() = cards.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val card  = cards[position]
            val idx   = card.routeNo - 1
            val count = liveCounts.getOrElse(idx) { 100 }
            val color = congestionColor(count)
            val eta   = adjustedEta(card.route.durationMin, count)
            val speed = expectedSpeed(count)
            val (synced, total) = signals(card.route.distanceKm, count)
            val pts   = greenPoints(count, liveCounts)
            val isPick = position == 0

            holder.strip.setBackgroundColor(color)
            holder.label.text = "ROUTE ${card.routeNo}  ·  ${card.route.summary.ifBlank { "city roads" }}"

            holder.rank.text = if (isPick) "✦ GREENSYNC PICK" else "#${position + 1}"
            holder.rank.backgroundTintList = ColorStateList.valueOf(
                if (isPick) color else Color.parseColor("#1B241D"))
            holder.rank.setTextColor(
                if (isPick) Color.parseColor("#0A0F0C") else Color.parseColor("#8B978C"))

            holder.eta.text = "$eta min"

            val (trendText, trendColor) = when {
                count > 500 -> "▲ filling fast" to Color.parseColor("#FF5247")
                count > 150 -> "▬ steady"       to Color.parseColor("#FFB300")
                else        -> "▼ clearing"     to Color.parseColor("#2DE371")
            }
            holder.trend.text = trendText
            holder.trend.setTextColor(trendColor)

            holder.badge.text = "${congestionIcon(count)} ${congestionLabel(count)}"
            holder.badge.backgroundTintList = ColorStateList.valueOf(color)

            holder.speed.text   = "🚗 $speed km/h"
            holder.details.text = "📏 %.1f km".format(card.route.distanceKm)
            holder.signals.text = "🚦 $synced/$total synced"

            holder.pb.progress = congestionProgress(count)
            holder.pb.progressTintList = ColorStateList.valueOf(color)

            holder.why.text = when {
                count > 500 -> "$count cars committed ahead — heavy load, expect stop-go"
                count > 150 -> "$count committed ahead — moderate, steady flow"
                else        -> "only $count committed — clear corridor, green wave on"
            }

            val savedKg = ecoSavedKg(card.route.distanceKm, count, liveCounts)
            holder.eco.text = if (savedKg > 0.05) "🍃 −%.1f kg CO₂".format(savedKg) else "🍃 baseline"
            holder.points.text = "+$pts pts"

            holder.itemView.setOnClickListener { onSelect(card) }
        }

        fun submit(newCards: List<RouteCard>, newMode: Mode) {
            cards = newCards
            mode = newMode
            notifyDataSetChanged()
        }
    }
}
