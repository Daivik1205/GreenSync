package com.greensync.screens

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.gson.Gson
import com.greensync.R

/**
 * Driver HUD screen — shown after the user selects a route.
 *
 * Listens for MQTT broadcast messages from MqttIntentService and updates:
 *   • Advisory label: COAST / PROCEED / STOP
 *   • Current signal phase
 *   • Queue severity indicator
 *   • Suggested speed
 *
 * Signal phase inference:
 *   If the nearest zone's event is "congestion" and a signal phase payload
 *   shows < 5 s remaining → show STOP advisory.
 *   If slowdown and < 10 s remaining → COAST.
 *   Otherwise → PROCEED.
 */
class HUDActivity : AppCompatActivity() {

    companion object {
        private const val EXTRA_ROUTE_ID      = "route_id"
        private const val EXTRA_ROUTE_SUMMARY = "route_summary"

        fun newIntent(context: Context, routeId: String, summary: String): Intent =
            Intent(context, HUDActivity::class.java).apply {
                putExtra(EXTRA_ROUTE_ID, routeId)
                putExtra(EXTRA_ROUTE_SUMMARY, summary)
            }
    }

    private val gson = Gson()

    private lateinit var tvAdvisory:     TextView
    private lateinit var tvPhase:        TextView
    private lateinit var tvQueue:        TextView
    private lateinit var tvSpeed:        TextView
    private lateinit var tvRouteLabel:   TextView

    // Latest zone + signal state from MQTT
    private var lastZoneEvent: String = "unknown"
    private var lastSignalSecondsLeft: Double = 30.0

    private val mqttReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val topic   = intent.getStringExtra("topic")   ?: return
            val payload = intent.getStringExtra("payload") ?: return
            handleMqttMessage(topic, payload)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_hud)

        tvAdvisory   = findViewById(R.id.tv_advisory)
        tvPhase      = findViewById(R.id.tv_phase)
        tvQueue      = findViewById(R.id.tv_queue)
        tvSpeed      = findViewById(R.id.tv_suggested_speed)
        tvRouteLabel = findViewById(R.id.tv_route_label)

        tvRouteLabel.text = intent.getStringExtra(EXTRA_ROUTE_SUMMARY) ?: "Active Route"

        registerReceiver(
            mqttReceiver,
            IntentFilter("com.greensync.MQTT_MESSAGE"),
            RECEIVER_NOT_EXPORTED,
        )
    }

    override fun onDestroy() {
        super.onDestroy()
        unregisterReceiver(mqttReceiver)
    }

    // ── MQTT message handling ─────────────────────────────────────────────────

    private fun handleMqttMessage(topic: String, payload: String) {
        when {
            topic.contains("/rsu/") && topic.endsWith("/state") -> {
                val state = runCatching {
                    gson.fromJson(payload, Map::class.java)
                }.getOrNull() ?: return
                lastZoneEvent = state["event"] as? String ?: "unknown"
                val queueCount = (state["vehicle_count"] as? Double)?.toInt() ?: 0
                tvQueue.text = "Queue: $queueCount vehicles  (${lastZoneEvent.uppercase()})"
                refreshAdvisory()
            }
            topic.contains("/signal/") && topic.endsWith("/phase") -> {
                val phase = runCatching {
                    gson.fromJson(payload, Map::class.java)
                }.getOrNull() ?: return
                val secondsLeft = (phase["time_to_switch"] as? Double) ?: 30.0
                lastSignalSecondsLeft = secondsLeft
                val phaseName = phase["phase"] as? String ?: "—"
                tvPhase.text = "Signal: $phaseName  (${secondsLeft.toInt()}s)"
                refreshAdvisory()
            }
        }
    }

    private fun refreshAdvisory() {
        val (advisory, speedKmh) = computeAdvisory(lastZoneEvent, lastSignalSecondsLeft)
        tvAdvisory.text = advisory
        tvSpeed.text    = "Suggested: $speedKmh km/h"
        tvAdvisory.setBackgroundColor(advisoryColor(advisory))
    }

    private fun computeAdvisory(event: String, secondsLeft: Double): Pair<String, Int> =
        when {
            event == "congestion" || secondsLeft < 5  -> "STOP"   to 0
            event == "slowdown"   || secondsLeft < 12 -> "COAST"  to 20
            else                                       -> "PROCEED" to 50
        }

    private fun advisoryColor(advisory: String): Int = when (advisory) {
        "STOP"    -> 0xFFE53935.toInt()
        "COAST"   -> 0xFFFB8C00.toInt()
        else      -> 0xFF43A047.toInt()
    }
}
