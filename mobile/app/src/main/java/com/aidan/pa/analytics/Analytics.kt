package com.aidan.pa.analytics

import com.aidan.pa.data.LocPoint
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.asin
import kotlin.math.cos
import kotlin.math.floor
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/** A labelled time interval (app session, web visit). Epoch ms. */
data class Span(val key: String, val start: Long, val end: Long)

data class Place(val lat: Double, val lon: Double, val minutes: Long, val points: Int)

data class SessionStats(val count: Int, val avgMs: Long, val longestMs: Long, val longestKey: String?)

/** Pure functions behind the dashboard charts (unit-tested on the JVM). */
object Analytics {
    private const val HOUR = 3_600_000L

    private fun clip(s: Span, from: Long, to: Long): Long =
        (minOf(s.end, to) - maxOf(s.start, from)).coerceAtLeast(0)

    /** Total time per key inside [from, to), biggest first. */
    fun totals(spans: List<Span>, from: Long, to: Long): List<Pair<String, Long>> =
        spans.groupBy { it.key }
            .mapValues { (_, v) -> v.sumOf { clip(it, from, to) } }
            .filterValues { it > 0 }
            .toList()
            .sortedByDescending { it.second }

    fun total(spans: List<Span>, from: Long, to: Long): Long = spans.sumOf { clip(it, from, to) }

    /** Time per hour of day (0-23), splitting spans that cross hour boundaries. */
    fun hourly(spans: List<Span>, from: Long, to: Long, zone: ZoneId): LongArray {
        val out = LongArray(24)
        for (s in spans) {
            var t = maxOf(s.start, from)
            val end = minOf(s.end, to)
            while (t < end) {
                val zdt = Instant.ofEpochMilli(t).atZone(zone)
                val nextHour = zdt.withMinute(0).withSecond(0).withNano(0).plusHours(1).toInstant().toEpochMilli()
                val stop = minOf(end, nextHour)
                out[zdt.hour] += stop - t
                t = stop
            }
        }
        return out
    }

    /** Time per calendar day for the last [days] days ending today, oldest first. */
    fun daily(spans: List<Span>, days: Int, today: LocalDate, zone: ZoneId): List<Pair<LocalDate, Long>> =
        (days - 1 downTo 0).map { back ->
            val d = today.minusDays(back.toLong())
            val from = d.atStartOfDay(zone).toInstant().toEpochMilli()
            val to = d.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
            d to total(spans, from, to)
        }

    fun sessionStats(spans: List<Span>, from: Long, to: Long): SessionStats {
        val inRange = spans.filter { clip(it, from, to) > 0 }
        if (inRange.isEmpty()) return SessionStats(0, 0, 0, null)
        val longest = inRange.maxBy { clip(it, from, to) }
        return SessionStats(
            count = inRange.size,
            avgMs = inRange.sumOf { clip(it, from, to) } / inRange.size,
            longestMs = clip(longest, from, to),
            longestKey = longest.key,
        )
    }

    fun haversineMeters(a: LocPoint, b: LocPoint): Double {
        val r = 6_371_000.0
        val dLat = Math.toRadians(b.lat - a.lat)
        val dLon = Math.toRadians(b.lon - a.lon)
        val h = sin(dLat / 2).pow(2) + cos(Math.toRadians(a.lat)) * cos(Math.toRadians(b.lat)) * sin(dLon / 2).pow(2)
        return 2 * r * asin(sqrt(h))
    }

    /** Distance travelled, ignoring inaccurate fixes and GPS jitter while standing still. */
    fun distanceMeters(points: List<LocPoint>, maxAccuracy: Float = 200f, minStep: Double = 40.0): Double {
        val good = points.filter { it.accuracy <= maxAccuracy }.sortedBy { it.ts }
        var total = 0.0
        var last: LocPoint? = null
        for (p in good) {
            val l = last
            if (l == null) { last = p; continue }
            val d = haversineMeters(l, p)
            if (d >= minStep) { total += d; last = p }
        }
        return total
    }

    /**
     * Where you spent time: points snapped to a ~[cellMeters] grid; each point is credited the
     * time until the next point (capped, so gaps while the phone was off don't count).
     */
    fun places(points: List<LocPoint>, cellMeters: Double = 150.0, capMs: Long = 15 * 60_000L): List<Place> {
        val sorted = points.sortedBy { it.ts }
        if (sorted.isEmpty()) return emptyList()
        val latStep = cellMeters / 111_320.0
        data class Acc(var lat: Double = 0.0, var lon: Double = 0.0, var ms: Long = 0, var n: Int = 0)
        val cells = HashMap<Pair<Long, Long>, Acc>()
        sorted.forEachIndexed { i, p ->
            val lonStep = cellMeters / (111_320.0 * cos(Math.toRadians(p.lat)).coerceAtLeast(0.01))
            val key = floor(p.lat / latStep).toLong() to floor(p.lon / lonStep).toLong()
            val dwell = if (i + 1 < sorted.size) minOf(sorted[i + 1].ts - p.ts, capMs) else 5 * 60_000L
            val a = cells.getOrPut(key) { Acc() }
            a.lat += p.lat; a.lon += p.lon; a.ms += dwell; a.n += 1
        }
        return cells.values
            .map { Place(it.lat / it.n, it.lon / it.n, it.ms / 60_000L, it.n) }
            .sortedByDescending { it.minutes }
    }

    fun formatDuration(ms: Long): String {
        val m = ms / 60_000L
        return when {
            m < 1 -> "${ms / 1000}s"
            m < 60 -> "${m}m"
            else -> "${m / 60}h ${m % 60}m"
        }
    }
}
