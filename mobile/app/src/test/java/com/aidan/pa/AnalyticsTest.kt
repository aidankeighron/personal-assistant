package com.aidan.pa

import com.aidan.pa.analytics.Analytics
import com.aidan.pa.analytics.Span
import com.aidan.pa.data.LocPoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

class AnalyticsTest {
    private val zone = ZoneId.of("America/Detroit")
    private val day = LocalDate.of(2026, 11, 2)
    private fun at(h: Int, m: Int = 0) = day.atTime(h, m).atZone(zone).toInstant().toEpochMilli()

    @Test fun totalsClipToRangeAndSort() {
        val spans = listOf(Span("a", at(9), at(10)), Span("b", at(10), at(10, 30)), Span("a", at(23, 30), at(23, 59)))
        val t = Analytics.totals(spans, at(0), at(23, 45))
        assertEquals(listOf("a" to (75 * 60_000L), "b" to (30 * 60_000L)), t)
    }

    @Test fun hourlySplitsAcrossHours() {
        val h = Analytics.hourly(listOf(Span("a", at(9, 45), at(10, 15))), at(0), at(23), zone)
        assertEquals(15 * 60_000L, h[9])
        assertEquals(15 * 60_000L, h[10])
        assertEquals(30 * 60_000L, h.sum())
    }

    @Test fun dailyHasOneBucketPerDay() {
        val d = Analytics.daily(listOf(Span("a", at(8), at(9))), 7, day, zone)
        assertEquals(7, d.size)
        assertEquals(day, d.last().first)
        assertEquals(3_600_000L, d.last().second)
        assertEquals(0L, d.first().second)
    }

    @Test fun distanceIgnoresJitterAndBadFixes() {
        val home = LocPoint(ts = 0, lat = 42.7325, lon = -84.5555, accuracy = 20f)
        val jitter = home.copy(ts = 1, lat = 42.73252)                    // ~2 m: ignored
        val bad = home.copy(ts = 2, lat = 42.80, accuracy = 900f)           // inaccurate: ignored
        val store = home.copy(ts = 3, lat = 42.7415)                       // ~1 km north
        val km = Analytics.distanceMeters(listOf(home, jitter, bad, store)) / 1000
        assertTrue("got $km", km in 0.95..1.05)
    }

    @Test fun placesRankByTimeSpent() {
        val home = (0 until 12).map { LocPoint(ts = it * 300_000L, lat = 42.7325, lon = -84.5555, accuracy = 20f) }
        val store = (12 until 15).map { LocPoint(ts = it * 300_000L, lat = 42.7415, lon = -84.5555, accuracy = 20f) }
        val p = Analytics.places(home + store)
        assertEquals(2, p.size)
        assertTrue(p[0].minutes > p[1].minutes)
        assertEquals(42.7325, p[0].lat, 1e-6)
    }

    @Test fun formatsDurations() {
        assertEquals("45s", Analytics.formatDuration(45_000))
        assertEquals("12m", Analytics.formatDuration(12 * 60_000L))
        assertEquals("2h 5m", Analytics.formatDuration(125 * 60_000L))
    }
}
