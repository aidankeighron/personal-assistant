package com.aidan.pa.collect

import com.aidan.pa.data.AppSession

/**
 * Turns raw UsageEvents into foreground sessions. Pure Kotlin so it is unit-tested.
 *
 * Event types (android.app.usage.UsageEvents.Event): 1 = ACTIVITY_RESUMED (foreground),
 * 2 = ACTIVITY_PAUSED (background), 16 = SCREEN_NON_INTERACTIVE, 17 = KEYGUARD_SHOWN,
 * 26 = DEVICE_SHUTDOWN.
 */
object UsageLogic {
    const val FOREGROUND = 1
    const val BACKGROUND = 2
    const val SCREEN_OFF = 16
    const val KEYGUARD_SHOWN = 17
    const val SHUTDOWN = 26

    /** Activities inside one app pause/resume within milliseconds; join those back up. */
    const val MERGE_GAP_MS = 3_000L
    const val MIN_SESSION_MS = 1_000L

    data class Event(val pkg: String, val type: Int, val ts: Long)
    data class Open(val pkg: String, val start: Long)
    data class Result(val sessions: List<AppSession>, val open: Open?)

    fun build(events: List<Event>, open: Open?, label: (String) -> String = { it }): Result {
        val out = mutableListOf<AppSession>()
        var cur = open
        fun close(at: Long) {
            val c = cur ?: return
            if (at > c.start) out += AppSession(pkg = c.pkg, label = label(c.pkg), start = c.start, end = at)
            cur = null
        }
        for (e in events.sortedBy { it.ts }) {
            when (e.type) {
                FOREGROUND -> if (cur?.pkg != e.pkg) { close(e.ts); cur = Open(e.pkg, e.ts) }
                BACKGROUND -> if (cur?.pkg == e.pkg) close(e.ts)
                SCREEN_OFF, KEYGUARD_SHOWN, SHUTDOWN -> close(e.ts)
            }
        }
        return Result(merge(out).filter { it.durationMs >= MIN_SESSION_MS }, cur)
    }

    fun merge(sessions: List<AppSession>): List<AppSession> {
        val out = mutableListOf<AppSession>()
        for (s in sessions.sortedBy { it.start }) {
            val last = out.lastOrNull()
            if (last != null && last.pkg == s.pkg && s.start - last.end <= MERGE_GAP_MS) {
                out[out.size - 1] = last.copy(end = maxOf(last.end, s.end))
            } else {
                out += s
            }
        }
        return out
    }
}
