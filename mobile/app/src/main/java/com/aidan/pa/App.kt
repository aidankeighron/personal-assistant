package com.aidan.pa

import android.app.Application
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import com.aidan.pa.collect.SyncWorker
import com.aidan.pa.data.Db
import com.aidan.pa.data.Prefs
import java.util.concurrent.TimeUnit

class App : Application() {
    val db by lazy { Db(this) }
    val prefs by lazy { Prefs(this) }

    override fun onCreate() {
        super.onCreate()
        // Safety net: even if the collector service is killed, usage + sync run every 15 min
        // (the shortest interval WorkManager allows).
        WorkManager.getInstance(this).enqueueUniquePeriodicWork(
            "collect-sync",
            ExistingPeriodicWorkPolicy.KEEP,
            PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES).build(),
        )
    }
}

val android.content.Context.app: App get() = applicationContext as App
