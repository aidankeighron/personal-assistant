package com.aidan.pa.sync

import com.aidan.pa.data.AppSession
import com.aidan.pa.data.LocPoint
import com.aidan.pa.data.WebVisit
import org.json.JSONArray
import org.json.JSONObject

/**
 * Body of POST /mobile/sync. Keep in sync with assistant/mobile.py on the server.
 * Times are epoch milliseconds.
 */
object Payload {
    fun build(device: String, apps: List<AppSession>, web: List<WebVisit>, locs: List<LocPoint>): JSONObject =
        JSONObject()
            .put("device", device)
            .put("app_sessions", JSONArray().apply {
                apps.forEach { put(JSONObject().put("package", it.pkg).put("label", it.label).put("start", it.start).put("end", it.end)) }
            })
            .put("web_visits", JSONArray().apply {
                web.forEach {
                    put(JSONObject().put("url", it.url).put("domain", it.domain).put("browser", it.browser)
                        .put("start", it.start).put("end", it.end))
                }
            })
            .put("locations", JSONArray().apply {
                locs.forEach {
                    put(JSONObject().put("ts", it.ts).put("lat", it.lat).put("lon", it.lon).put("accuracy", it.accuracy.toDouble()))
                }
            })
}
