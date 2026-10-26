package ai.vitaltrack.bridge

import android.content.Context
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.work.*
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {

    private val permissions = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getReadPermission(OxygenSaturationRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(WeightRecord::class),
        HealthPermission.getReadPermission(BodyFatRecord::class),
        HealthPermission.getReadPermission(LeanBodyMassRecord::class),
        HealthPermission.getReadPermission(BoneMassRecord::class)
    )

    private val requestPermissionActivityContract =
        PermissionController.createRequestPermissionResultContract()

    private val requestPermissions =
        registerForActivityResult(requestPermissionActivityContract) { granted ->
            if (granted.containsAll(permissions)) {
                Toast.makeText(this, "Toutes les autorisations Health Connect accordées", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Certaines autorisations n'ont pas été accordées", Toast.LENGTH_LONG).show()
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)

        val layout = android.widget.LinearLayout(this).apply {
            orientation = android.widget.LinearLayout.VERTICAL
            setPadding(40, 60, 40, 40)
        }

        val titleView = TextView(this).apply {
            text = "VitalTrack — Passerelle Health Connect"
            textSize = 20f
            setTypeface(null, android.graphics.Typeface.BOLD)
        }
        layout.addView(titleView)

        val descView = TextView(this).apply {
            text = "Pont gratuit Android Xiaomi (HyperOS / MIUI) pour synchroniser RingConn Gen 3, Withings et le podomètre local avec VitalTrack."
            setPadding(0, 16, 0, 32)
        }
        layout.addView(descView)

        val urlInput = EditText(this).apply {
            hint = "URL Webhook (ex: https://vitaltrack.vercel.app/api/webhook/health)"
            setText(prefs.getString("webhook_url", "https://vitaltrack.vercel.app/api/webhook/health"))
        }
        layout.addView(urlInput)

        val tokenInput = EditText(this).apply {
            hint = "Jeton d'appareil individuel (X-Webhook-Token)"
            setText(prefs.getString("device_token", ""))
        }
        layout.addView(tokenInput)

        val btnPerms = Button(this).apply {
            text = "1. Accorder permissions Health Connect"
            setOnClickListener {
                val client = HealthConnectClient.getOrCreate(applicationContext)
                requestPermissions.launch(permissions)
            }
        }
        layout.addView(btnPerms)

        val btnSave = Button(this).apply {
            text = "2. Enregistrer & Activer Synchro Arrière-Plan (15 min)"
            setOnClickListener {
                val url = urlInput.text.toString().trim()
                val tok = tokenInput.text.toString().trim()
                if (url.isEmpty() || tok.isEmpty()) {
                    Toast.makeText(this@MainActivity, "Veuillez renseigner l'URL et le Token", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }

                prefs.edit()
                    .putString("webhook_url", url)
                    .putString("device_token", tok)
                    .apply()

                scheduleSyncWorker()
                Toast.makeText(this@MainActivity, "Configuration sauvegardée ! Synchronisation périodique active.", Toast.LENGTH_SHORT).show()
            }
        }
        layout.addView(btnSave)

        val btnSyncNow = Button(this).apply {
            text = "3. Synchroniser maintenant (Test immédiat)"
            setOnClickListener {
                val inputData = Data.Builder()
                    .putBoolean("is_catchup", true)
                    .build()

                val oneTimeWork = OneTimeWorkRequestBuilder<HealthSyncWorker>()
                    .setInputData(inputData)
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                    .build()
                WorkManager.getInstance(applicationContext).enqueue(oneTimeWork)
                Toast.makeText(this@MainActivity, "Rattrapage 7 jours lancé !", Toast.LENGTH_SHORT).show()
            }
        }
        layout.addView(btnSyncNow)

        setContentView(layout)
    }

    private fun scheduleSyncWorker() {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        val periodicSync = PeriodicWorkRequestBuilder<HealthSyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()

        WorkManager.getInstance(applicationContext).enqueueUniquePeriodicWork(
            "VitalTrackHealthSync",
            ExistingPeriodicWorkPolicy.UPDATE,
            periodicSync
        )
    }
}
