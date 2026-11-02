package com.aidan.pa.data

import android.content.Context
import android.os.Build

class Prefs(context: Context) {
    private val sp = context.getSharedPreferences("pa_tracker", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = sp.getString("server_url", "http://m7:8000")!!
        set(v) = sp.edit().putString("server_url", v.trim().trimEnd('/')).apply()
    var token: String
        get() = sp.getString("token", "")!!
        set(v) = sp.edit().putString("token", v.trim()).apply()
    var deviceName: String
        get() = sp.getString("device", Build.MODEL ?: "phone")!!
        set(v) = sp.edit().putString("device", v.trim().ifEmpty { Build.MODEL ?: "phone" }).apply()

    var collecting: Boolean
        get() = sp.getBoolean("collecting", false)
        set(v) = sp.edit().putBoolean("collecting", v).apply()
    var trackLocation: Boolean
        get() = sp.getBoolean("track_location", true)
        set(v) = sp.edit().putBoolean("track_location", v).apply()
    var trackApps: Boolean
        get() = sp.getBoolean("track_apps", true)
        set(v) = sp.edit().putBoolean("track_apps", v).apply()
    var trackWeb: Boolean
        get() = sp.getBoolean("track_web", true)
        set(v) = sp.edit().putBoolean("track_web", v).apply()

    var lastSync: Long
        get() = sp.getLong("last_sync", 0)
        set(v) = sp.edit().putLong("last_sync", v).apply()
    var lastSyncResult: String
        get() = sp.getString("last_sync_result", "never synced")!!
        set(v) = sp.edit().putString("last_sync_result", v).apply()

    val syncConfigured get() = serverUrl.isNotBlank() && token.isNotBlank()
}
