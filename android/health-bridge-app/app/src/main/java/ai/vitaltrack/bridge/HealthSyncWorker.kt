package ai.vitaltrack.bridge

import android.content.Context
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.*
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.temporal.ChronoUnit
import java.util.concurrent.TimeUnit

/**
 * Worker d'arrière-plan Android pour lire Health Connect (RingConn, Withings, Podomètre Xiaomi)
 * et pousser un lot incrémental JSON vers le webhook VitalTrack sécurisé.
 */
class HealthSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        val webhookUrl = prefs.getString("webhook_url", null)
        val deviceToken = prefs.getString("device_token", null)

        if (webhookUrl.isNullOrBlank() || deviceToken.isNullOrBlank()) {
            Log.w(TAG, "Paramètres webhook manquants. Configuration requise.")
            return Result.failure()
        }

        val healthConnectClient = HealthConnectClient.getOrCreate(applicationContext)

        return try {
            val now = Instant.now()
            val startTime = now.minus(24, ChronoUnit.HOURS)
            val timeRange = TimeRangeFilter.between(startTime, now)

            val payload = JSONObject()
            payload.put("source", "health_connect")
            payload.put("synced_at", now.toString())
            payload.put("date", LocalDate.now().toString())

            // 1. Sommeil (Sessions & Stages)
            val sleepSessions = JSONArray()
            val sleepResp = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = SleepSessionRecord::class,
                    timeRangeFilter = timeRange
                )
            )
            for (rec in sleepResp.records) {
                val sObj = JSONObject()
                sObj.put("id", rec.metadata.id)
                sObj.put("start_time", rec.startTime.toString())
                sObj.put("end_time", rec.endTime.toString())
                val durMin = ChronoUnit.MINUTES.between(rec.startTime, rec.endTime)
                sObj.put("duration_minutes", durMin)
                sObj.put("title", rec.title ?: "Sommeil")

                val stages = JSONArray()
                for (st in rec.stages) {
                    val stObj = JSONObject()
                    stObj.put("stage", mapSleepStage(st.stage))
                    stObj.put("start_time", st.startTime.toString())
                    stObj.put("end_time", st.endTime.toString())
                    stObj.put("duration_seconds", ChronoUnit.SECONDS.between(st.startTime, st.endTime))
                    stages.put(stObj)
                }
                sObj.put("stages", stages)
                sleepSessions.put(sObj)
            }
            if (sleepSessions.length() > 0) {
                payload.put("sleep_sessions", sleepSessions)
            }

            // 2. Échantillons FC (HeartRate)
            val hrSamples = JSONArray()
            val hrResp = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = HeartRateRecord::class,
                    timeRangeFilter = timeRange
                )
            )
            for (rec in hrResp.records) {
                for (sample in rec.samples) {
                    val samp = JSONObject()
                    samp.put("metric_type", "hr")
                    samp.put("timestamp", sample.time.toString())
                    samp.put("value", sample.beatsPerMinute)
                    samp.put("unit", "bpm")
                    hrSamples.put(samp)
                }
            }
            if (hrSamples.length() > 0) {
                payload.put("intraday_samples", hrSamples)
            }

            // 3. Pas (Steps)
            val stepsResp = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = StepsRecord::class,
                    timeRangeFilter = timeRange
                )
            )
            var totalSteps = 0L
            for (rec in stepsResp.records) {
                totalSteps += rec.count
            }
            payload.put("steps", totalSteps)

            // 4. Calories
            val calResp = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = ActiveCaloriesBurnedRecord::class,
                    timeRangeFilter = timeRange
                )
            )
            var totalActiveCal = 0.0
            for (rec in calResp.records) {
                totalActiveCal += rec.energy.inKilocalories
            }
            payload.put("active_calories_kcal", totalActiveCal)

            // 5. Poids (Weight)
            val weightResp = healthConnectClient.readRecords(
                ReadRecordsRequest(
                    recordType = WeightRecord::class,
                    timeRangeFilter = timeRange
                )
            )
            weightResp.records.lastOrNull()?.let { lastWeight ->
                payload.put("weight_kg", lastWeight.weight.inKilograms)
                payload.put("weight_external_id", lastWeight.metadata.id)
            }

            // 6. Envoi au Webhook VitalTrack avec Token individuel
            val jsonMedia = "application/json; charset=utf-8".toMediaType()
            val requestBody = payload.toString().toRequestBody(jsonMedia)

            val request = Request.Builder()
                .url(webhookUrl)
                .addHeader("X-Webhook-Token", deviceToken)
                .addHeader("Content-Type", "application/json")
                .post(requestBody)
                .build()

            httpClient.newCall(request).execute().use { response ->
                if (response.isSuccessful) {
                    Log.i(TAG, "Ingestion VitalTrack réussie: ${response.code}")
                    Result.success()
                } else {
                    Log.e(TAG, "Erreur serveur VitalTrack HTTP: ${response.code}")
                    Result.retry()
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Erreur synchronisation Health Connect", e)
            Result.retry()
        }
    }

    private fun mapSleepStage(stageCode: Int): String {
        return when (stageCode) {
            SleepSessionRecord.STAGE_TYPE_DEEP -> "deep"
            SleepSessionRecord.STAGE_TYPE_LIGHT -> "light"
            SleepSessionRecord.STAGE_TYPE_REM -> "rem"
            SleepSessionRecord.STAGE_TYPE_AWAKE -> "awake"
            else -> "light"
        }
    }

    companion object {
        const val TAG = "HealthSyncWorker"
    }
}
