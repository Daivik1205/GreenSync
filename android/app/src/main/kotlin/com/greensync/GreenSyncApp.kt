package com.greensync

import android.app.Application
import android.util.Log

class GreenSyncApp : Application() {
    override fun onCreate() {
        super.onCreate()
        Log.i("GreenSync", "GreenSync V2 application started")
    }
}
