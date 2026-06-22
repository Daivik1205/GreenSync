package com.greensync

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import com.greensync.screens.RouteSelectionActivity
import com.greensync.services.EcuTelemetryService
import com.greensync.services.MqttIntentService

/**
 * Phone launcher activity.
 * Requests location permission, starts background services, then
 * immediately hands off to RouteSelectionActivity.
 */
class MainActivity : AppCompatActivity() {

    private val LOCATION_PERMISSION_REQUEST = 100

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (hasLocationPermission()) {
            proceed()
        } else {
            ActivityCompat.requestPermissions(
                this,
                arrayOf(
                    Manifest.permission.ACCESS_FINE_LOCATION,
                    Manifest.permission.ACCESS_COARSE_LOCATION,
                ),
                LOCATION_PERMISSION_REQUEST,
            )
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray,
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == LOCATION_PERMISSION_REQUEST) {
            proceed()   // continue regardless — location improves origin detection
        }
    }

    private fun proceed() {
        // Start MQTT + ECU telemetry background services
        startService(Intent(this, MqttIntentService::class.java))
        startService(Intent(this, EcuTelemetryService::class.java))

        startActivity(Intent(this, RouteSelectionActivity::class.java))
        finish()
    }

    private fun hasLocationPermission(): Boolean =
        ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION) ==
            PackageManager.PERMISSION_GRANTED
}
