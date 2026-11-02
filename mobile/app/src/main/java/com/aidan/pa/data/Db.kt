package com.aidan.pa.data

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

/** Local store. Everything stays on the phone (raw data screen) and is synced in batches. */
class Db(context: Context) : SQLiteOpenHelper(context, "tracker.db", null, 1) {

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL(
            """CREATE TABLE app_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, pkg TEXT NOT NULL,
               label TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL, synced INTEGER NOT NULL DEFAULT 0,
               UNIQUE(pkg, start))"""
        )
        db.execSQL(
            """CREATE TABLE web_visits (id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT NOT NULL,
               domain TEXT NOT NULL, browser TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
               synced INTEGER NOT NULL DEFAULT 0, UNIQUE(url, start))"""
        )
        db.execSQL(
            """CREATE TABLE locations (id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL UNIQUE,
               lat REAL NOT NULL, lon REAL NOT NULL, accuracy REAL NOT NULL, synced INTEGER NOT NULL DEFAULT 0)"""
        )
        db.execSQL("CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT)")
        db.execSQL("CREATE INDEX idx_app_start ON app_sessions(start)")
        db.execSQL("CREATE INDEX idx_web_start ON web_visits(start)")
        db.execSQL("CREATE INDEX idx_loc_ts ON locations(ts)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    // -- writes ---------------------------------------------------------------
    fun insertAppSessions(sessions: List<AppSession>) = writableDatabase.run {
        beginTransaction()
        try {
            for (s in sessions) insertWithOnConflict("app_sessions", null, ContentValues().apply {
                put("pkg", s.pkg); put("label", s.label); put("start", s.start); put("end", s.end)
            }, SQLiteDatabase.CONFLICT_IGNORE)
            setTransactionSuccessful()
        } finally { endTransaction() }
    }

    fun insertWebVisit(v: WebVisit) {
        writableDatabase.insertWithOnConflict("web_visits", null, ContentValues().apply {
            put("url", v.url); put("domain", v.domain); put("browser", v.browser); put("start", v.start); put("end", v.end)
        }, SQLiteDatabase.CONFLICT_IGNORE)
    }

    fun insertLocation(p: LocPoint) {
        writableDatabase.insertWithOnConflict("locations", null, ContentValues().apply {
            put("ts", p.ts); put("lat", p.lat); put("lon", p.lon); put("accuracy", p.accuracy.toDouble())
        }, SQLiteDatabase.CONFLICT_IGNORE)
    }

    // -- reads ----------------------------------------------------------------
    fun appSessions(from: Long, to: Long, unsyncedOnly: Boolean = false, limit: Int = 100_000): List<AppSession> =
        readableDatabase.rawQuery(
            "SELECT id, pkg, label, start, end FROM app_sessions WHERE end >= ? AND start < ?" +
                (if (unsyncedOnly) " AND synced = 0" else "") + " ORDER BY start LIMIT $limit",
            arrayOf(from.toString(), to.toString()),
        ).use { c ->
            buildList { while (c.moveToNext()) add(AppSession(c.getLong(0), c.getString(1), c.getString(2), c.getLong(3), c.getLong(4))) }
        }

    fun webVisits(from: Long, to: Long, unsyncedOnly: Boolean = false, limit: Int = 100_000): List<WebVisit> =
        readableDatabase.rawQuery(
            "SELECT id, url, domain, browser, start, end FROM web_visits WHERE end >= ? AND start < ?" +
                (if (unsyncedOnly) " AND synced = 0" else "") + " ORDER BY start LIMIT $limit",
            arrayOf(from.toString(), to.toString()),
        ).use { c ->
            buildList { while (c.moveToNext()) add(WebVisit(c.getLong(0), c.getString(1), c.getString(2), c.getString(3), c.getLong(4), c.getLong(5))) }
        }

    fun locations(from: Long, to: Long, unsyncedOnly: Boolean = false, limit: Int = 100_000): List<LocPoint> =
        readableDatabase.rawQuery(
            "SELECT id, ts, lat, lon, accuracy FROM locations WHERE ts >= ? AND ts < ?" +
                (if (unsyncedOnly) " AND synced = 0" else "") + " ORDER BY ts LIMIT $limit",
            arrayOf(from.toString(), to.toString()),
        ).use { c ->
            buildList { while (c.moveToNext()) add(LocPoint(c.getLong(0), c.getLong(1), c.getDouble(2), c.getDouble(3), c.getFloat(4))) }
        }

    fun lastLocationTs(): Long =
        readableDatabase.rawQuery("SELECT MAX(ts) FROM locations", null).use { c -> if (c.moveToFirst()) c.getLong(0) else 0L }

    fun pendingCounts(): Map<String, Int> = listOf("app_sessions", "web_visits", "locations").associateWith { t ->
        readableDatabase.rawQuery("SELECT COUNT(*) FROM $t WHERE synced = 0", null).use { c -> if (c.moveToFirst()) c.getInt(0) else 0 }
    }

    fun markSynced(table: String, ids: List<Long>) {
        if (ids.isEmpty()) return
        require(table in setOf("app_sessions", "web_visits", "locations"))
        writableDatabase.execSQL("UPDATE $table SET synced = 1 WHERE id IN (${ids.joinToString(",")})")
    }

    /** Keep the phone's copy bounded: drop synced rows older than [days]. */
    fun prune(days: Int = 90) {
        val cutoff = System.currentTimeMillis() - days * 86_400_000L
        writableDatabase.run {
            delete("app_sessions", "synced = 1 AND end < ?", arrayOf(cutoff.toString()))
            delete("web_visits", "synced = 1 AND end < ?", arrayOf(cutoff.toString()))
            delete("locations", "synced = 1 AND ts < ?", arrayOf(cutoff.toString()))
        }
    }

    // -- kv -------------------------------------------------------------------
    fun kvGet(key: String): String? =
        readableDatabase.rawQuery("SELECT value FROM kv WHERE key = ?", arrayOf(key)).use { c -> if (c.moveToFirst()) c.getString(0) else null }

    fun kvSet(key: String, value: String?) {
        if (value == null) writableDatabase.delete("kv", "key = ?", arrayOf(key))
        else writableDatabase.insertWithOnConflict("kv", null, ContentValues().apply { put("key", key); put("value", value) },
            SQLiteDatabase.CONFLICT_REPLACE)
    }
}
