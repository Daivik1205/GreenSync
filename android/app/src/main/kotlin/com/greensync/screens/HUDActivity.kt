package com.greensync.screens

import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.os.Bundle
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.greensync.R
import com.greensync.screens.RouteSelectionActivity.Companion.MOCK_USER_COUNTS
import com.greensync.screens.RouteSelectionActivity.Companion.congestionColor
import com.greensync.screens.RouteSelectionActivity.Companion.congestionIcon
import com.greensync.screens.RouteSelectionActivity.Companion.congestionLabel
import com.greensync.screens.RouteSelectionActivity.Companion.congestionProgress

class HUDActivity : AppCompatActivity() {

    companion object {
        private const val EXTRA_ROUTE_ID     = "route_id"
        private const val EXTRA_SUMMARY      = "route_summary"
        private const val EXTRA_SELECTED_IDX = "selected_idx"
        private const val EXTRA_USER_COUNT   = "user_count"
        private const val EXTRA_ALL_COUNTS   = "all_counts"
        private const val EXTRA_DEST_NAME    = "dest_name"
        private const val EXTRA_ETA          = "adjusted_eta"
        private const val EXTRA_SPEED        = "expected_speed"
        private const val EXTRA_DISTANCE     = "distance_km"

        fun newIntent(
            context:     Context,
            routeId:     String,
            summary:     String,
            selectedIdx: Int,
            userCount:   Int,
            allCounts:   IntArray,
            destName:    String  = "Destination",
            adjustedEta: Int     = 0,
            speed:       Int     = 0,
            distanceKm:  Double  = 0.0,
        ): Intent = Intent(context, HUDActivity::class.java).apply {
            putExtra(EXTRA_ROUTE_ID,     routeId)
            putExtra(EXTRA_SUMMARY,      summary)
            putExtra(EXTRA_SELECTED_IDX, selectedIdx)
            putExtra(EXTRA_USER_COUNT,   userCount)
            putExtra(EXTRA_ALL_COUNTS,   allCounts)
            putExtra(EXTRA_DEST_NAME,    destName)
            putExtra(EXTRA_ETA,          adjustedEta)
            putExtra(EXTRA_SPEED,        speed)
            putExtra(EXTRA_DISTANCE,     distanceKm)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hud)

        val summary     = intent.getStringExtra(EXTRA_SUMMARY)     ?: "Selected Route"
        val selectedIdx = intent.getIntExtra(EXTRA_SELECTED_IDX, 0)
        val userCount   = intent.getIntExtra(EXTRA_USER_COUNT, 100)
        val allCounts   = intent.getIntArrayExtra(EXTRA_ALL_COUNTS) ?: MOCK_USER_COUNTS
        val destName    = intent.getStringExtra(EXTRA_DEST_NAME)    ?: "Destination"
        val eta         = intent.getIntExtra(EXTRA_ETA, 0)
        val speed       = intent.getIntExtra(EXTRA_SPEED, 0)
        val distance    = intent.getDoubleExtra(EXTRA_DISTANCE, 0.0)

        val updatedCount = userCount + 1
        val color        = congestionColor(updatedCount)
        val icon         = congestionIcon(updatedCount)
        val label        = congestionLabel(updatedCount)

        // Back button
        findViewById<TextView>(R.id.btn_back).setOnClickListener { finish() }

        // Header title
        findViewById<TextView>(R.id.tv_hud_title).text = "Yelahanka  →  $destName"

        // Route confirmed banner
        val routeNum    = selectedIdx + 1
        val bannerText  = "Route $routeNum  ·  ${summary.ifBlank { "Via city roads" }}"
        val bannerView  = findViewById<TextView>(R.id.tv_route_label)
        bannerView.text = bannerText
        bannerView.backgroundTintList = ColorStateList.valueOf(color)

        // Stat cards
        val etaDisplay = if (eta > 0) "$eta" else "--"
        val spdDisplay = if (speed > 0) "$speed" else "--"
        val distDisplay = if (distance > 0) "%.1f".format(distance) else "--"

        findViewById<TextView>(R.id.tv_stat_eta).text      = etaDisplay
        val speedView = findViewById<TextView>(R.id.tv_stat_speed)
        speedView.text = spdDisplay
        speedView.setTextColor(color)
        findViewById<TextView>(R.id.tv_stat_distance).text = distDisplay

        // Congestion display
        findViewById<TextView>(R.id.tv_congestion_icon).text  = icon
        val levelView = findViewById<TextView>(R.id.tv_congestion_level)
        levelView.text = label
        levelView.setTextColor(color)

        // "You joined" message
        findViewById<TextView>(R.id.tv_you_joined).text =
            "You + ${updatedCount - 1} others on this route"

        // Route comparison bars
        val cmpLabels = arrayOf(
            findViewById<TextView>(R.id.tv_cmp_label_0),
            findViewById(R.id.tv_cmp_label_1),
            findViewById(R.id.tv_cmp_label_2),
        )
        val cmpBars = arrayOf(
            findViewById<ProgressBar>(R.id.pb_cmp_0),
            findViewById(R.id.pb_cmp_1),
            findViewById(R.id.pb_cmp_2),
        )
        val cmpCounts = arrayOf(
            findViewById<TextView>(R.id.tv_cmp_count_0),
            findViewById(R.id.tv_cmp_count_1),
            findViewById(R.id.tv_cmp_count_2),
        )

        allCounts.forEachIndexed { i, count ->
            val c      = if (i == selectedIdx) updatedCount else count
            val cColor = congestionColor(c)
            val spd    = RouteSelectionActivity.expectedSpeed(c)
            cmpLabels[i].text = "Route ${i + 1}"
            cmpBars[i].progress = congestionProgress(c)
            cmpBars[i].progressTintList = ColorStateList.valueOf(cColor)
            cmpCounts[i].text = "${congestionIcon(c)} $c  ·  ~$spd km/h"
            cmpCounts[i].setTextColor(cColor)

            if (i == selectedIdx) {
                cmpLabels[i].setTextColor(color)
                cmpLabels[i].textSize = 13f
            }
        }
    }
}
