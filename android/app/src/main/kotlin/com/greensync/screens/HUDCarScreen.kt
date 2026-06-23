package com.greensync.screens

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import androidx.car.app.CarContext
import androidx.car.app.Screen
import androidx.car.app.model.Action
import androidx.car.app.model.MessageTemplate
import androidx.car.app.model.Template
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import com.google.gson.Gson
import com.greensync.models.Route

/**
 * Android Auto HUD screen — shown on the DHU after route selection.
 *
 * Uses MessageTemplate (single large-text advisory) for driver safety —
 * minimal distraction, maximum legibility at a glance.
 *
 * Updates in real-time via MQTT broadcast from MqttIntentService.
 */
class HUDCarScreen(
    carContext: CarContext,
    private val selectedRoute: Route,
) : Screen(carContext) {

    private val gson = Gson()
    private var advisory     = "CONNECTING…"
    private var phaseInfo    = ""
    private var suggestedKmh = 50

    private val mqttReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val topic   = intent.getStringExtra("topic")   ?: return
            val payload = intent.getStringExtra("payload") ?: return
            handleMqtt(topic, payload)
        }
    }

    init {
        lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) {
                carContext.registerReceiver(
                    mqttReceiver,
                    IntentFilter("com.greensync.MQTT_MESSAGE"),
                )
            }

            override fun onStop(owner: LifecycleOwner) {
                runCatching { carContext.unregisterReceiver(mqttReceiver) }
            }
        })
    }

    override fun onGetTemplate(): Template {
        val body = buildString {
            append("$advisory\n")
            append("Suggested: $suggestedKmh km/h\n")
            if (phaseInfo.isNotBlank()) append(phaseInfo)
        }

        return MessageTemplate.Builder(body)
            .setTitle(selectedRoute.summary)
            .setHeaderAction(Action.BACK)
            .addAction(
                Action.Builder()
                    .setTitle("Exit Nav")
                    .setOnClickListener { screenManager.pop() }
                    .build()
            )
            .build()
    }

    // ── MQTT ─────────────────────────────────────────────────────────────────

    private fun handleMqtt(topic: String, payload: String) {
        val map = runCatching { gson.fromJson(payload, Map::class.java) }.getOrNull() ?: return

        when {
            topic.contains("/rsu/") -> {
                val event = map["event"] as? String ?: return
                val count = (map["vehicle_count"] as? Double)?.toInt() ?: 0
                val (adv, spd) = computeAdvisory(event, lastSignalSecs)
                advisory     = adv
                suggestedKmh = spd
                phaseInfo    = "Zone: ${event.uppercase()}  •  $count vehicles"
                invalidate()
            }
            topic.contains("/signal/") -> {
                val secs      = (map["time_to_switch"] as? Double) ?: 30.0
                lastSignalSecs = secs
                val phaseName = map["phase"] as? String ?: "—"
                phaseInfo     = "Signal: $phaseName  (${secs.toInt()}s)"
                invalidate()
            }
        }
    }

    private var lastSignalSecs = 30.0

    private fun computeAdvisory(event: String, secs: Double): Pair<String, Int> = when {
        event == "congestion" || secs < 5  -> "🔴 STOP"    to 0
        event == "slowdown"   || secs < 12 -> "🟡 COAST"   to 20
        else                                -> "🟢 PROCEED" to 50
    }
}
