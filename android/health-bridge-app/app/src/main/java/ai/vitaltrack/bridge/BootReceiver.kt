package ai.vitaltrack.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.work.*
import java.util.concurrent.TimeUnit

/**
 * Receiver pour replanifier et forcer une synchronisation dès le démarrage du téléphone (BALI-193).
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Log.i("BootReceiver", "Démarrage Android détecté (BOOT_COMPLETED) : replanification et sync de rattrapage")
            val prefs = context.getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
            val autoSync = prefs.getBoolean("auto_sync_enabled", true)
            if (autoSync) {
                val constraints = Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()

                val periodicSync = PeriodicWorkRequestBuilder<HealthSyncWorker>(15, TimeUnit.MINUTES)
                    .setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
                    .build()

                WorkManager.getInstance(context).enqueueUniquePeriodicWork(
                    "VitalTrackHealthSync",
                    ExistingPeriodicWorkPolicy.UPDATE,
                    periodicSync
                )

                // Déclencher également un rattrapage immédiat (is_catchup=true) pour remonter les jours hors ligne
                val oneTimeCatchup = OneTimeWorkRequestBuilder<HealthSyncWorker>()
                    .setConstraints(constraints)
                    .setInputData(Data.Builder().putBoolean("is_catchup", true).build())
                    .build()
                WorkManager.getInstance(context).enqueue(oneTimeCatchup)
            }
        }
    }
}
