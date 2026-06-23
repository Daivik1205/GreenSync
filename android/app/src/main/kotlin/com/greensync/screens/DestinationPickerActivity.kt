package com.greensync.screens

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.content.pm.PackageManager
import android.location.Geocoder
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.greensync.R
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Calendar
import java.util.Locale

class DestinationPickerActivity : AppCompatActivity() {

    data class Destination(
        val name: String,
        val area: String,
        val emoji: String,
        val lat: Double,
        val lng: Double,
        val going: Int,
    )

    companion object {
        const val EXTRA_DEST_NAME   = "dest_name"
        const val EXTRA_DEST_LAT    = "dest_lat"
        const val EXTRA_DEST_LNG    = "dest_lng"
        const val EXTRA_ORIGIN_LAT  = "origin_lat"
        const val EXTRA_ORIGIN_LNG  = "origin_lng"
        const val EXTRA_ORIGIN_NAME = "origin_name"

        // Yelahanka fallback
        private const val FALLBACK_LAT  = 13.1007
        private const val FALLBACK_LNG  = 77.5963
        private const val FALLBACK_NAME = "Yelahanka"

        val DESTINATIONS = listOf(
            Destination("Home",        "Mysore Road",     "🏠", 12.9399, 77.5432, 1042),
            Destination("Office",      "Electronic City", "💼", 12.8411, 77.6793,  867),
            Destination("Airport",     "Devanahalli",     "✈️", 13.1986, 77.7066,  234),
            Destination("Koramangala", "South Bengaluru", "🍕", 12.9352, 77.6245,  453),
            Destination("Majestic",    "City Centre",     "🏛️", 12.9762, 77.5713,  712),
            Destination("Whitefield",  "East Bengaluru",  "🏢", 12.9698, 77.7499,  589),
        )
    }

    private var originLat  = FALLBACK_LAT
    private var originLng  = FALLBACK_LNG
    private var originName = FALLBACK_NAME

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_destination_picker)

        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        val greeting = when {
            hour < 12 -> "Good morning!"
            hour < 17 -> "Good afternoon!"
            else      -> "Good evening!"
        }
        findViewById<TextView>(R.id.tv_greeting).text = greeting

        val rv = findViewById<RecyclerView>(R.id.rv_destinations)
        rv.layoutManager = GridLayoutManager(this, 2)
        rv.adapter = DestAdapter(DESTINATIONS) { dest ->
            startActivity(
                Intent(this, RouteSelectionActivity::class.java).apply {
                    putExtra(EXTRA_DEST_NAME,   dest.name)
                    putExtra(EXTRA_DEST_LAT,    dest.lat)
                    putExtra(EXTRA_DEST_LNG,    dest.lng)
                    putExtra(EXTRA_ORIGIN_LAT,  originLat)
                    putExtra(EXTRA_ORIGIN_LNG,  originLng)
                    putExtra(EXTRA_ORIGIN_NAME, originName)
                }
            )
        }

        fetchLocation()
    }

    @SuppressLint("MissingPermission")
    private fun fetchLocation() {
        val hasPermission = ContextCompat.checkSelfPermission(
            this, Manifest.permission.ACCESS_FINE_LOCATION
        ) == PackageManager.PERMISSION_GRANTED

        if (!hasPermission) {
            setOriginChip(FALLBACK_NAME)
            return
        }

        val lm = getSystemService(LOCATION_SERVICE) as LocationManager

        // Try last known location from any available provider — instant, no callback
        val bestLast = listOf(LocationManager.GPS_PROVIDER, LocationManager.NETWORK_PROVIDER)
            .filter { lm.isProviderEnabled(it) }
            .mapNotNull { lm.getLastKnownLocation(it) }
            .minByOrNull { it.accuracy }   // prefer most accurate

        if (bestLast != null) {
            applyLocation(bestLast)
        } else {
            // Request a single fresh fix
            val provider = when {
                lm.isProviderEnabled(LocationManager.NETWORK_PROVIDER) -> LocationManager.NETWORK_PROVIDER
                lm.isProviderEnabled(LocationManager.GPS_PROVIDER)     -> LocationManager.GPS_PROVIDER
                else -> { setOriginChip(FALLBACK_NAME); return }
            }
            val listener = object : LocationListener {
                override fun onLocationChanged(loc: Location) {
                    lm.removeUpdates(this)
                    applyLocation(loc)
                }
            }
            lm.requestLocationUpdates(provider, 0L, 0f, listener)
        }
    }

    private fun applyLocation(location: Location) {
        originLat = location.latitude
        originLng = location.longitude

        // Reverse-geocode on IO thread, update chip on main thread
        lifecycleScope.launch {
            val name = withContext(Dispatchers.IO) { reverseGeocode(location) }
            originName = name
            setOriginChip(name)
        }
    }

    private fun setOriginChip(name: String) {
        findViewById<TextView>(R.id.tv_origin_name)?.text = name
    }

    private fun reverseGeocode(location: Location): String {
        return try {
            val geocoder = Geocoder(this, Locale.getDefault())
            @Suppress("DEPRECATION")
            val addresses = geocoder.getFromLocation(location.latitude, location.longitude, 1)
            val addr = addresses?.firstOrNull()
            addr?.subLocality ?: addr?.locality ?: addr?.adminArea ?: FALLBACK_NAME
        } catch (e: Exception) {
            FALLBACK_NAME
        }
    }

    private class DestAdapter(
        private val items: List<Destination>,
        private val onClick: (Destination) -> Unit,
    ) : RecyclerView.Adapter<DestAdapter.VH>() {

        inner class VH(view: View) : RecyclerView.ViewHolder(view) {
            val tvEmoji: TextView = view.findViewById(R.id.tv_dest_emoji)
            val tvName:  TextView = view.findViewById(R.id.tv_dest_name)
            val tvArea:  TextView = view.findViewById(R.id.tv_dest_area)
            val tvGoing: TextView = view.findViewById(R.id.tv_dest_going)
        }

        override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): VH =
            VH(LayoutInflater.from(parent.context).inflate(R.layout.item_destination, parent, false))

        override fun getItemCount() = items.size

        override fun onBindViewHolder(holder: VH, position: Int) {
            val dest = items[position]
            holder.tvEmoji.text = dest.emoji
            holder.tvName.text  = dest.name
            holder.tvArea.text  = dest.area
            holder.tvGoing.text = "${dest.going} going here"
            holder.itemView.setOnClickListener { onClick(dest) }
        }
    }
}
