package com.greensync.screens

import android.content.Context
import android.content.Intent
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Bundle
import android.view.View
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.greensync.R
import com.greensync.screens.RouteSelectionActivity.Companion.MOCK_USER_COUNTS
import com.greensync.screens.RouteSelectionActivity.Companion.congestionColor
import com.greensync.screens.RouteSelectionActivity.Companion.congestionIcon
import com.greensync.screens.RouteSelectionActivity.Companion.congestionLabel
import com.greensync.screens.RouteSelectionActivity.Companion.congestionProgress
import com.greensync.screens.RouteSelectionActivity.Companion.expectedSpeed
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlin.random.Random

class HUDActivity : AppCompatActivity() {

    companion object {
        private const val EXTRA_ROUTE_ID     = "route_id"
        private const val EXTRA_SUMMARY      = "route_summary"
        private const val EXTRA_SELECTED_IDX = "selected_idx"
        private const val EXTRA_USER_COUNT   = "user_count"
        private const val EXTRA_ALL_COUNTS   = "all_counts"
        private const val EXTRA_DEST_NAME    = "dest_name"
        private const val EXTRA_ORIGIN_NAME  = "origin_name"
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
            destName:    String = "Destination",
            originName:  String = "Origin",
            adjustedEta: Int    = 0,
            speed:       Int    = 0,
            distanceKm:  Double = 0.0,
        ): Intent = Intent(context, HUDActivity::class.java).apply {
            putExtra(EXTRA_ROUTE_ID,     routeId)
            putExtra(EXTRA_SUMMARY,      summary)
            putExtra(EXTRA_SELECTED_IDX, selectedIdx)
            putExtra(EXTRA_USER_COUNT,   userCount)
            putExtra(EXTRA_ALL_COUNTS,   allCounts)
            putExtra(EXTRA_DEST_NAME,    destName)
            putExtra(EXTRA_ORIGIN_NAME,  originName)
            putExtra(EXTRA_ETA,          adjustedEta)
            putExtra(EXTRA_SPEED,        speed)
            putExtra(EXTRA_DISTANCE,     distanceKm)
        }
    }

    // Signal state
    private var signalSeconds = Random.nextInt(10, 45)
    private var isGreen       = Random.nextBoolean()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hud)

        val summary     = intent.getStringExtra(EXTRA_SUMMARY)     ?: "Selected Route"
        val selectedIdx = intent.getIntExtra(EXTRA_SELECTED_IDX, 0)
        val userCount   = intent.getIntExtra(EXTRA_USER_COUNT, 100)
        val allCounts   = intent.getIntArrayExtra(EXTRA_ALL_COUNTS) ?: MOCK_USER_COUNTS
        val destName    = intent.getStringExtra(EXTRA_DEST_NAME)    ?: "Destination"
        val originName  = intent.getStringExtra(EXTRA_ORIGIN_NAME) ?: "Origin"
        val eta         = intent.getIntExtra(EXTRA_ETA, 0)
        val speed       = intent.getIntExtra(EXTRA_SPEED, 0)
        val distance    = intent.getDoubleExtra(EXTRA_DISTANCE, 0.0)

        val updatedCount = userCount + 1
        val color        = congestionColor(updatedCount)
        val icon         = congestionIcon(updatedCount)
        val label        = congestionLabel(updatedCount)

        // Back
        findViewById<TextView>(R.id.btn_back).setOnClickListener { finish() }

        // Header
        findViewById<TextView>(R.id.tv_hud_title).text = "$originName  →  $destName"

        // Route confirmed banner
        val routeNum   = selectedIdx + 1
        val bannerView = findViewById<TextView>(R.id.tv_route_label)
        bannerView.text = "Route $routeNum  ·  ${summary.ifBlank { "Via city roads" }}"
        bannerView.backgroundTintList = ColorStateList.valueOf(color)

        // Stat cards
        findViewById<TextView>(R.id.tv_stat_eta).text      = if (eta > 0) "$eta" else "--"
        val speedView = findViewById<TextView>(R.id.tv_stat_speed)
        speedView.text = if (speed > 0) "$speed" else "--"
        speedView.setTextColor(color)
        findViewById<TextView>(R.id.tv_stat_distance).text =
            if (distance > 0) "%.1f".format(distance) else "--"

        // Congestion
        findViewById<TextView>(R.id.tv_congestion_icon).text = icon
        val levelView = findViewById<TextView>(R.id.tv_congestion_level)
        levelView.text = label
        levelView.setTextColor(color)
        findViewById<TextView>(R.id.tv_you_joined).text =
            "You + ${updatedCount - 1} others on this route"

        // Route comparison
        val cmpLabels = arrayOf(
            findViewById<TextView>(R.id.tv_cmp_label_0),
            findViewById(R.id.tv_cmp_label_1),
            findViewById<TextView>(R.id.tv_cmp_label_2),
        )
        val cmpBars = arrayOf(
            findViewById<ProgressBar>(R.id.pb_cmp_0),
            findViewById(R.id.pb_cmp_1),
            findViewById<ProgressBar>(R.id.pb_cmp_2),
        )
        val cmpCounts = arrayOf(
            findViewById<TextView>(R.id.tv_cmp_count_0),
            findViewById(R.id.tv_cmp_count_1),
            findViewById<TextView>(R.id.tv_cmp_count_2),
        )
        allCounts.forEachIndexed { i, count ->
            val c      = if (i == selectedIdx) updatedCount else count
            val cColor = congestionColor(c)
            val spd    = expectedSpeed(c)
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

        // Community report buttons
        val totalActive = allCounts.sum() + 1
        setupReportButtons(totalActive)

        // V2I signal countdown
        startSignalCountdown()
    }

    private fun startSignalCountdown() {
        updateSignalUi()
        lifecycleScope.launch {
            while (true) {
                delay(1000)
                signalSeconds--
                if (signalSeconds <= 0) {
                    isGreen       = !isGreen
                    signalSeconds = if (isGreen) Random.nextInt(20, 40) else Random.nextInt(25, 50)
                }
                updateSignalUi()
            }
        }
    }

    private fun updateSignalUi() {
        val phaseText  = if (isGreen) "🟢  GREEN" else "🔴  RED"
        val phaseColor = if (isGreen) Color.parseColor("#43A047") else Color.parseColor("#E53935")
        val countText  = "${signalSeconds}s"

        val phaseView = findViewById<TextView>(R.id.tv_signal_phase) ?: return
        val countView = findViewById<TextView>(R.id.tv_signal_countdown) ?: return
        phaseView.text = phaseText
        phaseView.setTextColor(phaseColor)
        countView.text = countText
        countView.setTextColor(phaseColor)
    }

    private fun setupReportButtons(totalActive: Int) {
        val confirmView = findViewById<TextView>(R.id.tv_report_confirm)
        val buttonsView = findViewById<LinearLayout>(R.id.ll_report_buttons)

        val handler = android.os.Handler(mainLooper)

        fun onReport(label: String) {
            confirmView.text = "✓ \"$label\" reported!\nYour update reaches ~$totalActive active users."
            confirmView.visibility = View.VISIBLE
            buttonsView.visibility = View.GONE
            // Reset after 4 seconds
            handler.removeCallbacksAndMessages(null)
            handler.postDelayed({
                confirmView.visibility = View.GONE
                buttonsView.visibility = View.VISIBLE
            }, 4000)
        }

        findViewById<TextView>(R.id.btn_report_roadwork).setOnClickListener { onReport("Road Work") }
        findViewById<TextView>(R.id.btn_report_accident).setOnClickListener { onReport("Accident") }
        findViewById<TextView>(R.id.btn_report_police).setOnClickListener   { onReport("Police Checkpoint") }
        findViewById<TextView>(R.id.btn_report_flooding).setOnClickListener { onReport("Flooding") }
        findViewById<TextView>(R.id.btn_report_clear).setOnClickListener    { onReport("All Clear") }
    }
}
