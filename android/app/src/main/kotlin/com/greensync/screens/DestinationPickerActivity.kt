package com.greensync.screens

import android.content.Intent
import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.greensync.R
import java.util.Calendar

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
        const val EXTRA_DEST_NAME = "dest_name"
        const val EXTRA_DEST_LAT  = "dest_lat"
        const val EXTRA_DEST_LNG  = "dest_lng"

        val DESTINATIONS = listOf(
            Destination("Home",        "Mysore Road",     "🏠", 12.9399, 77.5432, 1042),
            Destination("Office",      "Electronic City", "💼", 12.8411, 77.6793,  867),
            Destination("Airport",     "Devanahalli",     "✈️", 13.1986, 77.7066,  234),
            Destination("Koramangala", "South Bengaluru", "🍕", 12.9352, 77.6245,  453),
            Destination("Majestic",    "City Centre",     "🏛️", 12.9762, 77.5713,  712),
            Destination("Whitefield",  "East Bengaluru",  "🏢", 12.9698, 77.7499,  589),
        )
    }

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
                    putExtra(EXTRA_DEST_NAME, dest.name)
                    putExtra(EXTRA_DEST_LAT,  dest.lat)
                    putExtra(EXTRA_DEST_LNG,  dest.lng)
                }
            )
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
