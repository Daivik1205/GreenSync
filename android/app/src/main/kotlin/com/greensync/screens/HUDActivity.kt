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

        fun newIntent(
            context:     Context,
            routeId:     String,
            summary:     String,
            selectedIdx: Int,
            userCount:   Int,
            allCounts:   IntArray,
        ): Intent = Intent(context, HUDActivity::class.java).apply {
            putExtra(EXTRA_ROUTE_ID,     routeId)
            putExtra(EXTRA_SUMMARY,      summary)
            putExtra(EXTRA_SELECTED_IDX, selectedIdx)
            putExtra(EXTRA_USER_COUNT,   userCount)
            putExtra(EXTRA_ALL_COUNTS,   allCounts)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hud)

        val summary     = intent.getStringExtra(EXTRA_SUMMARY)     ?: "Selected Route"
        val selectedIdx = intent.getIntExtra(EXTRA_SELECTED_IDX, 0)
        val userCount   = intent.getIntExtra(EXTRA_USER_COUNT, 100)
        val allCounts   = intent.getIntArrayExtra(EXTRA_ALL_COUNTS) ?: MOCK_USER_COUNTS

        // After selection, user adds 1 to the count
        val updatedCount = userCount + 1
        val color        = congestionColor(updatedCount)
        val icon         = congestionIcon(updatedCount)
        val label        = congestionLabel(updatedCount)

        // Route label
        val routeNum = selectedIdx + 1
        val summaryText = if (summary.isBlank()) "Route $routeNum" else summary
        findViewById<TextView>(R.id.tv_route_label).text =
            "Route $routeNum  ·  $summaryText"

        // Central congestion display
        findViewById<TextView>(R.id.tv_congestion_icon).text  = icon
        findViewById<TextView>(R.id.tv_congestion_level).text = label
        findViewById<TextView>(R.id.tv_congestion_level).setTextColor(color)

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
            val c = if (i == selectedIdx) updatedCount else count
            val cColor = congestionColor(c)
            cmpLabels[i].text = "Route ${i + 1}"
            cmpBars[i].progress = congestionProgress(c)
            cmpBars[i].progressTintList = ColorStateList.valueOf(cColor)
            cmpCounts[i].text = "${congestionIcon(c)} $c users"
            cmpCounts[i].setTextColor(cColor)

            // Bold the selected route
            if (i == selectedIdx) {
                cmpLabels[i].setTextColor(color)
                cmpLabels[i].textSize = 13f
            }
        }
    }
}
