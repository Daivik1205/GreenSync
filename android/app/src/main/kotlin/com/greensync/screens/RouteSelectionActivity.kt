package com.greensync.screens

import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import androidx.recyclerview.widget.DividerItemDecoration
import android.view.LayoutInflater
import android.view.ViewGroup
import android.widget.TextView
import com.google.android.gms.maps.CameraUpdateFactory
import com.google.android.gms.maps.GoogleMap
import com.google.android.gms.maps.OnMapReadyCallback
import com.google.android.gms.maps.SupportMapFragment
import com.google.android.gms.maps.model.LatLng
import com.google.android.gms.maps.model.LatLngBounds
import com.google.android.gms.maps.model.PolylineOptions
import com.greensync.R
import com.greensync.models.Route
import com.greensync.viewmodels.RouteUiState
import com.greensync.viewmodels.RouteViewModel
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.launch

/**
 * Full-screen route selection screen (phone UI).
 *
 * Shows a Google Map with 3 coloured polylines (OSRM alternatives) and
 * a bottom RecyclerView with route cards. Tapping a card:
 *   1. Highlights that route on the map.
 *   2. Calls RouteViewModel.selectRoute() → publishes MQTT intent.
 *   3. Opens HUDActivity with the selected route.
 *
 * The Android Auto equivalent is RouteSelectionCarScreen.kt.
 */
class RouteSelectionActivity : AppCompatActivity(), OnMapReadyCallback {

    // Hardcoded demo: Yelahanka → Mysore Road (Bengaluru corridor)
    private val ORIGIN      = LatLng(13.1007, 77.5963)
    private val DESTINATION = LatLng(12.9121, 77.5590)

    private val ROUTE_COLORS = intArrayOf(
        0xFF1A73E8.toInt(),   // blue   — route 0
        0xFF34A853.toInt(),   // green  — route 1
        0xFFFBBC04.toInt(),   // yellow — route 2
    )

    private val viewModel: RouteViewModel by viewModels()
    private var googleMap: GoogleMap? = null
    private lateinit var adapter: RouteAdapter

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_route_selection)

        val mapFragment = supportFragmentManager
            .findFragmentById(R.id.map_fragment) as SupportMapFragment
        mapFragment.getMapAsync(this)

        adapter = RouteAdapter(emptyList()) { route ->
            onRouteSelected(route)
        }
        val rv = findViewById<RecyclerView>(R.id.rv_routes)
        rv.layoutManager = LinearLayoutManager(this)
        rv.addItemDecoration(DividerItemDecoration(this, DividerItemDecoration.VERTICAL))
        rv.adapter = adapter

        observeViewModel()
    }

    override fun onMapReady(map: GoogleMap) {
        googleMap = map
        map.moveCamera(CameraUpdateFactory.newLatLngZoom(ORIGIN, 11f))
        viewModel.fetchRoutes(ORIGIN, DESTINATION)
    }

    // ── Observation ───────────────────────────────────────────────────────────

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

    // ── Map drawing ───────────────────────────────────────────────────────────

    private fun drawRoutes(routes: List<Route>) {
        val map = googleMap ?: return
        map.clear()
        val boundsBuilder = LatLngBounds.Builder()

        routes.forEachIndexed { i, route ->
            val color = ROUTE_COLORS.getOrElse(i) { 0xFF888888.toInt() }
            val width = if (i == 0) 12f else 8f
            map.addPolyline(
                PolylineOptions()
                    .addAll(route.geometry)
                    .color(color)
                    .width(width)
                    .zIndex(if (i == 0) 2f else 1f)
            )
            route.geometry.forEach { boundsBuilder.include(it) }
        }

        try {
            map.animateCamera(CameraUpdateFactory.newLatLngBounds(boundsBuilder.build(), 80))
        } catch (e: Exception) { /* bounds invalid on tiny screens */ }
    }

    // ── Selection ─────────────────────────────────────────────────────────────

    private fun onRouteSelected(route: Route) {
        viewModel.selectRoute(route)
        startActivity(HUDActivity.newIntent(this, route.id, route.summary))
    }

    private fun showLoading(show: Boolean) {
        findViewById<View>(R.id.progress_bar)?.visibility = if (show) View.VISIBLE else View.GONE
    }

    // ── Adapter ───────────────────────────────────────────────────────────────

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
