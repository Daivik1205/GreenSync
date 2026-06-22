package com.greensync.services

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.gson.Gson
import com.greensync.R
import com.greensync.models.EcuTelemetryPayload
import com.greensync.models.IntentPayload
import com.greensync.models.Route
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import org.eclipse.paho.client.mqttv3.MqttClient
import org.eclipse.paho.client.mqttv3.MqttConnectOptions
import org.eclipse.paho.client.mqttv3.MqttMessage
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence

/**
 * Foreground service that maintains a persistent MQTT connection.
 *
 * Responsibilities:
 *   1. Publishes route intent when user selects a route.
 *   2. Publishes ECU telemetry (speed, fuel/battery) on demand from EcuTelemetryService.
 *   3. Subscribes to greensyncq/rsu/+/state and greensyncq/signal/+/phase
 *      to update the local HUD state.
 *
 * Topics published:
 *   greensync/user/intent       — IntentPayload (JSON)
 *   greensync/ecu/telemetry     — EcuTelemetryPayload (JSON)
 *
 * Topics subscribed:
 *   greensyncq/rsu/+/state      — zone congestion state
 *   greensyncq/signal/+/phase   — signal timing
 */
class MqttIntentService : Service() {

    companion object {
        private const val TAG            = "MqttIntentService"
        private const val CHANNEL_ID     = "greensync_mqtt"
        private const val NOTIF_ID       = 1001
        private const val BROKER_URI     = "tcp://192.168.1.100:1883"   // configure per deployment
        private const val CLIENT_ID_PREFIX = "greensync_android_"

        const val ACTION_PUBLISH_INTENT    = "com.greensync.PUBLISH_INTENT"
        const val ACTION_PUBLISH_TELEMETRY = "com.greensync.PUBLISH_TELEMETRY"
        const val EXTRA_INTENT_PAYLOAD     = "intent_payload_json"
        const val EXTRA_TELEMETRY_PAYLOAD  = "telemetry_payload_json"

        fun publishIntent(context: Context, payload: IntentPayload) {
            val intent = Intent(context, MqttIntentService::class.java).apply {
                action = ACTION_PUBLISH_INTENT
                putExtra(EXTRA_INTENT_PAYLOAD, Gson().toJson(payload))
            }
            context.startService(intent)
        }

        fun publishTelemetry(context: Context, payload: EcuTelemetryPayload) {
            val intent = Intent(context, MqttIntentService::class.java).apply {
                action = ACTION_PUBLISH_TELEMETRY
                putExtra(EXTRA_TELEMETRY_PAYLOAD, Gson().toJson(payload))
            }
            context.startService(intent)
        }
    }

    private val scope   = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val gson    = Gson()
    private var mqttClient: MqttClient? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        startForeground(NOTIF_ID, buildNotification())
        scope.launch { connectMqtt() }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_PUBLISH_INTENT -> {
                val json = intent.getStringExtra(EXTRA_INTENT_PAYLOAD) ?: return START_STICKY
                scope.launch { publish("greensync/user/intent", json) }
            }
            ACTION_PUBLISH_TELEMETRY -> {
                val json = intent.getStringExtra(EXTRA_TELEMETRY_PAYLOAD) ?: return START_STICKY
                scope.launch { publish("greensync/ecu/telemetry", json) }
            }
        }
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        scope.cancel()
        runCatching { mqttClient?.disconnect() }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ── MQTT connection ───────────────────────────────────────────────────────

    private fun connectMqtt() {
        val clientId = CLIENT_ID_PREFIX + System.currentTimeMillis()
        val client   = MqttClient(BROKER_URI, clientId, MemoryPersistence())
        val options  = MqttConnectOptions().apply {
            isCleanSession    = true
            connectionTimeout = 10
            keepAliveInterval = 30
            isAutomaticReconnect = true
        }

        try {
            client.connect(options)
            mqttClient = client
            Log.i(TAG, "MQTT connected to $BROKER_URI")
            subscribeToIncoming(client)
        } catch (e: Exception) {
            Log.e(TAG, "MQTT connect failed: ${e.message}")
        }
    }

    private fun subscribeToIncoming(client: MqttClient) {
        val topics = arrayOf("greensyncq/rsu/+/state", "greensyncq/signal/+/phase")
        val qos    = intArrayOf(0, 0)
        client.subscribe(topics, qos) { topic, message ->
            // Broadcast locally so UI layers can consume without their own MQTT client
            val broadcastIntent = Intent("com.greensync.MQTT_MESSAGE").apply {
                putExtra("topic",   topic)
                putExtra("payload", String(message.payload))
            }
            sendBroadcast(broadcastIntent)
        }
        Log.d(TAG, "Subscribed to RSU state and signal phase topics")
    }

    private fun publish(topic: String, json: String) {
        val client = mqttClient ?: return
        if (!client.isConnected) return
        val message = MqttMessage(json.toByteArray(Charsets.UTF_8)).apply { qos = 1 }
        try {
            client.publish(topic, message)
            Log.d(TAG, "Published to $topic: ${json.take(120)}")
        } catch (e: Exception) {
            Log.w(TAG, "Publish failed on $topic: ${e.message}")
        }
    }

    // ── Notification (required for foreground service) ────────────────────────

    private fun createNotificationChannel() {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "GreenSync V2X",
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java).createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GreenSync")
            .setContentText("V2X communication active")
            .setSmallIcon(R.drawable.ic_signal)
            .setOngoing(true)
            .build()
}
