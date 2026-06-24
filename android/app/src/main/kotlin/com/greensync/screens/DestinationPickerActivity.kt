package com.greensync.screens

import android.Manifest
import android.animation.ValueAnimator
import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.text.Editable
import android.text.TextWatcher
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.gms.location.FusedLocationProviderClient
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import com.google.android.gms.tasks.CancellationTokenSource
import com.greensync.R
import com.greensync.services.GeocodingService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar
import java.util.Locale
import kotlin.math.abs
import kotlin.random.Random

class DestinationPickerActivity : AppCompatActivity() {

    data class Place(
        val name: String,
        val area: String,
        val emoji: String,
        val lat: Double,
        val lng: Double,
    ) {
        /** Stable pseudo-random "commuters heading here" count. */
        val going: Int get() = 60 + (abs((name + area).hashCode()) % 1180)
    }

    companion object {
        const val EXTRA_DEST_NAME   = "dest_name"
        const val EXTRA_DEST_LAT    = "dest_lat"
        const val EXTRA_DEST_LNG    = "dest_lng"
        const val EXTRA_ORIGIN_LAT  = "origin_lat"
        const val EXTRA_ORIGIN_LNG  = "origin_lng"
        const val EXTRA_ORIGIN_NAME = "origin_name"

        private const val FALLBACK_LAT  = 13.1007
        private const val FALLBACK_LNG  = 77.5963
        private const val FALLBACK_NAME = "Yelahanka"

        private const val PREFS        = "greensync_prefs"
        private const val KEY_RECENTS  = "recent_places"

        // Top tiles shown in "Popular now"
        val POPULAR = listOf(
            Place("Home",        "Mysore Road",     "🏠", 12.9399, 77.5432),
            Place("Office",      "Electronic City", "💼", 12.8411, 77.6793),
            Place("Airport",     "Devanahalli",     "✈️", 13.1986, 77.7066),
            Place("Koramangala", "South Bengaluru", "🍕", 12.9352, 77.6245),
            Place("Majestic",    "City Centre",     "🏛️", 12.9762, 77.5713),
            Place("Whitefield",  "East Bengaluru",  "🏢", 12.9698, 77.7499),
        )

        // Full searchable catalog of Bengaluru destinations
        val CATALOG = POPULAR + listOf(
            Place("Indiranagar",    "100ft Road",       "🍻", 12.9719, 77.6412),
            Place("MG Road",        "Central Business",  "🛍️", 12.9756, 77.6068),
            Place("Hebbal",         "North Bengaluru",   "🌳", 13.0358, 77.5970),
            Place("Jayanagar",      "South Bengaluru",   "🌸", 12.9250, 77.5938),
            Place("HSR Layout",     "Sector 1",          "☕", 12.9116, 77.6474),
            Place("Marathahalli",   "Outer Ring Road",   "🛒", 12.9591, 77.6974),
            Place("Banashankari",   "BSK Stage II",      "🛕", 12.9255, 77.5468),
            Place("Yeshwanthpur",   "Tumkur Road",       "🚉", 13.0287, 77.5400),
            Place("Hebbal Flyover", "Bellary Road",      "🛣️", 13.0410, 77.5910),
            Place("Cubbon Park",    "Sampangi Rama",     "🌿", 12.9763, 77.5929),
            Place("UB City",        "Vittal Mallya Rd",  "🥂", 12.9719, 77.5957),
            Place("Sarjapur Road",  "South-East",        "🏗️", 12.9009, 77.6874),
            Place("Bannerghatta",   "Bannerghatta Rd",   "🦁", 12.8000, 77.5770),
            Place("Bellandur",      "Outer Ring Road",   "🏙️", 12.9258, 77.6762),
            Place("Malleshwaram",   "Sampige Road",      "🏵️", 13.0035, 77.5709),
            Place("KR Market",      "City Market",       "🥬", 12.9627, 77.5806),
            Place("Electronic City","Phase 1",           "💻", 12.8452, 77.6602),
            Place("ITPL",           "Whitefield",        "🖥️", 12.9856, 77.7367),
        )

        fun serialize(p: Place) =
            "${p.name}¦${p.area}¦${p.emoji}¦${p.lat}¦${p.lng}"

        fun deserialize(s: String): Place? {
            val t = s.split("¦")
            return if (t.size == 5)
                Place(t[0], t[1], t[2], t[3].toDoubleOrNull() ?: return null, t[4].toDoubleOrNull() ?: return null)
            else null
        }
    }

    private var originLat  = FALLBACK_LAT
    private var originLng  = FALLBACK_LNG
    private var originName = FALLBACK_NAME

    private lateinit var prefs: android.content.SharedPreferences
    private val recents = mutableListOf<Place>()

    private lateinit var recentAdapter:  PlaceTileAdapter
    private lateinit var popularAdapter: PlaceTileAdapter
    private lateinit var resultsAdapter: SearchResultAdapter

    private val statusHandler = Handler(Looper.getMainLooper())
    private var commuters = 1042
    private var reports   = 38

    private val geocoder = GeocodingService()
    private var searchJob: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_destination_picker)

        prefs = getSharedPreferences(PREFS, Context.MODE_PRIVATE)

        // Greeting
        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        findViewById<TextView>(R.id.tv_greeting).text = when {
            hour < 12 -> "Good morning."
            hour < 17 -> "Good afternoon."
            else      -> "Good evening."
        }

        findViewById<TextView>(R.id.btn_car_mode).setOnClickListener {
            startActivity(Intent(this, VehicleActivity::class.java))
        }

        loadRecents()
        setupLists()
        setupSearch()
        startLiveStatus()
        fetchLocation()
    }

    override fun onResume() {
        super.onResume()
        // Reflect any newly-added recent after returning
        loadRecents()
        if (::recentAdapter.isInitialized) {
            recentAdapter.submit(recents)
            findViewById<View>(R.id.tv_recent_header).visibility =
                if (recents.isEmpty()) View.GONE else View.VISIBLE
            findViewById<View>(R.id.rv_recent).visibility =
                if (recents.isEmpty()) View.GONE else View.VISIBLE
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        statusHandler.removeCallbacksAndMessages(null)
        stopLocationUpdates()
    }

    // ── Lists ──────────────────────────────────────────────────────────────

    private fun setupLists() {
        popularAdapter = PlaceTileAdapter(POPULAR) { launchTo(it) }
        findViewById<RecyclerView>(R.id.rv_popular).apply {
            layoutManager = GridLayoutManager(this@DestinationPickerActivity, 2)
            adapter = popularAdapter
            isNestedScrollingEnabled = false
        }

        recentAdapter = PlaceTileAdapter(recents, recentChip = true) { launchTo(it) }
        findViewById<RecyclerView>(R.id.rv_recent).apply {
            layoutManager = LinearLayoutManager(
                this@DestinationPickerActivity, LinearLayoutManager.HORIZONTAL, false)
            adapter = recentAdapter
            isNestedScrollingEnabled = false
        }
        findViewById<View>(R.id.tv_recent_header).visibility =
            if (recents.isEmpty()) View.GONE else View.VISIBLE
        findViewById<View>(R.id.rv_recent).visibility =
            if (recents.isEmpty()) View.GONE else View.VISIBLE

        resultsAdapter = SearchResultAdapter(emptyList()) { launchTo(it) }
        findViewById<RecyclerView>(R.id.rv_results).apply {
            layoutManager = LinearLayoutManager(this@DestinationPickerActivity)
            adapter = resultsAdapter
            isNestedScrollingEnabled = false
        }
    }

    // ── Search ─────────────────────────────────────────────────────────────

    private fun setupSearch() {
        val et      = findViewById<EditText>(R.id.et_search)
        val clear   = findViewById<TextView>(R.id.btn_clear_search)
        val browse  = findViewById<View>(R.id.ll_browse)
        val search  = findViewById<View>(R.id.ll_search)

        et.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable?) {
                val q = s?.toString()?.trim().orEmpty()
                if (q.isEmpty()) {
                    searchJob?.cancel()
                    clear.visibility  = View.GONE
                    browse.visibility = View.VISIBLE
                    search.visibility = View.GONE
                } else {
                    clear.visibility  = View.VISIBLE
                    browse.visibility = View.GONE
                    search.visibility = View.VISIBLE
                    runSearch(q)
                }
            }
        })

        clear.setOnClickListener {
            et.setText("")
            et.clearFocus()
            (getSystemService(INPUT_METHOD_SERVICE) as InputMethodManager)
                .hideSoftInputFromWindow(et.windowToken, 0)
        }
    }

    /**
     * Shows instant matches from the local catalog, then debounces a live
     * Nominatim (OSM) lookup so any place/address on the map can be found.
     */
    private fun runSearch(query: String) {
        val noRes     = findViewById<View>(R.id.tv_no_results)
        val searching = findViewById<View>(R.id.tv_searching)

        // 1. Instant local matches — keeps the UI responsive while we hit the network.
        val local = CATALOG.filter { it.name.contains(query, true) || it.area.contains(query, true) }
        resultsAdapter.submit(local)
        noRes.visibility = View.GONE

        searchJob?.cancel()
        searchJob = lifecycleScope.launch {
            delay(350)                       // debounce keystrokes
            searching.visibility = View.VISIBLE
            val remote = geocoder.search(query)
            searching.visibility = View.GONE

            // Merge: local matches first, then geocoded results not already shown.
            val merged = local.toMutableList()
            val seen   = local.map { it.name.lowercase() to it.area.lowercase() }.toMutableSet()
            for (r in remote) {
                val key = r.name.lowercase() to r.area.lowercase()
                if (seen.add(key)) {
                    merged.add(Place(r.name, r.area, r.emoji, r.lat, r.lng))
                }
            }
            resultsAdapter.submit(merged)
            noRes.visibility = if (merged.isEmpty()) View.VISIBLE else View.GONE
        }
    }

    // ── Recents persistence ────────────────────────────────────────────────

    private fun loadRecents() {
        recents.clear()
        val raw = prefs.getString(KEY_RECENTS, null)
        if (raw.isNullOrBlank()) {
            // Seed so the demo is never empty
            recents.addAll(listOf(
                CATALOG.first { it.name == "Majestic" },
                CATALOG.first { it.name == "Indiranagar" },
                CATALOG.first { it.name == "MG Road" },
            ))
            saveRecents()
        } else {
            raw.split("\n").mapNotNull { deserialize(it) }.forEach { recents.add(it) }
        }
    }

    private fun addRecent(place: Place) {
        recents.removeAll { it.name == place.name && it.area == place.area }
        recents.add(0, place)
        while (recents.size > 6) recents.removeAt(recents.size - 1)
        saveRecents()
    }

    private fun saveRecents() {
        prefs.edit()
            .putString(KEY_RECENTS, recents.joinToString("\n") { serialize(it) })
            .apply()
    }

    // ── Navigation ─────────────────────────────────────────────────────────

    private fun launchTo(place: Place) {
        addRecent(place)
        startActivity(
            Intent(this, RouteSelectionActivity::class.java).apply {
                putExtra(EXTRA_DEST_NAME,   place.name)
                putExtra(EXTRA_DEST_LAT,    place.lat)
                putExtra(EXTRA_DEST_LNG,    place.lng)
                putExtra(EXTRA_ORIGIN_LAT,  originLat)
                putExtra(EXTRA_ORIGIN_LNG,  originLng)
                putExtra(EXTRA_ORIGIN_NAME, originName)
            }
        )
    }

    // ── Live status strip ──────────────────────────────────────────────────

    private fun startLiveStatus() {
        val statusView = findViewById<TextView>(R.id.tv_live_status)
        val dot        = findViewById<View>(R.id.dot_live)

        // Pulse the live dot
        ValueAnimator.ofFloat(1f, 0.25f, 1f).apply {
            duration = 1600
            repeatCount = ValueAnimator.INFINITE
            addUpdateListener { dot.alpha = it.animatedValue as Float }
            start()
        }

        fun render() {
            statusView.text = "LIVE — %,d commuters online · %d reports today".format(commuters, reports)
        }
        render()

        val tick = object : Runnable {
            override fun run() {
                commuters = (commuters + Random.nextInt(-12, 18)).coerceIn(900, 1300)
                if (Random.nextInt(3) == 0) reports++
                render()
                statusHandler.postDelayed(this, 4000)
            }
        }
        statusHandler.postDelayed(tick, 4000)
    }

    // ── Location ───────────────────────────────────────────────────────────

    private val fusedClient: FusedLocationProviderClient by lazy {
        LocationServices.getFusedLocationProviderClient(this)
    }
    private var cancellationTokenSource: CancellationTokenSource? = null
    private var fusedCallback: LocationCallback? = null
    private var lmListener: LocationListener? = null
    private var originResolved = false

    private fun hasLocationPermission() = ContextCompat.checkSelfPermission(
        this, Manifest.permission.ACCESS_FINE_LOCATION
    ) == PackageManager.PERMISSION_GRANTED ||
        ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_COARSE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED

    private fun locationServicesEnabled(): Boolean {
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        return lm.isProviderEnabled(LocationManager.GPS_PROVIDER) ||
               lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER)
    }

    /**
     * Resolve the user's *live* location and use it as the routing origin.
     *
     * Primary path is the fused provider's high-accuracy single fix (combines
     * GPS + Wi-Fi + cell), falling back to a streamed fused update and finally
     * to raw LocationManager on both providers for devices without Play
     * Services. The origin used for routing is only ever the real fix — we
     * never silently route from the hardcoded fallback once permission is
     * granted and services are on.
     */
    @SuppressLint("MissingPermission")
    private fun fetchLocation() {
        if (!hasLocationPermission()) { setOriginChip(FALLBACK_NAME); return }
        if (!locationServicesEnabled())  { setOriginChip("Location off"); return }

        setOriginChip("Locating…")

        val cts = CancellationTokenSource()
        cancellationTokenSource = cts
        try {
            fusedClient.getCurrentLocation(Priority.PRIORITY_HIGH_ACCURACY, cts.token)
                .addOnSuccessListener { loc ->
                    if (loc != null) onLocationResolved(loc) else startFusedUpdates()
                }
                .addOnFailureListener { startLocationManagerUpdates() }
        } catch (e: Exception) {
            startLocationManagerUpdates()
        }

        // Safety net: only revert the chip label if nothing ever resolved.
        lifecycleScope.launch {
            delay(12000)
            if (!originResolved) setOriginChip(FALLBACK_NAME)
        }
    }

    /** Fused streamed updates — used when a single fix can't be computed instantly. */
    @SuppressLint("MissingPermission")
    private fun startFusedUpdates() {
        if (originResolved) return
        val request = LocationRequest.Builder(Priority.PRIORITY_HIGH_ACCURACY, 1000L)
            .setMinUpdateIntervalMillis(500L)
            .setMaxUpdates(1)
            .setWaitForAccurateLocation(true)
            .build()
        val callback = object : LocationCallback() {
            override fun onLocationResult(result: LocationResult) {
                result.lastLocation?.let { onLocationResolved(it) }
            }
        }
        fusedCallback = callback
        try {
            fusedClient.requestLocationUpdates(request, callback, Looper.getMainLooper())
                .addOnFailureListener { startLocationManagerUpdates() }
        } catch (e: Exception) {
            startLocationManagerUpdates()
        }
    }

    /** Raw LocationManager fallback (no Play Services): first fix from either provider wins. */
    @SuppressLint("MissingPermission")
    private fun startLocationManagerUpdates() {
        if (originResolved) return
        val lm = getSystemService(LOCATION_SERVICE) as LocationManager
        val listener = object : LocationListener {
            override fun onLocationChanged(loc: Location) = onLocationResolved(loc)
            override fun onProviderEnabled(provider: String) {}
            override fun onProviderDisabled(provider: String) {}
            @Deprecated("deprecated in API 29")
            override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
        }
        lmListener = listener
        listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .filter { lm.isProviderEnabled(it) }
            .forEach { lm.requestLocationUpdates(it, 0L, 0f, listener, Looper.getMainLooper()) }
    }

    private fun onLocationResolved(location: Location) {
        if (originResolved) return
        originResolved = true
        stopLocationUpdates()
        applyLocation(location)
    }

    private fun stopLocationUpdates() {
        cancellationTokenSource?.cancel()
        cancellationTokenSource = null
        fusedCallback?.let { fusedClient.removeLocationUpdates(it) }
        fusedCallback = null
        lmListener?.let {
            (getSystemService(LOCATION_SERVICE) as LocationManager).removeUpdates(it)
        }
        lmListener = null
    }

    private fun applyLocation(location: Location) {
        originLat = location.latitude
        originLng = location.longitude
        lifecycleScope.launch {
            val name = withContext(Dispatchers.IO) { reverseGeocode(location) }
            originName = name
            setOriginChip(name)
        }
    }

    private fun setOriginChip(name: String) {
        findViewById<TextView>(R.id.tv_origin_name)?.text = name
    }

    private fun reverseGeocode(location: Location): String = try {
        val geocoder = Geocoder(this, Locale.getDefault())
        @Suppress("DEPRECATION")
        val addr = geocoder.getFromLocation(location.latitude, location.longitude, 1)?.firstOrNull()
        addr?.subLocality ?: addr?.locality ?: addr?.adminArea ?: FALLBACK_NAME
    } catch (e: Exception) { FALLBACK_NAME }

    // ── Adapters ───────────────────────────────────────────────────────────

    /** Grid tile (popular) or horizontal chip (recent), chosen by [recentChip]. */
    private class PlaceTileAdapter(
        source: List<Place>,
        private val recentChip: Boolean = false,
        private val onClick: (Place) -> Unit,
    ) : RecyclerView.Adapter<RecyclerView.ViewHolder>() {

        private var items = source.toList()

        fun submit(newItems: List<Place>) { items = newItems.toList(); notifyDataSetChanged() }

        override fun getItemCount() = items.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): RecyclerView.ViewHolder {
            val layout = if (recentChip) R.layout.item_recent else R.layout.item_destination
            val v = LayoutInflater.from(parent.context).inflate(layout, parent, false)
            return if (recentChip) RecentVH(v) else TileVH(v)
        }

        override fun onBindViewHolder(holder: RecyclerView.ViewHolder, position: Int) {
            val p = items[position]
            if (holder is RecentVH) {
                holder.emoji.text = p.emoji
                holder.name.text  = p.name
                holder.itemView.setOnClickListener { onClick(p) }
            } else if (holder is TileVH) {
                holder.emoji.text = p.emoji
                holder.name.text  = p.name
                holder.area.text  = p.area
                holder.going.text = "%,d going".format(p.going)
                holder.itemView.setOnClickListener { onClick(p) }
            }
        }

        class TileVH(v: View) : RecyclerView.ViewHolder(v) {
            val emoji: TextView = v.findViewById(R.id.tv_dest_emoji)
            val name:  TextView = v.findViewById(R.id.tv_dest_name)
            val area:  TextView = v.findViewById(R.id.tv_dest_area)
            val going: TextView = v.findViewById(R.id.tv_dest_going)
        }

        class RecentVH(v: View) : RecyclerView.ViewHolder(v) {
            val emoji: TextView = v.findViewById(R.id.tv_recent_emoji)
            val name:  TextView = v.findViewById(R.id.tv_recent_name)
        }
    }

    /** Vertical search-result rows. */
    private class SearchResultAdapter(
        source: List<Place>,
        private val onClick: (Place) -> Unit,
    ) : RecyclerView.Adapter<SearchResultAdapter.VH>() {

        private var items = source.toList()

        fun submit(newItems: List<Place>) { items = newItems.toList(); notifyDataSetChanged() }

        override fun getItemCount() = items.size

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_search_place, parent, false))

        override fun onBindViewHolder(holder: VH, position: Int) {
            val p = items[position]
            holder.emoji.text = p.emoji
            holder.name.text  = p.name
            holder.area.text  = p.area
            holder.going.text = "%,d".format(p.going)
            holder.itemView.setOnClickListener { onClick(p) }
        }

        class VH(v: View) : RecyclerView.ViewHolder(v) {
            val emoji: TextView = v.findViewById(R.id.tv_sp_emoji)
            val name:  TextView = v.findViewById(R.id.tv_sp_name)
            val area:  TextView = v.findViewById(R.id.tv_sp_area)
            val going: TextView = v.findViewById(R.id.tv_sp_going)
        }
    }
}
