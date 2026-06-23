package com.greensync.screens

import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
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

class RouteSelectionActivity : AppCompatActivity() {

    companion object {
        val ORIGIN = LatLng(13.1007, 77.5963)

        val MOCK_USER_COUNTS = intArrayOf(312, 89, 641)

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
    }

    private val viewModel: RouteViewModel by viewModels()
    private lateinit var mapView: MapView
    private lateinit var adapter: RouteAdapter
    private var currentRoutes: List<Route> = emptyList()

    private lateinit var destName: String
    private lateinit var destination: LatLng

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_route_selection)

        destName    = intent.getStringExtra(EXTRA_DEST_NAME) ?: "Destination"
        val destLat = intent.getDoubleExtra(EXTRA_DEST_LAT, 12.9121)
        val destLng = intent.getDoubleExtra(EXTRA_DEST_LNG, 77.5590)
        destination = LatLng(destLat, destLng)

        // Header: "Yelahanka → Office"
        findViewById<TextView>(R.id.tv_route_header).text =
            "Yelahanka  →  $destName"

        mapView = findViewById(R.id.map_view)
        mapView.setTileSource(TileSourceFactory.MAPNIK)
        mapView.setMultiTouchControls(true)
        mapView.controller.setZoom(11.0)
        mapView.controller.setCenter(GeoPoint(ORIGIN.latitude, ORIGIN.longitude))

        val totalUsers = MOCK_USER_COUNTS.sum()
        findViewById<TextView>(R.id.tv_total_users).text = "$totalUsers users tracked"

        adapter = RouteAdapter(emptyList(), destName) { route, index ->
            onRouteSelected(route, index)
        }
        val rv = findViewById<RecyclerView>(R.id.rv_routes)
        rv.layoutManager = LinearLayoutManager(this)
        rv.adapter = adapter

        observeViewModel()
        viewModel.fetchRoutes(ORIGIN, destination)
    }

    override fun onResume() { super.onResume(); mapView.onResume() }
    override fun onPause()  { super.onPause();  mapView.onPause()  }

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
            val count = MOCK_USER_COUNTS.getOrElse(i) { 100 }
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
        val userCount = MOCK_USER_COUNTS.getOrElse(index) { 100 }
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
                allCounts   = MOCK_USER_COUNTS,
                destName    = destName,
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
        private val destName: String,
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
            val tvUsers:     TextView    = view.findViewById(R.id.tv_user_count)
            val pbBar:       ProgressBar = view.findViewById(R.id.pb_congestion)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_route, parent, false))

        override fun getItemCount() = routes.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val route = routes[position]
            val count = MOCK_USER_COUNTS.getOrElse(position) { 100 }
            val color = congestionColor(count)
            val label = congestionLabel(count)
            val icon  = congestionIcon(count)
            val eta   = adjustedEta(route.durationMin, count)
            val speed = expectedSpeed(count)

            // Is this the least-congested (recommended) route?
            val bestIdx = MOCK_USER_COUNTS.indices.minByOrNull { MOCK_USER_COUNTS[it] } ?: -1
            val isRecommended = position == bestIdx

            holder.strip.setBackgroundColor(color)
            holder.tvLabel.text = "Route ${position + 1}"
            holder.tvBadge.text = "$icon  $label"
            holder.tvBadge.backgroundTintList = ColorStateList.valueOf(color)

            holder.tvRecommend.visibility = if (isRecommended) View.VISIBLE else View.GONE

            holder.tvEta.text   = "~$eta min"
            holder.tvSpeed.text = "~$speed km/h avg"

            holder.tvDetails.text = "%.1f km  ·  ~%.0f min base".format(route.distanceKm, route.durationMin)
            holder.tvSummary.text = route.summary.ifBlank { "Route ${position + 1}" }
            holder.tvUsers.text   = "👥 $count users  "
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
