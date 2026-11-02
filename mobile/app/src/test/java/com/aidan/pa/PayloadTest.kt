package com.aidan.pa

import com.aidan.pa.data.AppSession
import com.aidan.pa.data.LocPoint
import com.aidan.pa.data.WebVisit
import com.aidan.pa.sync.Payload
import org.junit.Assert.assertEquals
import org.junit.Test

/** The server (assistant/mobile.py) relies on exactly these field names. */
class PayloadTest {
    @Test fun matchesServerContract() {
        val p = Payload.build(
            "Pixel 8",
            listOf(AppSession(1, "com.discord", "Discord", 1_000, 61_000)),
            listOf(WebVisit(2, "github.com/x", "github.com", "com.android.chrome", 5_000, 9_000)),
            listOf(LocPoint(3, 7_000, 42.73, -84.55, 12f)),
        )
        assertEquals("Pixel 8", p.getString("device"))
        val a = p.getJSONArray("app_sessions").getJSONObject(0)
        assertEquals(listOf("com.discord", "Discord", 1_000L, 61_000L),
            listOf(a.getString("package"), a.getString("label"), a.getLong("start"), a.getLong("end")))
        val w = p.getJSONArray("web_visits").getJSONObject(0)
        assertEquals("github.com", w.getString("domain"))
        assertEquals("com.android.chrome", w.getString("browser"))
        val l = p.getJSONArray("locations").getJSONObject(0)
        assertEquals(7_000L, l.getLong("ts"))
        assertEquals(12.0, l.getDouble("accuracy"), 0.0)
    }
}
