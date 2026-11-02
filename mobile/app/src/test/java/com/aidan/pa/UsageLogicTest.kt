package com.aidan.pa

import com.aidan.pa.collect.UsageLogic
import com.aidan.pa.collect.UsageLogic.Event
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UsageLogicTest {
    private val fg = UsageLogic.FOREGROUND
    private val bg = UsageLogic.BACKGROUND

    @Test fun pairsForegroundAndBackground() {
        val r = UsageLogic.build(listOf(Event("chat", fg, 1_000), Event("chat", bg, 61_000), Event("maps", fg, 70_000)), null)
        assertEquals(1, r.sessions.size)
        assertEquals(60_000, r.sessions[0].durationMs)
        assertEquals(UsageLogic.Open("maps", 70_000), r.open)   // still open; finished on a later run
    }

    @Test fun activitySwitchesInsideOneAppAreMerged() {
        val ev = listOf(Event("chat", fg, 0), Event("chat", bg, 10_000), Event("chat", fg, 10_200), Event("chat", bg, 30_000))
        val r = UsageLogic.build(ev, null)
        assertEquals(1, r.sessions.size)
        assertEquals(30_000, r.sessions[0].durationMs)
    }

    @Test fun screenOffClosesAndOpenCarriesOverBetweenRuns() {
        val first = UsageLogic.build(listOf(Event("game", fg, 0)), null)
        val second = UsageLogic.build(listOf(Event("", UsageLogic.SCREEN_OFF, 120_000)), first.open)
        assertEquals(120_000, second.sessions.single().durationMs)
        assertNull(second.open)
    }

    @Test fun switchingAppsClosesThePreviousOne() {
        val r = UsageLogic.build(listOf(Event("a", fg, 0), Event("b", fg, 5_000), Event("b", bg, 9_000)), null) { it.uppercase() }
        assertEquals(listOf("A" to 5_000L, "B" to 4_000L), r.sessions.map { it.label to it.durationMs })
    }

    @Test fun dropsBlips() {
        assertEquals(0, UsageLogic.build(listOf(Event("a", fg, 0), Event("a", bg, 300)), null).sessions.size)
    }
}
