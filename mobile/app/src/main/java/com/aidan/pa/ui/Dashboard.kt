@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.aidan.pa.ui

import android.content.Context
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.aidan.pa.analytics.Analytics
import com.aidan.pa.analytics.Place
import com.aidan.pa.analytics.SessionStats
import com.aidan.pa.analytics.Span
import com.aidan.pa.app
import com.aidan.pa.collect.UsageCollector
import com.aidan.pa.data.LocPoint
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

enum class Range(val label: String, val days: Int) { TODAY("Today", 1), WEEK("7 days", 7), MONTH("30 days", 30) }

private class DashData(
    val screenMs: Long,
    val stats: SessionStats,
    val topApps: List<Pair<String, Long>>,
    val hourly: LongArray,
    val daily: List<Pair<LocalDate, Long>>,
    val webMs: Long,
    val topSites: List<Pair<String, Long>>,
    val distanceKm: Double,
    val places: List<Place>,
    val points: List<LocPoint>,
)

private fun load(ctx: Context, range: Range): DashData {
    val db = ctx.app.db
    val zone = ZoneId.systemDefault()
    val today = LocalDate.now(zone)
    val from = today.minusDays(range.days - 1L).atStartOfDay(zone).toInstant().toEpochMilli()
    val to = System.currentTimeMillis()
    val trendDays = maxOf(7, range.days)
    val trendFrom = today.minusDays(trendDays - 1L).atStartOfDay(zone).toInstant().toEpochMilli()
    val appSpans = db.appSessions(trendFrom, to).map { Span(it.label, it.start, it.end) }
    val webSpans = db.webVisits(from, to).map { Span(it.domain, it.start, it.end) }
    val points = db.locations(from, to)
    return DashData(
        screenMs = Analytics.total(appSpans, from, to),
        stats = Analytics.sessionStats(appSpans, from, to),
        topApps = Analytics.totals(appSpans, from, to).take(8),
        hourly = Analytics.hourly(appSpans, from, to, zone),
        daily = Analytics.daily(appSpans, trendDays, today, zone),
        webMs = Analytics.total(webSpans, from, to),
        topSites = Analytics.totals(webSpans, from, to).take(8),
        distanceKm = Analytics.distanceMeters(points) / 1000.0,
        places = Analytics.places(points).take(5),
        points = points,
    )
}

@Composable
fun DashboardScreen(refresh: Int) {
    val ctx = LocalContext.current
    var range by rememberSaveable { mutableStateOf(Range.TODAY) }
    var data by remember { mutableStateOf<DashData?>(null) }
    LaunchedEffect(range, refresh) {
        data = withContext(Dispatchers.IO) {
            runCatching { UsageCollector.collect(ctx) }   // pull the latest app sessions before drawing
            load(ctx, range)
        }
    }
    val c = MaterialTheme.colorScheme
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(vertical = 12.dp)) {
        Text("Your usage", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.padding(horizontal = 16.dp))
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Range.entries.forEach { r -> FilterChip(selected = range == r, onClick = { range = r }, label = { Text(r.label) }) }
        }
        val d = data
        if (d == null) {
            CircularProgressIndicator(Modifier.padding(32.dp))
            return@Column
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Stat("Screen time", Analytics.formatDuration(d.screenMs), Modifier.weight(1f))
            Stat("Sessions", d.stats.count.toString(), Modifier.weight(1f))
            Stat("Web", Analytics.formatDuration(d.webMs), Modifier.weight(1f))
            Stat("Moved", String.format(Locale.US, "%.1f km", d.distanceKm), Modifier.weight(1f))
        }
        Spacer(Modifier.height(6.dp))
        ChartCard("Top apps", "Time in the foreground") { HBarChart(d.topApps, c.primary) }
        ChartCard("When you use your phone", "Screen time by hour of day") {
            ColumnChart(d.hourly.toList(), (0..23).map { if (it == 0) "12a" else if (it < 12) "${it}a" else if (it == 12) "12p" else "${it - 12}p" },
                c.tertiary, labelEvery = 6)
        }
        ChartCard("Daily screen time", "Last ${d.daily.size} days") {
            val fmt = DateTimeFormatter.ofPattern(if (d.daily.size <= 7) "EEE" else "d")
            ColumnChart(d.daily.map { it.second }, d.daily.map { it.first.format(fmt) }, c.primary,
                labelEvery = if (d.daily.size <= 7) 1 else 5)
        }
        ChartCard("Session lengths") {
            if (d.stats.count == 0) Empty("No sessions yet.") else Column {
                Text("Average session: ${Analytics.formatDuration(d.stats.avgMs)}")
                Text("Longest: ${Analytics.formatDuration(d.stats.longestMs)} in ${d.stats.longestKey}")
            }
        }
        ChartCard("Top websites", "Time each site was on screen") { HBarChart(d.topSites, c.secondary) }
        ChartCard("Where you spent time", "Places ~150 m across, by time there") {
            if (d.places.isEmpty()) Empty("No location points yet.") else Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                d.places.forEachIndexed { i, p ->
                    Text("${i + 1}. ${String.format(Locale.US, "%.4f, %.4f", p.lat, p.lon)}  ·  ${Analytics.formatDuration(p.minutes * 60_000L)}",
                        style = MaterialTheme.typography.bodySmall)
                }
            }
        }
        ChartCard("Location trail", "${d.points.size} points, drawn to scale") { TrailPlot(d.points, c.primary, c.error) }
    }
}

@Composable
private fun Stat(label: String, value: String, modifier: Modifier) {
    Card(modifier) {
        Column(Modifier.padding(horizontal = 10.dp, vertical = 10.dp)) {
            Text(value, style = MaterialTheme.typography.titleMedium, maxLines = 1)
            Text(label, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}
