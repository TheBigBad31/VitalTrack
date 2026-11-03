package ai.vitaltrack.bridge

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import androidx.work.*
import java.util.concurrent.TimeUnit

/**
 * Receiver démarré au boot de l'appareil (BOOT_COMPLETED / QUICKBOOT)
 * Replanifie le travail périodique HealthSyncWorker et déclenche une synchronisation
 * immédiate si auto_sync_enabled est actif et que la passerelle est configurée.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        val action = intent?.action
        if (action == Intent.ACTION_BOOT_COMPLETED ||
            action == "android.intent.action.QUICKBOOT_POWERON" ||
            action == Intent.ACTION_MY_PACKAGE_REPLACED) {

            Log.i(TAG, "Événement de démarrage détecté ($action). Vérification de la configuration VitalTrack.")
            val prefs = context.getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
            val isAutoSync = prefs.getBoolean("auto_sync_enabled", true)
            val hasToken = !prefs.getString("device_token", null).isNullOrBlank()
            val hasUrl = !prefs.getString("webhook_url", null).isNullOrBlank()

            if (isAutoSync && hasToken && hasUrl) {
                val constraints = Constraints.Builder()
                    .setRequiredNetworkType(NetworkType.CONNECTED)
                    .build()

                val periodicSync = PeriodicWorkRequestBuilder<HealthSyncWorker>(15, TimeUnit.MINUTES)
                    .setConstraints(constraints)
                    .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
                    .build()

                val workManager = WorkManager.getInstance(context)
                workManager.enqueueUniquePeriodicWork(
                    "VitalTrackHealthSync",
                    ExistingPeriodicWorkPolicy.UPDATE,
                    periodicSync
                )

                val oneTimeBootSync = OneTimeWorkRequestBuilder<HealthSyncWorker>()
                    .setConstraints(constraints)
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                    .build()

                workManager.enqueue(oneTimeBootSync)
                Log.i(TAG, "Planification périodique 15 min réactivée et sync de boot enfilee avec succès.")
            } else {
                Log.d(TAG, "Auto-sync désactivée ou paramètres manquants au boot.")
            }
        }
    }

    companion object {
        private const val TAG = "VitalTrackBootReceiver"
    }
}
