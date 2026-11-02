package com.aidan.pa.collect

import android.accessibilityservice.AccessibilityService
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.aidan.pa.app
import com.aidan.pa.data.WebVisit

/**
 * Logs which website is showing in the browser, and for how long, by reading ONLY the
 * address bar of known browsers. A visit ends when the URL changes, you switch to another
 * app, or the screen turns off.
 */
class WebAccessibilityService : AccessibilityService() {

    companion object {
        /** Browser package -> address bar view ids (several, as browsers rename them between versions). */
        val BROWSERS: Map<String, List<String>> = mapOf(
            "com.android.chrome" to listOf("url_bar"),
            "com.chrome.beta" to listOf("url_bar"),
            "com.brave.browser" to listOf("url_bar"),
            "com.microsoft.emmx" to listOf("url_bar"),
            "com.kiwibrowser.browser" to listOf("url_bar"),
            "com.vivaldi.browser" to listOf("url_bar"),
            "org.mozilla.firefox" to listOf("mozac_browser_toolbar_url_view", "url_bar_title"),
            "org.mozilla.firefox_beta" to listOf("mozac_browser_toolbar_url_view"),
            "org.mozilla.focus" to listOf("display_url", "mozac_browser_toolbar_url_view"),
            "com.sec.android.app.sbrowser" to listOf("location_bar_edit_text"),
            "com.opera.browser" to listOf("url_field"),
            "com.duckduckgo.mobile.android" to listOf("omnibarTextInput"),
        )
        @Volatile var running = false
            private set
    }

    private data class Open(val url: String, val domain: String, val browser: String, val start: Long)

    private var open: Open? = null
    private var lastRead = 0L
    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) = close(System.currentTimeMillis())
    }

    override fun onServiceConnected() {
        running = true
        registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF))
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (!app.prefs.trackWeb) { close(System.currentTimeMillis()); return }
        val now = System.currentTimeMillis()
        val root = rootInActiveWindow ?: return
        val pkg = root.packageName?.toString() ?: return
        val ids = BROWSERS[pkg]
        if (ids == null) {
            // another app is in front: the browser visit (if any) is over
            if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) close(now)
            return
        }
        if (now - lastRead < 1_000) return   // address bars fire many content events; once a second is plenty
        lastRead = now
        val bar = findBar(root, pkg, ids) ?: return
        if (bar.isFocused) return            // you're typing: that's a search, not a page
        val (url, domain) = UrlParse.parse(bar.text) ?: return
        if (open?.url == url) return
        close(now)
        open = Open(url, domain, pkg, now)
    }

    private fun findBar(root: AccessibilityNodeInfo, pkg: String, ids: List<String>): AccessibilityNodeInfo? {
        for (id in ids) {
            root.findAccessibilityNodeInfosByViewId("$pkg:id/$id")?.firstOrNull()?.let { return it }
        }
        return null
    }

    private fun close(at: Long) {
        val o = open ?: return
        open = null
        if (at - o.start >= 2_000) {
            app.db.insertWebVisit(WebVisit(url = o.url, domain = o.domain, browser = o.browser, start = o.start, end = at))
        }
    }

    override fun onInterrupt() = Unit

    override fun onDestroy() {
        close(System.currentTimeMillis())
        running = false
        runCatching { unregisterReceiver(screenOff) }
        super.onDestroy()
    }
}
