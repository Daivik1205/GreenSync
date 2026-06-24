package com.greensync

import android.content.Intent
import androidx.car.app.Screen
import androidx.car.app.Session
import com.greensync.screens.CarInfoScreen

/**
 * Car App Session — owns the screen stack for Android Auto / the DHU.
 * Opens on the vehicle-info dashboard; routes are one tap away from there.
 */
class GreenSyncCarSession : Session() {

    override fun onCreateScreen(intent: Intent): Screen =
        CarInfoScreen(carContext)
}
