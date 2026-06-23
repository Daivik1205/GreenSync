package com.greensync.screens

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.DividerItemDecoration
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.greensync.R
import com.greensync.models.LatLng
import com.greensync.models.Route
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

    private val ORIGIN      = LatLng(13.1007, 77.5963)
    private val DESTINATION = LatLng(12.9121, 77.5590)

    private val ROUTE_COLORS = intArrayOf(
        0xFF1A73E8.toInt(),
        0xFF34A853.toInt(),
        0xFFFBBC04.toInt(),
    )

    private val viewModel: RouteViewModel by viewModels()
    private lateinit var mapView: MapView
    private lateinit var adapter: RouteAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Configuration.getInstance().userAgentValue = packageName
        setContentView(R.layout.activity_route_selection)

        mapView = findViewById(R.id.map_view)
        mapView.setTileSource(TileSourceFactory.MAPNIK)
        mapView.setMultiTouchControls(true)
        mapView.controller.setZoom(11.0)
        mapView.controller.setCenter(GeoPoint(ORIGIN.latitude, ORIGIN.longitude))

        adapter = RouteAdapter(emptyList()) { route -> onRouteSelected(route) }
        val rv = findViewById<RecyclerView>(R.id.rv_routes)
        rv.layoutManager = LinearLayoutManager(this)
        rv.addItemDecoration(DividerItemDecoration(this, DividerItemDecoration.VERTICAL))
        rv.adapter = adapter

        observeViewModel()
        viewModel.fetchRoutes(ORIGIN, DESTINATION)
    }

    override fun onResume() {
        super.onResume()
        mapView.onResume()
    }

    override fun onPause() {
        super.onPause()
        mapView.onPause()
    }

    private fun observeViewModel() {
        lifecycleScope.launch {
            viewModel.uiState.collectLatest { state ->
                when (state) {
                    is RouteUiState.Loading -> showLoading(true)
                    is RouteUiState.Success -> {
                        showLoading(false)
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
            val color = ROUTE_COLORS.getOrElse(i) { 0xFF888888.toInt() }
            val width = if (i == 0) 12f else 8f
            val polyline = Polyline().apply {
                setPoints(route.geometry.map { GeoPoint(it.latitude, it.longitude) })
                outlinePaint.color = color
                outlinePaint.strokeWidth = width
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

    private fun onRouteSelected(route: Route) {
        viewModel.selectRoute(route)
        startActivity(HUDActivity.newIntent(this, route.id, route.summary))
    }

    private fun showLoading(show: Boolean) {
        findViewById<View>(R.id.progress_bar)?.visibility =
            if (show) View.VISIBLE else View.GONE
    }

    private class RouteAdapter(
        private var routes: List<Route>,
        private val onClick: (Route) -> Unit,
    ) : RecyclerView.Adapter<RouteAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvLabel:    TextView = view.findViewById(R.id.tv_route_label)
            val tvDistance: TextView = view.findViewById(R.id.tv_distance)
            val tvDuration: TextView = view.findViewById(R.id.tv_duration)
            val tvSummary:  TextView = view.findViewById(R.id.tv_summary)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_route, parent, false))

        override fun getItemCount() = routes.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val route = routes[position]
            holder.tvLabel.text    = "Route ${position + 1}"
            holder.tvDistance.text = "%.1f km".format(route.distanceKm)
            holder.tvDuration.text = "%.0f min".format(route.durationMin)
            holder.tvSummary.text  = route.summary
            holder.itemView.setOnClickListener { onClick(route) }
        }

        fun updateRoutes(newRoutes: List<Route>) {
            routes = newRoutes
            notifyDataSetChanged()
        }
    }
}
