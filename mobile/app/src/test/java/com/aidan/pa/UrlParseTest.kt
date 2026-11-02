package com.aidan.pa

import com.aidan.pa.collect.UrlParse
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class UrlParseTest {
    @Test fun parsesAddressBarText() {
        assertEquals("github.com/aidankeighron" to "github.com", UrlParse.parse("https://github.com/aidankeighron/"))
        assertEquals("www.reddit.com/r/simracing" to "reddit.com", UrlParse.parse("www.reddit.com/r/simracing"))
        assertEquals("m.youtube.com/watch?v=x" to "youtube.com", UrlParse.parse("m.youtube.com/watch?v=x"))
        assertEquals("100.101.102.103:8000/app" to "100.101.102.103", UrlParse.parse("http://100.101.102.103:8000/app"))
    }

    @Test fun ignoresSearchesAndJunk() {
        assertNull(UrlParse.parse("best sim racing wheel"))
        assertNull(UrlParse.parse("hello"))
        assertNull(UrlParse.parse(""))
        assertNull(UrlParse.parse(null))
        assertNull(UrlParse.parse("3.14"))
    }
}
