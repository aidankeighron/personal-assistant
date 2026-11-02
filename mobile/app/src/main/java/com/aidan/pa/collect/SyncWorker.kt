package com.aidan.pa.collect

import android.content.Context
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.aidan.pa.sync.Sync

/** Runs every 15 minutes even if the collector service was killed: app sessions + sync. */
class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        runCatching { UsageCollector.collect(applicationContext) }
        Sync.sync(applicationContext)
        return Result.success()
    }
}
