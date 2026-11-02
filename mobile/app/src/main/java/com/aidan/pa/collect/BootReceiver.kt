package com.aidan.pa.collect

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.aidan.pa.app

/** Restart collection after a reboot or an app update, if it was on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (context.app.prefs.collecting) runCatching { CollectorService.start(context) }
    }
}
