package com.aidan.pa.collect

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.Process
import com.aidan.pa.app

/** Reads Android's usage events since the last run and stores finished app sessions. */
object UsageCollector {
    private const val CURSOR = "usage_cursor"
    private const val OPEN = "usage_open"
    private const val BACKFILL_MS = 3 * 86_400_000L
    private val labels = HashMap<String, String>()

    fun hasPermission(ctx: Context): Boolean {
        val ops = ctx.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= 29) {
            ops.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        } else {
            @Suppress("DEPRECATION")
            ops.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), ctx.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun label(ctx: Context, pkg: String): String = labels.getOrPut(pkg) {
        try {
            val pm = ctx.packageManager
            pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
        } catch (e: PackageManager.NameNotFoundException) {
            pkg
        }
    }

    /** Returns how many new sessions were stored. */
    @Synchronized
    fun collect(ctx: Context): Int {
        if (!ctx.app.prefs.trackApps || !hasPermission(ctx)) return 0
        val db = ctx.app.db
        val now = System.currentTimeMillis()
        val from = db.kvGet(CURSOR)?.toLongOrNull() ?: (now - BACKFILL_MS)
        val usm = ctx.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val raw = usm.queryEvents(from, now)
        val events = mutableListOf<UsageLogic.Event>()
        val e = UsageEvents.Event()
        while (raw.hasNextEvent()) {
            raw.getNextEvent(e)
            if (e.eventType in setOf(UsageLogic.FOREGROUND, UsageLogic.BACKGROUND, UsageLogic.SCREEN_OFF,
                    UsageLogic.KEYGUARD_SHOWN, UsageLogic.SHUTDOWN)) {
                events += UsageLogic.Event(e.packageName ?: "", e.eventType, e.timeStamp)
            }
        }
        val open = db.kvGet(OPEN)?.split("|")?.takeIf { it.size == 2 }?.let { UsageLogic.Open(it[0], it[1].toLong()) }
        val result = UsageLogic.build(events, open) { label(ctx, it) }
        db.insertAppSessions(result.sessions)
        db.kvSet(OPEN, result.open?.let { "${it.pkg}|${it.start}" })
        db.kvSet(CURSOR, now.toString())
        return result.sessions.size
    }
}
