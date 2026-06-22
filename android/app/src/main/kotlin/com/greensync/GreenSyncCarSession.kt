package com.greensync

import android.content.Intent
import androidx.car.app.Screen
import androidx.car.app.Session
import com.greensync.screens.RouteSelectionCarScreen

/**
 * Car App Session — owns the screen stack for the Android Auto DHU.
 * The initial screen is RouteSelectionCarScreen (shows 3 OSRM alternatives).
 */
class GreenSyncCarSession : Session() {

    override fun onCreateScreen(intent: Intent): Screen =
        RouteSelectionCarScreen(carContext)
}
