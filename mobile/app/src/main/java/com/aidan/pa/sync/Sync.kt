package com.aidan.pa.sync

import android.content.Context
import com.aidan.pa.app
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

/** Pushes unsynced rows to your server (the desktop assistant) in batches. */
object Sync {
    private const val BATCH = 500
    private val lock = Mutex()

    private fun open(url: String, token: String, method: String): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 10_000
            readTimeout = 20_000
            setRequestProperty("Authorization", "Bearer $token")
            setRequestProperty("Content-Type", "application/json")
        }

    /** Returns a short human-readable result (also saved for the Settings screen). */
    suspend fun sync(ctx: Context): String = withContext(Dispatchers.IO) {
        val prefs = ctx.app.prefs
        if (!prefs.syncConfigured) return@withContext "sync off (set server + token)".also { prefs.lastSyncResult = it }
        lock.withLock {
            val db = ctx.app.db
            var sent = 0
            val result = try {
                repeat(40) {   // up to 40 batches per run; the rest goes next time
                    val apps = db.appSessions(0, Long.MAX_VALUE, unsyncedOnly = true, limit = BATCH)
                    val web = db.webVisits(0, Long.MAX_VALUE, unsyncedOnly = true, limit = BATCH)
                    val locs = db.locations(0, Long.MAX_VALUE, unsyncedOnly = true, limit = BATCH)
                    if (apps.isEmpty() && web.isEmpty() && locs.isEmpty()) return@repeat
                    val conn = open("${prefs.serverUrl}/mobile/sync", prefs.token, "POST")
                    conn.doOutput = true
                    conn.outputStream.use { it.write(Payload.build(prefs.deviceName, apps, web, locs).toString().toByteArray()) }
                    val code = conn.responseCode
                    if (code != 200) {
                        val err = conn.errorStream?.bufferedReader()?.readText().orEmpty().take(120)
                        throw IllegalStateException(if (code == 401) "bad token" else "HTTP $code $err")
                    }
                    conn.inputStream.close()
                    db.markSynced("app_sessions", apps.map { it.id })
                    db.markSynced("web_visits", web.map { it.id })
                    db.markSynced("locations", locs.map { it.id })
                    sent += apps.size + web.size + locs.size
                }
                prefs.lastSync = System.currentTimeMillis()
                "synced $sent"
            } catch (e: Exception) {
                "sync failed: ${e.message ?: e.javaClass.simpleName}"
            }
            prefs.lastSyncResult = result
            result
        }
    }

    /** For the "Test connection" button. */
    suspend fun test(ctx: Context, serverUrl: String, token: String): String = withContext(Dispatchers.IO) {
        try {
            val health = open("$serverUrl/health", token, "GET")
            if (health.responseCode != 200) return@withContext "Server answered HTTP ${health.responseCode}"
            val src = open("$serverUrl/sources?token=${URLEncoder.encode(token, "UTF-8")}", token, "GET")
            when (src.responseCode) {
                200 -> {
                    val body = JSONObject(src.inputStream.bufferedReader().readText())
                    val sources = body.optJSONArray("sources")
                    "Connected. Server has ${sources?.length() ?: 0} data sources."
                }
                401 -> "Server reachable, but the token is wrong (use ASSISTANT_API_TOKEN from the server's .env)."
                else -> "Server reachable, /sources answered HTTP ${src.responseCode}"
            }
        } catch (e: Exception) {
            "Can't reach $serverUrl (${e.javaClass.simpleName}: ${e.message}). Is Tailscale on?"
        }
    }
}
