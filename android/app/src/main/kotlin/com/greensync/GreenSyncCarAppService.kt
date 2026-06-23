package com.greensync

import androidx.car.app.CarAppService
import androidx.car.app.Session
import androidx.car.app.validation.HostValidator

/**
 * Entry point for the Android Auto Desktop Head Unit (DHU).
 *
 * The Car App Library calls createSession() when the user launches GreenSync
 * from the car's launcher. GreenSyncCarSession returns the initial Screen
 * (RouteSelectionCarScreen), which integrates with the DHU's navigation UX.
 */
class GreenSyncCarAppService : CarAppService() {

    override fun createHostValidator(): HostValidator =
        HostValidator.ALLOW_ALL_HOSTS_VALIDATOR   // restrict in production to Android Auto host sig

    override fun onCreateSession(): Session = GreenSyncCarSession()
}
