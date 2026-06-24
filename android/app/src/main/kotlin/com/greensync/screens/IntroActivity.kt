package com.greensync.screens

import android.animation.ValueAnimator
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.animation.DecelerateInterpolator
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.greensync.MainActivity
import com.greensync.R
import kotlin.random.Random

/**
 * First-run style introduction / home screen.
 *
 * Sets the tone before the user dives in: animated wordmark, the three
 * pillars of GreenSync, and a live "booting digital twin" ticker. The CTA
 * hands off to [MainActivity], which keeps the existing permission +
 * service-start + destination-picker flow intact.
 */
class IntroActivity : AppCompatActivity() {

    private val handler = Handler(Looper.getMainLooper())
    private var commuters = 1042
    private var optimal   = 76
    private var booted    = false

    private val bootLines = listOf(
        "LIVE — booting digital twin…",
        "LIVE — syncing 35 RSU zones…",
        "LIVE — GRU+LSH forecaster online",
    )
    private var bootIdx = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_intro)

        animateEntrance()
        pulseDot()
        startLiveTicker()

        findViewById<TextView>(R.id.btn_enter).setOnClickListener {
            it.isEnabled = false
            startActivity(Intent(this, MainActivity::class.java))
            overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out)
            finish()
        }

        findViewById<TextView>(R.id.btn_intro_car).setOnClickListener {
            startActivity(Intent(this, VehicleActivity::class.java))
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacksAndMessages(null)
    }

    /** Staggered fade + rise so the screen assembles itself on entry. */
    private fun animateEntrance() {
        val ids = listOf(
            R.id.intro_live_pill,
            R.id.tv_intro_kicker,
            R.id.tv_intro_title,
            R.id.tv_intro_tagline,
            R.id.intro_feature_1,
            R.id.intro_feature_2,
            R.id.intro_feature_3,
            R.id.btn_enter,
            R.id.btn_intro_car,
            R.id.tv_intro_footer,
        )
        ids.forEachIndexed { i, id ->
            findViewById<View>(id).apply {
                alpha = 0f
                translationY = 34f
                animate()
                    .alpha(1f)
                    .translationY(0f)
                    .setStartDelay(120L + i * 85L)
                    .setDuration(520L)
                    .setInterpolator(DecelerateInterpolator())
                    .start()
            }
        }

        // Glow breathes in
        findViewById<View>(R.id.hero_glow).apply {
            alpha = 0f
            animate().alpha(1f).setStartDelay(80L).setDuration(900L).start()
        }
    }

    private fun pulseDot() {
        val dot = findViewById<View>(R.id.intro_dot)
        ValueAnimator.ofFloat(1f, 0.25f, 1f).apply {
            duration = 1500
            repeatCount = ValueAnimator.INFINITE
            addUpdateListener { dot.alpha = it.animatedValue as Float }
            start()
        }
    }

    private fun startLiveTicker() {
        val pill = findViewById<TextView>(R.id.tv_intro_live)
        val tick = object : Runnable {
            override fun run() {
                if (!booted && bootIdx < bootLines.size) {
                    pill.text = bootLines[bootIdx++]
                    if (bootIdx >= bootLines.size) booted = true
                } else {
                    commuters = (commuters + Random.nextInt(-9, 15)).coerceIn(900, 1300)
                    optimal   = (optimal + Random.nextInt(-2, 3)).coerceIn(68, 86)
                    pill.text = "LIVE — %,d commuters · network %d%% optimal".format(commuters, optimal)
                }
                handler.postDelayed(this, 1400)
            }
        }
        handler.postDelayed(tick, 900)
    }
}
