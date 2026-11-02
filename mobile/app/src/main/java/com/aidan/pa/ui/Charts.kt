package com.aidan.pa.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.aidan.pa.analytics.Analytics
import com.aidan.pa.data.LocPoint
import kotlin.math.cos

@Composable
fun ChartCard(title: String, subtitle: String? = null, content: @Composable () -> Unit) {
    Card(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 6.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(Modifier.height(10.dp))
            content()
        }
    }
}

@Composable
fun Empty(text: String) = Text(text, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)

/** Horizontal bars: label | bar | value. */
@Composable
fun HBarChart(items: List<Pair<String, Long>>, color: Color, format: (Long) -> String = Analytics::formatDuration) {
    if (items.isEmpty()) { Empty("No data yet."); return }
    val max = items.maxOf { it.second }.coerceAtLeast(1)
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        items.forEach { (label, value) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.width(112.dp), maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodySmall)
                Box(Modifier.weight(1f).height(14.dp)) {
                    Box(Modifier.fillMaxHeight().fillMaxWidth((value.toFloat() / max).coerceIn(0.02f, 1f))
                        .background(color, RoundedCornerShape(4.dp)))
                }
                Text(format(value), Modifier.width(64.dp), textAlign = TextAlign.End, style = MaterialTheme.typography.labelSmall)
            }
        }
    }
}

/** Vertical columns with optional x labels (shown every [labelEvery] columns). */
@Composable
fun ColumnChart(values: List<Long>, labels: List<String>, color: Color, height: Dp = 120.dp, labelEvery: Int = 1) {
    val max = (values.maxOrNull() ?: 0L).coerceAtLeast(1)
    Row(Modifier.fillMaxWidth().height(height), verticalAlignment = Alignment.Bottom,
        horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        values.forEach { v ->
            val frac = if (v <= 0) 0f else (v.toFloat() / max).coerceIn(0.02f, 1f)
            Box(Modifier.weight(1f).fillMaxHeight(frac).background(color, RoundedCornerShape(topStart = 3.dp, topEnd = 3.dp)))
        }
    }
    Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(2.dp)) {
        labels.forEachIndexed { i, l ->
            Text(if (i % labelEvery == 0) l else "", Modifier.weight(1f), textAlign = TextAlign.Center,
                maxLines = 1, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

/** Your location trail for the period, drawn to scale (no map tiles, no API key). */
@Composable
fun TrailPlot(points: List<LocPoint>, line: Color, dot: Color) {
    if (points.size < 2) { Empty("Not enough location points yet."); return }
    val minLat = points.minOf { it.lat }; val maxLat = points.maxOf { it.lat }
    val minLon = points.minOf { it.lon }; val maxLon = points.maxOf { it.lon }
    val k = cos(Math.toRadians((minLat + maxLat) / 2))   // shrink longitude so shapes aren't stretched
    Canvas(Modifier.fillMaxWidth().height(200.dp)) {
        val w = ((maxLon - minLon) * k).coerceAtLeast(1e-6)
        val h = (maxLat - minLat).coerceAtLeast(1e-6)
        val scale = minOf((size.width - 24f) / w, (size.height - 24f) / h).toFloat()
        val ox = (size.width - (w * scale).toFloat()) / 2f
        val oy = (size.height - (h * scale).toFloat()) / 2f
        fun pos(p: LocPoint) = Offset(ox + ((p.lon - minLon) * k * scale).toFloat(), oy + ((maxLat - p.lat) * scale).toFloat())
        val path = Path().apply {
            moveTo(pos(points.first()).x, pos(points.first()).y)
            points.drop(1).forEach { lineTo(pos(it).x, pos(it).y) }
        }
        drawPath(path, line, style = Stroke(width = 3f))
        points.forEach { drawCircle(dot.copy(alpha = 0.5f), radius = 4f, center = pos(it)) }
        drawCircle(dot, radius = 9f, center = pos(points.last()))
    }
}
