package com.aidan.pa.collect

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import android.os.Looper
import androidx.core.content.ContextCompat
import com.aidan.pa.MainActivity
import com.aidan.pa.R
import com.aidan.pa.app
import com.aidan.pa.data.LocPoint
import com.aidan.pa.sync.Sync
import com.google.android.gms.location.LocationCallback
import com.google.android.gms.location.LocationRequest
import com.google.android.gms.location.LocationResult
import com.google.android.gms.location.LocationServices
import com.google.android.gms.location.Priority
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

/**
 * Foreground service (Android requires one for background location). Every 5 minutes:
 * record a location fix, collect finished app sessions, and sync everything to the server.
 */
class CollectorService : Service() {

    companion object {
        const val INTERVAL_MS = 5 * 60_000L
        private const val CHANNEL = "collector"
        private const val NOTIF_ID = 5

        fun hasLocationPermission(ctx: Context) =
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                ContextCompat.checkSelfPermission(ctx, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED

        /** Starts collection if the user turned it on and location is allowed. Returns why not, or null. */
        fun start(ctx: Context): String? {
            if (!hasLocationPermission(ctx)) return "Allow location first (the collector runs as a location service)."
            ContextCompat.startForegroundService(ctx, Intent(ctx, CollectorService::class.java))
            return null
        }

        fun stop(ctx: Context) = ctx.stopService(Intent(ctx, CollectorService::class.java))

        @Volatile var running = false
            private set
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val fused by lazy { LocationServices.getFusedLocationProviderClient(this) }
    private val callback = object : LocationCallback() {
        override fun onLocationResult(result: LocationResult) {
            if (!app.prefs.trackLocation) return
            result.locations.forEach { app.db.insertLocation(LocPoint(ts = it.time, lat = it.latitude, lon = it.longitude, accuracy = it.accuracy)) }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (!hasLocationPermission(this)) { stopSelf(); return START_NOT_STICKY }
        val type = if (Build.VERSION.SDK_INT >= 29) ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION else 0
        if (Build.VERSION.SDK_INT >= 29) startForeground(NOTIF_ID, notification("Starting…"), type)
        else startForeground(NOTIF_ID, notification("Starting…"))
        if (!running) {
            running = true
            requestUpdates()
            scope.launch {
                while (isActive) {
                    tick()
                    delay(INTERVAL_MS)
                }
            }
        }
        return START_STICKY
    }

    @SuppressLint("MissingPermission")  // checked in hasLocationPermission()
    private fun requestUpdates() {
        if (!app.prefs.trackLocation || !hasLocationPermission(this)) return
        val req = LocationRequest.Builder(Priority.PRIORITY_BALANCED_POWER_ACCURACY, INTERVAL_MS)
            .setMinUpdateIntervalMillis(INTERVAL_MS - 60_000L)
            .build()
        fused.requestLocationUpdates(req, callback, Looper.getMainLooper())
    }

    @SuppressLint("MissingPermission")
    private suspend fun tick() {
        val db = app.db
        // No fix from the update stream recently (phone still, Doze)? Ask for one explicitly.
        if (app.prefs.trackLocation && hasLocationPermission(this) &&
            System.currentTimeMillis() - db.lastLocationTs() > INTERVAL_MS + 60_000L) {
            fused.getCurrentLocation(Priority.PRIORITY_BALANCED_POWER_ACCURACY, null).addOnSuccessListener { loc ->
                if (loc != null) db.insertLocation(LocPoint(ts = loc.time, lat = loc.latitude, lon = loc.longitude, accuracy = loc.accuracy))
            }
        }
        runCatching { UsageCollector.collect(this) }
        val result = Sync.sync(this)
        db.prune()
        val time = DateFormat.getTimeInstance(DateFormat.SHORT).format(Date())
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, notification("Last check $time · $result"))
    }

    private fun notification(text: String): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(NotificationChannel(CHANNEL, "Data collection", NotificationManager.IMPORTANCE_LOW))
        }
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_track)
            .setContentTitle("Collecting usage + location")
            .setContentText(text)
            .setOngoing(true)
            .setContentIntent(open)
            .build()
    }

    override fun onDestroy() {
        running = false
        fused.removeLocationUpdates(callback)
        scope.cancel()
        super.onDestroy()
    }
}
