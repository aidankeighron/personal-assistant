package com.aidan.pa.ui

import android.Manifest
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import com.aidan.pa.app
import com.aidan.pa.collect.CollectorService
import com.aidan.pa.collect.UsageCollector
import com.aidan.pa.collect.WebAccessibilityService
import com.aidan.pa.sync.Sync
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

private fun granted(ctx: Context, p: String) = ContextCompat.checkSelfPermission(ctx, p) == PackageManager.PERMISSION_GRANTED

private fun accessibilityOn(ctx: Context): Boolean {
    val me = ComponentName(ctx, WebAccessibilityService::class.java).flattenToString()
    val enabled = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES).orEmpty()
    return enabled.split(':').any { it.equals(me, ignoreCase = true) }
}

private fun batteryUnrestricted(ctx: Context) =
    (ctx.getSystemService(Context.POWER_SERVICE) as PowerManager).isIgnoringBatteryOptimizations(ctx.packageName)

@Composable
fun SettingsScreen(refresh: Int) {
    val ctx = LocalContext.current
    val prefs = ctx.app.prefs
    val scope = rememberCoroutineScope()
    var tick by remember { mutableIntStateOf(0) }          // re-read statuses after actions
    val key = refresh + tick

    var server by remember { mutableStateOf(prefs.serverUrl) }
    var token by remember { mutableStateOf(prefs.token) }
    var device by remember { mutableStateOf(prefs.deviceName) }
    var status by remember { mutableStateOf("") }

    val locationLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestMultiplePermissions()) { tick++ }
    val singleLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { tick++ }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {

        Text("Server (your desktop assistant)", style = MaterialTheme.typography.titleMedium)
        OutlinedTextField(server, { server = it }, Modifier.fillMaxWidth(), label = { Text("Server URL") },
            supportingText = { Text("Over Tailscale, e.g. http://m7:8000 or http://desktop:8000") }, singleLine = true)
        OutlinedTextField(token, { token = it }, Modifier.fillMaxWidth(), label = { Text("API token") },
            supportingText = { Text("ASSISTANT_API_TOKEN from the server's .env") }, singleLine = true,
            visualTransformation = PasswordVisualTransformation())
        OutlinedTextField(device, { device = it }, Modifier.fillMaxWidth(), label = { Text("Device name") }, singleLine = true)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = {
                prefs.serverUrl = server; prefs.token = token; prefs.deviceName = device
                status = "Saved."
            }) { Text("Save") }
            OutlinedButton(onClick = {
                status = "Testing…"
                scope.launch { status = Sync.test(ctx, server.trim().trimEnd('/'), token.trim()) }
            }) { Text("Test connection") }
        }
        if (status.isNotEmpty()) Text(status, style = MaterialTheme.typography.bodySmall)

        Text("Collect", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
        var loc by remember { mutableStateOf(prefs.trackLocation) }
        var apps by remember { mutableStateOf(prefs.trackApps) }
        var web by remember { mutableStateOf(prefs.trackWeb) }
        Toggle("Location every 5 minutes", loc) { loc = it; prefs.trackLocation = it }
        Toggle("Which apps are open, and when", apps) { apps = it; prefs.trackApps = it }
        Toggle("Which websites are open, and when", web) { web = it; prefs.trackWeb = it }

        var collecting by remember(key) { mutableStateOf(prefs.collecting && CollectorService.running) }
        Button(onClick = {
            if (collecting) {
                prefs.collecting = false; CollectorService.stop(ctx); collecting = false; status = "Collection stopped."
            } else {
                prefs.collecting = true
                val err = CollectorService.start(ctx)
                collecting = err == null
                status = err ?: "Collecting. A small notification stays while it runs."
            }
            tick++
        }, Modifier.fillMaxWidth()) { Text(if (collecting) "Stop collecting" else "Start collecting") }

        Text("Permissions", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
        // keyed on `key` so they refresh when you come back from a settings page
        val fine = remember(key) { granted(ctx, Manifest.permission.ACCESS_FINE_LOCATION) }
        val bg = remember(key) { Build.VERSION.SDK_INT < 29 || granted(ctx, Manifest.permission.ACCESS_BACKGROUND_LOCATION) }
        val notif = remember(key) { Build.VERSION.SDK_INT < 33 || granted(ctx, Manifest.permission.POST_NOTIFICATIONS) }
        val usage = remember(key) { UsageCollector.hasPermission(ctx) }
        val access = remember(key) { accessibilityOn(ctx) }
        val battery = remember(key) { batteryUnrestricted(ctx) }

        Perm("Location", fine, "Needed for location and to run in the background.") {
            locationLauncher.launch(arrayOf(Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION))
        }
        if (Build.VERSION.SDK_INT >= 29) Perm("Location: Allow all the time", bg,
            "So collection restarts after a reboot. Pick \"Allow all the time\" on the next screen.") {
            if (!fine) status = "Allow location first." else singleLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        }
        if (Build.VERSION.SDK_INT >= 33) Perm("Notifications", notif, "Shows the small \"collecting\" notification.") {
            singleLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        Perm("Usage access", usage, "Find PA Tracker in the list and turn it on. Gives app open/close times.") {
            ctx.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS))
        }
        Perm("Accessibility: websites", access,
            "Installed apps → PA Tracker: websites → On. If it's greyed out (\"restricted setting\"): " +
                "Settings → Apps → PA Tracker → ⋮ → Allow restricted settings, then try again.") {
            ctx.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        Perm("Battery: unrestricted", battery, "Stops Android from pausing collection overnight.") {
            ctx.startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:${ctx.packageName}")))
        }

        Text("Sync", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(top = 8.dp))
        val pending = remember(key) { ctx.app.db.pendingCounts() }
        val last = prefs.lastSync.takeIf { it > 0 }?.let { DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT).format(Date(it)) } ?: "never"
        Text("Last sync: $last · ${prefs.lastSyncResult}", style = MaterialTheme.typography.bodySmall)
        Text("Waiting to sync: ${pending["app_sessions"]} app sessions, ${pending["web_visits"]} web visits, " +
            "${pending["locations"]} locations", style = MaterialTheme.typography.bodySmall)
        OutlinedButton(onClick = {
            status = "Syncing…"
            scope.launch {
                runCatching { UsageCollector.collect(ctx) }
                status = Sync.sync(ctx); tick++
            }
        }) { Text("Sync now") }
        Text("Data stays on this phone (90 days) and on your own server. Nothing goes anywhere else.",
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun Toggle(label: String, value: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(value, onChange)
    }
}

@Composable
private fun Perm(name: String, ok: Boolean, help: String, fix: () -> Unit) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text((if (ok) "✅ " else "⚠️ ") + name, style = MaterialTheme.typography.bodyMedium)
            if (!ok) Text(help, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (!ok) OutlinedButton(onClick = fix) { Text("Fix") }
    }
}
