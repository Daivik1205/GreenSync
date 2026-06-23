package com.greensync.screens

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
import kotlin.random.Random

class RouteSelectionActivity : AppCompatActivity() {

    companion object {
        // Yelahanka fallback used when no GPS fix is available
        val ORIGIN = LatLng(13.1007, 77.5963)
        val MOCK_USER_COUNTS = intArrayOf(312, 89, 641)

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
            count > 500 -> Color.parseColor("#E53935")
            count > 150 -> Color.parseColor("#FB8C00")
            else        -> Color.parseColor("#43A047")
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

        // grams CO₂ per km at this congestion level
        private fun co2PerKm(count: Int) = when {
            count > 500 -> 180
            count > 150 -> 130
            else        -> 90
        }

        fun ecoLabel(distKm: Double, count: Int, counts: IntArray): String? {
            val thisCo2  = co2PerKm(count) * distKm
            val worstCo2 = counts.maxOf { co2PerKm(it) } * distKm
            val savedKg  = (worstCo2 - thisCo2) / 1000.0
            return if (savedKg > 0.05) "🍃  Saves ~%.1f kg CO₂ vs worst route".format(savedKg) else null
        }
    }

    private val viewModel: RouteViewModel by viewModels()
    private lateinit var mapView: MapView
    private lateinit var adapter: RouteAdapter
    private var currentRoutes: List<Route> = emptyList()

    private lateinit var destName: String
    private lateinit var destination: LatLng
    private lateinit var origin: LatLng
    private lateinit var originName: String

    // Live crowd simulation
    private val liveCounts = MOCK_USER_COUNTS.copyOf()
    private val liveHandler = Handler(Looper.getMainLooper())
    private var tickerAlertIdx = 0
    private val liveRunnable = object : Runnable {
        override fun run() {
            for (i in liveCounts.indices) {
                liveCounts[i] = (liveCounts[i] + Random.nextInt(-8, 9)).coerceAtLeast(10)
            }
            adapter.notifyDataSetChanged()
            val totalUsers = liveCounts.sum()
            findViewById<TextView>(R.id.tv_total_users).text = "$totalUsers users tracked"
            updateTicker()
            liveHandler.postDelayed(this, 7000)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_route_selection)

        destName   = intent.getStringExtra(EXTRA_DEST_NAME)   ?: "Destination"
        originName = intent.getStringExtra(EXTRA_ORIGIN_NAME) ?: "Yelahanka"
        val destLat   = intent.getDoubleExtra(EXTRA_DEST_LAT,   12.9121)
        val destLng   = intent.getDoubleExtra(EXTRA_DEST_LNG,   77.5590)
        val originLat = intent.getDoubleExtra(EXTRA_ORIGIN_LAT, ORIGIN.latitude)
        val originLng = intent.getDoubleExtra(EXTRA_ORIGIN_LNG, ORIGIN.longitude)
        destination   = LatLng(destLat, destLng)
        origin        = LatLng(originLat, originLng)

        findViewById<TextView>(R.id.tv_route_header).text = "$originName  →  $destName"

        mapView = findViewById(R.id.map_view)
        mapView.setTileSource(TileSourceFactory.MAPNIK)
        mapView.setMultiTouchControls(true)
        mapView.controller.setZoom(11.0)
        mapView.controller.setCenter(GeoPoint(origin.latitude, origin.longitude))

        findViewById<TextView>(R.id.tv_total_users).text = "${liveCounts.sum()} users tracked"

        // Ticker — needs isSelected=true to run marquee
        val ticker = findViewById<TextView>(R.id.tv_ticker)
        ticker.isSelected = true
        updateTicker()

        adapter = RouteAdapter(emptyList(), liveCounts) { route, index ->
            onRouteSelected(route, index)
        }
        val rv = findViewById<RecyclerView>(R.id.rv_routes)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        observeViewModel()
        viewModel.fetchRoutes(origin, destination)
    }

    override fun onResume() {
        super.onResume()
        mapView.onResume()
        liveHandler.postDelayed(liveRunnable, 7000)
    }

    override fun onPause() {
        super.onPause()
        mapView.onPause()
        liveHandler.removeCallbacks(liveRunnable)
    }

    private fun updateTicker() {
        val msg = TICKER_ALERTS[tickerAlertIdx % TICKER_ALERTS.size]
        tickerAlertIdx++
        val next = TICKER_ALERTS[tickerAlertIdx % TICKER_ALERTS.size]
        val ticker = findViewById<TextView>(R.id.tv_ticker)
        ticker.text = "$msg        ·        $next        ·        ${TICKER_ALERTS[(tickerAlertIdx + 1) % TICKER_ALERTS.size]}"
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
                        adapter.updateRoutes(state.routes)
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
            val polyline = Polyline().apply {
                setPoints(route.geometry.map { GeoPoint(it.latitude, it.longitude) })
                outlinePaint.color = color
                outlinePaint.strokeWidth = width
                outlinePaint.alpha = 200
            }
            mapView.overlays.add(polyline)
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

    private fun onRouteSelected(route: Route, index: Int) {
        val userCount = liveCounts.getOrElse(index) { 100 }
        val eta       = adjustedEta(route.durationMin, userCount)
        val speed     = expectedSpeed(userCount)
        viewModel.selectRoute(route)
        startActivity(
            HUDActivity.newIntent(
                context     = this,
                routeId     = route.id,
                summary     = route.summary,
                selectedIdx = index,
                userCount   = userCount,
                allCounts   = liveCounts,
                destName    = destName,
                originName  = originName,
                adjustedEta = eta,
                speed       = speed,
                distanceKm  = route.distanceKm,
            )
        )
    }

    private fun showLoading(show: Boolean) {
        findViewById<View>(R.id.progress_bar)?.visibility =
            if (show) View.VISIBLE else View.GONE
    }

    private class RouteAdapter(
        private var routes: List<Route>,
        private val liveCounts: IntArray,
        private val onClick: (Route, Int) -> Unit,
    ) : RecyclerView.Adapter<RouteAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val strip:       View        = view.findViewById(R.id.congestion_strip)
            val tvLabel:     TextView    = view.findViewById(R.id.tv_route_label)
            val tvBadge:     TextView    = view.findViewById(R.id.tv_congestion_badge)
            val tvRecommend: TextView    = view.findViewById(R.id.tv_recommended)
            val tvEta:       TextView    = view.findViewById(R.id.tv_eta)
            val tvSpeed:     TextView    = view.findViewById(R.id.tv_speed)
            val tvDetails:   TextView    = view.findViewById(R.id.tv_details)
            val tvSummary:   TextView    = view.findViewById(R.id.tv_summary)
            val tvEco:       TextView    = view.findViewById(R.id.tv_eco)
            val tvUsers:     TextView    = view.findViewById(R.id.tv_user_count)
            val pbBar:       ProgressBar = view.findViewById(R.id.pb_congestion)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_route, parent, false))

        override fun getItemCount() = routes.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val route = routes[position]
            val count = liveCounts.getOrElse(position) { 100 }
            val color = congestionColor(count)
            val label = congestionLabel(count)
            val icon  = congestionIcon(count)
            val eta   = adjustedEta(route.durationMin, count)
            val speed = expectedSpeed(count)

            val bestIdx       = liveCounts.indices.minByOrNull { liveCounts[it] } ?: -1
            val isRecommended = position == bestIdx

            holder.strip.setBackgroundColor(color)
            holder.tvLabel.text = "Route ${position + 1}"
            holder.tvBadge.text = "$icon  $label"
            holder.tvBadge.backgroundTintList = ColorStateList.valueOf(color)
            holder.tvRecommend.visibility = if (isRecommended) View.VISIBLE else View.GONE
            holder.tvEta.text   = "~$eta min"
            holder.tvSpeed.text = "~$speed km/h avg"
            holder.tvDetails.text  = "%.1f km  ·  base ~%.0f min".format(route.distanceKm, route.durationMin)
            holder.tvSummary.text  = route.summary.ifBlank { "Route ${position + 1}" }

            val ecoText = ecoLabel(route.distanceKm, count, liveCounts)
            holder.tvEco.text       = ecoText ?: ""
            holder.tvEco.visibility = if (ecoText != null) View.VISIBLE else View.GONE

            holder.tvUsers.text   = "👥 $count active  "
            holder.pbBar.progress = congestionProgress(count)
            holder.pbBar.progressTintList = ColorStateList.valueOf(color)

            holder.itemView.setOnClickListener { onClick(route, position) }
        }

        fun updateRoutes(newRoutes: List<Route>) {
            routes = newRoutes
            notifyDataSetChanged()
        }
    }
}
