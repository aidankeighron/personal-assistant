@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.aidan.pa.ui

import android.content.Context
import android.content.Intent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.aidan.pa.analytics.Analytics
import com.aidan.pa.app
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

private enum class Kind(val label: String) { APPS("Apps"), WEB("Websites"), LOCATION("Location") }

private data class Row3(val time: String, val main: String, val detail: String, val csv: String)

private val TIME = DateTimeFormatter.ofPattern("HH:mm:ss")

private fun t(ms: Long, zone: ZoneId) = Instant.ofEpochMilli(ms).atZone(zone).format(TIME)

private fun loadRows(ctx: Context, kind: Kind, day: LocalDate): List<Row3> {
    val zone = ZoneId.systemDefault()
    val from = day.atStartOfDay(zone).toInstant().toEpochMilli()
    val to = day.plusDays(1).atStartOfDay(zone).toInstant().toEpochMilli()
    val db = ctx.app.db
    return when (kind) {
        Kind.APPS -> db.appSessions(from, to).reversed().map {
            Row3("${t(it.start, zone)}–${t(it.end, zone)}", it.label, "${it.pkg} · ${Analytics.formatDuration(it.durationMs)}",
                "${it.start},${it.end},${it.pkg},\"${it.label.replace("\"", "'")}\",${it.durationMs / 1000}")
        }
        Kind.WEB -> db.webVisits(from, to).reversed().map {
            Row3("${t(it.start, zone)}–${t(it.end, zone)}", it.domain, "${it.url} · ${Analytics.formatDuration(it.durationMs)}",
                "${it.start},${it.end},${it.domain},\"${it.url.replace("\"", "%22")}\",${it.browser},${it.durationMs / 1000}")
        }
        Kind.LOCATION -> db.locations(from, to).reversed().map {
            Row3(t(it.ts, zone), String.format(Locale.US, "%.5f, %.5f", it.lat, it.lon), "±${it.accuracy.toInt()} m",
                "${it.ts},${it.lat},${it.lon},${it.accuracy}")
        }
    }
}

private val CSV_HEADER = mapOf(
    Kind.APPS to "start_ms,end_ms,package,app,duration_s",
    Kind.WEB to "start_ms,end_ms,domain,url,browser,duration_s",
    Kind.LOCATION to "ts_ms,lat,lon,accuracy_m",
)

@Composable
fun RawDataScreen(refresh: Int) {
    val ctx = LocalContext.current
    var kind by rememberSaveable { mutableStateOf(Kind.APPS) }
    var day by remember { mutableStateOf(LocalDate.now()) }
    var rows by remember { mutableStateOf<List<Row3>>(emptyList()) }
    LaunchedEffect(kind, day, refresh) { rows = withContext(Dispatchers.IO) { loadRows(ctx, kind, day) } }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Kind.entries.forEach { k -> FilterChip(selected = kind == k, onClick = { kind = k }, label = { Text(k.label) }) }
        }
        Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = { day = day.minusDays(1) }) { Text("‹ Prev") }
            Text(day.format(DateTimeFormatter.ofPattern("EEE, MMM d")), Modifier.weight(1f), style = MaterialTheme.typography.titleSmall)
            TextButton(onClick = { day = day.plusDays(1) }, enabled = day < LocalDate.now()) { Text("Next ›") }
            TextButton(onClick = {
                val csv = (listOf(CSV_HEADER.getValue(kind)) + rows.reversed().map { it.csv }).joinToString("\n")
                ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).apply {
                    type = "text/csv"
                    putExtra(Intent.EXTRA_SUBJECT, "pa-${kind.name.lowercase()}-$day.csv")
                    putExtra(Intent.EXTRA_TEXT, csv)
                }, "Export CSV"))
            }, enabled = rows.isNotEmpty()) { Text("CSV") }
        }
        Text("${rows.size} ${kind.label.lowercase()} records", Modifier.padding(horizontal = 16.dp),
            style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        LazyColumn(Modifier.fillMaxSize()) {
            items(rows) { r ->
                Column(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
                    Row {
                        Text(r.main, Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        Text(r.time, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                    Text(r.detail, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
                HorizontalDivider()
            }
        }
    }
}
