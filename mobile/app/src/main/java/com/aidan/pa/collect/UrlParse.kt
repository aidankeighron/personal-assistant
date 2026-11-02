package com.aidan.pa.collect

/** Address-bar text -> (url, domain). Returns null for search terms / half-typed text. */
object UrlParse {
    private val SCHEME = Regex("^[a-zA-Z][a-zA-Z0-9+.-]*://")
    private val HOST = Regex("^([a-z0-9-]+\\.)+[a-z]{2,}(:\\d+)?$")
    private val IP = Regex("^\\d{1,3}(\\.\\d{1,3}){3}(:\\d+)?$")

    fun parse(text: CharSequence?): Pair<String, String>? {
        val raw = text?.toString()?.trim().orEmpty()
        if (raw.isEmpty() || raw.contains(' ') || !raw.contains('.')) return null
        val noScheme = raw.replace(SCHEME, "")
        val host = noScheme.substringBefore('/').substringBefore('?').substringBefore('#').lowercase()
        if (!(HOST.matches(host) || IP.matches(host))) return null
        val domain = host.removePrefix("www.").removePrefix("m.").substringBefore(':')
        return noScheme.removeSuffix("/") to domain
    }
}
