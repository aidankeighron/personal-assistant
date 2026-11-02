package com.aidan.pa.data

/** One stretch of time an app was in the foreground. Times are epoch milliseconds. */
data class AppSession(
    val id: Long = 0,
    val pkg: String,
    val label: String,
    val start: Long,
    val end: Long,
) {
    val durationMs get() = (end - start).coerceAtLeast(0)
}

/** One stretch of time a page was showing in a browser. */
data class WebVisit(
    val id: Long = 0,
    val url: String,
    val domain: String,
    val browser: String,
    val start: Long,
    val end: Long,
) {
    val durationMs get() = (end - start).coerceAtLeast(0)
}

data class LocPoint(
    val id: Long = 0,
    val ts: Long,
    val lat: Double,
    val lon: Double,
    val accuracy: Float,
)
