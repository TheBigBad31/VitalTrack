package ai.vitaltrack.bridge

import android.content.Context
import android.util.Log
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.records.*
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import androidx.work.CoroutineWorker
import androidx.work.Data
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
 * 
 * Tolérant aux pannes : chaque type de métrique Health Connect est isolé dans son propre try-catch
 * pour éviter qu'une permission manquante ou une exception sur un type (ex: BoneMass) ne bloque
 * toute la synchronisation des pas, poids, sommeil ou rythme cardiaque.
 */
class HealthSyncWorker(
    appContext: Context,
    workerParams: WorkerParameters
) : CoroutineWorker(appContext, workerParams) {

    private val httpClient = OkHttpClient.Builder()
        .followRedirects(true)
        .followSslRedirects(true)
        .connectTimeout(60, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .writeTimeout(60, TimeUnit.SECONDS)
        .build()

    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        val rawWebhookUrl = prefs.getString("webhook_url", null)
        val deviceToken = prefs.getString("device_token", null)

        if (rawWebhookUrl.isNullOrBlank() || deviceToken.isNullOrBlank()) {
            Log.w(TAG, "Paramètres webhook manquants. Configuration requise.")
            return Result.failure()
        }

        // Nettoyage et normalisation de l'URL cible
        var webhookUrl = rawWebhookUrl.trim()
        if (webhookUrl.endsWith("/")) {
            webhookUrl = webhookUrl.dropLast(1)
        }
        if (!webhookUrl.contains("/api/webhook")) {
            // Si l'utilisateur a rentré seulement le domaine ou une mauvaise sous-route
            webhookUrl = if (webhookUrl.endsWith("/api")) {
                "$webhookUrl/webhooks/health-connect"
            } else {
                "$webhookUrl/api/webhooks/health-connect"
            }
        }

        val healthConnectClient = HealthConnectClient.getOrCreate(applicationContext)

        return try {
            val now = Instant.now()
            val isFirstSync = !prefs.getBoolean("has_completed_first_sync", false)
            val isCatchupRequested = inputData.getBoolean("is_catchup", false)
            val isCatchup = isFirstSync || isCatchupRequested

            // Période d'interrogation : 7 jours pour un rattrapage / première synchro, 24 heures en routine
            val syncDays = if (isCatchup) 7L else 1L
            val startTime = now.minus(syncDays * 24L, ChronoUnit.HOURS)
            val timeRange = TimeRangeFilter.between(startTime, now)

            // Fenêtre spécifique d'aujourd'hui (depuis minuit) pour les pas et calories du jour
            val todayStart = LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant()
            val todayTimeRange = TimeRangeFilter.between(todayStart, now)

            val payload = JSONObject()
            payload.put("source", "health_connect")
            payload.put("synced_at", now.toString())
            payload.put("date", LocalDate.now().toString())
            payload.put("is_catchup", isCatchup)

            // 1. Sommeil (Sessions & Stages)
            try {
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
                    sObj.put("external_id", rec.metadata.id)
                    sObj.put("start_time", rec.startTime.toString())
                    sObj.put("end_time", rec.endTime.toString())
                    sObj.put("date", rec.endTime.atZone(ZoneId.systemDefault()).toLocalDate().toString())
                    val durMin = ChronoUnit.MINUTES.between(rec.startTime, rec.endTime)
                    sObj.put("duration_minutes", durMin)
                    sObj.put("title", rec.title ?: "Sommeil")

                    val stages = JSONArray()
                    var deepMin = 0L
                    var lightMin = 0L
                    var remMin = 0L
                    var awakeMin = 0L

                    for (st in rec.stages) {
                        val stObj = JSONObject()
                        val stageStr = mapSleepStage(st.stage)
                        stObj.put("stage", stageStr)
                        stObj.put("start_time", st.startTime.toString())
                        stObj.put("end_time", st.endTime.toString())
                        val stageDurSec = ChronoUnit.SECONDS.between(st.startTime, st.endTime)
                        stObj.put("duration_seconds", stageDurSec)
                        stages.put(stObj)

                        val stageDurMin = ChronoUnit.MINUTES.between(st.startTime, st.endTime)
                        when (stageStr) {
                            "deep" -> deepMin += stageDurMin
                            "light" -> lightMin += stageDurMin
                            "rem" -> remMin += stageDurMin
                            "awake" -> awakeMin += stageDurMin
                        }
                    }
                    sObj.put("stages", stages)
                    sObj.put("deep_minutes", deepMin)
                    sObj.put("light_minutes", lightMin)
                    sObj.put("rem_minutes", remMin)
                    sObj.put("awake_minutes", awakeMin)
                    sleepSessions.put(sObj)
                }
                if (sleepSessions.length() > 0) {
                    payload.put("sleep_sessions", sleepSessions)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire le sommeil depuis Health Connect", e)
            }

            // 2. Échantillons FC (HeartRate) avec sous-échantillonnage pour éviter le timeout
            try {
                val allSamples = mutableListOf<JSONObject>()
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
                        allSamples.add(samp)
                    }
                }
                val hrSamples = JSONArray()
                if (allSamples.size > 500) {
                    // Sous-échantillonnage régulier pour conserver la courbe sans surcharger le serveur
                    val step = (allSamples.size + 499) / 500
                    for (i in allSamples.indices step step) {
                        hrSamples.put(allSamples[i])
                    }
                } else {
                    for (samp in allSamples) {
                        hrSamples.put(samp)
                    }
                }
                if (hrSamples.length() > 0) {
                    payload.put("intraday_samples", hrSamples)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire les échantillons FC depuis Health Connect", e)
            }

            // 3. Pas (Steps) - Agrégation Health Connect officielle (déduplication automatique des sources)
            try {
                val stepsAgg = healthConnectClient.aggregate(
                    AggregateRequest(
                        metrics = setOf(StepsRecord.COUNT_TOTAL),
                        timeRangeFilter = todayTimeRange
                    )
                )
                val totalSteps = stepsAgg[StepsRecord.COUNT_TOTAL]
                if (totalSteps != null) {
                    payload.put("steps", totalSteps)
                } else {
                    // Fallback readRecords si l'agrégation retourne null
                    val stepsResp = healthConnectClient.readRecords(
                        ReadRecordsRequest(
                            recordType = StepsRecord::class,
                            timeRangeFilter = todayTimeRange
                        )
                    )
                    var fallbackSteps = 0L
                    for (rec in stepsResp.records) {
                        fallbackSteps += rec.count
                    }
                    payload.put("steps", fallbackSteps)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire/agréger les pas depuis Health Connect", e)
            }

            // 4. Calories actives - Agrégation Health Connect officielle (déduplication automatique des sources)
            try {
                val calAgg = healthConnectClient.aggregate(
                    AggregateRequest(
                        metrics = setOf(ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL),
                        timeRangeFilter = todayTimeRange
                    )
                )
                val activeCalEnergy = calAgg[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]
                if (activeCalEnergy != null) {
                    payload.put("active_calories_kcal", activeCalEnergy.inKilocalories)
                } else {
                    // Fallback readRecords
                    val calResp = healthConnectClient.readRecords(
                        ReadRecordsRequest(
                            recordType = ActiveCaloriesBurnedRecord::class,
                            timeRangeFilter = todayTimeRange
                        )
                    )
                    var fallbackCal = 0.0
                    for (rec in calResp.records) {
                        fallbackCal += rec.energy.inKilocalories
                    }
                    payload.put("active_calories_kcal", fallbackCal)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible d'agréger les calories actives depuis Health Connect", e)
            }

            // 5. Poids & Composition corporelle (Withings)
            try {
                val weightResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = WeightRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                weightResp.records.lastOrNull()?.let { lastWeight ->
                    payload.put("weight_kg", lastWeight.weight.inKilograms)
                    payload.put("weight_external_id", lastWeight.metadata.id)
                    val weightDate = lastWeight.time.atZone(ZoneId.systemDefault()).toLocalDate().toString()
                    payload.put("weight_date", weightDate)
                    // Si aucune date n'était définie ou pour compatibilité, mais sans écraser la date du jour du payload
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire le poids depuis Health Connect", e)
            }

            // BodyFatRecord (Withings / Health Connect)
            try {
                val bodyFatResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = BodyFatRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                bodyFatResp.records.lastOrNull()?.let { lastFat ->
                    payload.put("body_fat_pct", lastFat.percentage.value)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire la masse grasse depuis Health Connect", e)
            }

            // LeanBodyMassRecord (Masse musculaire en kg)
            try {
                val leanMassResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = LeanBodyMassRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                leanMassResp.records.lastOrNull()?.let { lastLean ->
                    payload.put("muscle_mass_kg", lastLean.mass.inKilograms)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire la masse musculaire depuis Health Connect", e)
            }

            // BoneMassRecord (Masse osseuse en kg si présent)
            try {
                val boneMassResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = BoneMassRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                boneMassResp.records.lastOrNull()?.let { lastBone ->
                    payload.put("bone_mass_kg", lastBone.mass.inKilograms)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire la masse osseuse depuis Health Connect", e)
            }

            // 6. Biométrie RingConn Gen 3 (HRV RMSSD, FC repos, SpO2)
            try {
                val hrvResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = HeartRateVariabilityRmssdRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                hrvResp.records.lastOrNull()?.let { lastHrv ->
                    payload.put("hrv_ms", lastHrv.heartRateVariabilityMillis)
                    payload.put("hrv_rmssd_ms", lastHrv.heartRateVariabilityMillis)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire le HRV depuis Health Connect", e)
            }

            try {
                val rhrResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = RestingHeartRateRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                rhrResp.records.lastOrNull()?.let { lastRhr ->
                    payload.put("resting_hr_bpm", lastRhr.beatsPerMinute)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire la FC de repos depuis Health Connect", e)
            }

            try {
                val spo2Resp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = OxygenSaturationRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                spo2Resp.records.lastOrNull()?.let { lastSpo2 ->
                    payload.put("spo2_pct", lastSpo2.percentage.value)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire la SpO2 depuis Health Connect", e)
            }

            // 7. Séances d'entraînement (ExerciseSessionRecord / Workouts) avec calories et distance associées
            try {
                val exerciseResp = healthConnectClient.readRecords(
                    ReadRecordsRequest(
                        recordType = ExerciseSessionRecord::class,
                        timeRangeFilter = timeRange
                    )
                )
                val workoutsArray = JSONArray()
                for (ex in exerciseResp.records) {
                    val wObj = JSONObject()
                    wObj.put("id", ex.metadata.id)
                    wObj.put("external_id", ex.metadata.id)
                    wObj.put("workout_type", mapExerciseType(ex.exerciseType))
                    wObj.put("start_time", ex.startTime.toString())
                    wObj.put("end_time", ex.endTime.toString())
                    val durMin = ChronoUnit.MINUTES.between(ex.startTime, ex.endTime)
                    wObj.put("duration_minutes", durMin)
                    if (!ex.title.isNullOrBlank()) {
                        wObj.put("notes", ex.title)
                    }

                    // Récupérer les calories associées à la séance d'entraînement
                    var workoutCalories = 0.0
                    try {
                        val wCalAgg = healthConnectClient.aggregate(
                            AggregateRequest(
                                metrics = setOf(
                                    TotalCaloriesBurnedRecord.ENERGY_TOTAL,
                                    ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL
                                ),
                                timeRangeFilter = TimeRangeFilter.between(ex.startTime, ex.endTime)
                            )
                        )
                        val totalCal = wCalAgg[TotalCaloriesBurnedRecord.ENERGY_TOTAL]?.inKilocalories
                        val activeCal = wCalAgg[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]?.inKilocalories
                        workoutCalories = totalCal ?: activeCal ?: 0.0
                    } catch (ce: Exception) {
                        Log.d(TAG, "Impossible d'agréger les calories pour la séance ${ex.metadata.id}", ce)
                    }
                    wObj.put("calories_kcal", workoutCalories)

                    // Récupérer la distance et la fréquence cardiaque moyenne
                    try {
                        val wMetricsAgg = healthConnectClient.aggregate(
                            AggregateRequest(
                                metrics = setOf(
                                    DistanceRecord.DISTANCE_TOTAL,
                                    HeartRateRecord.BPM_AVG,
                                    HeartRateRecord.BPM_MAX
                                ),
                                timeRangeFilter = TimeRangeFilter.between(ex.startTime, ex.endTime)
                            )
                        )
                        wMetricsAgg[DistanceRecord.DISTANCE_TOTAL]?.inMeters?.let { dist ->
                            wObj.put("distance_meters", dist)
                        }
                        wMetricsAgg[HeartRateRecord.BPM_AVG]?.let { avgHr ->
                            wObj.put("avg_hr_bpm", avgHr.toInt())
                        }
                        wMetricsAgg[HeartRateRecord.BPM_MAX]?.let { maxHr ->
                            wObj.put("max_hr_bpm", maxHr.toInt())
                        }
                    } catch (me: Exception) {
                        Log.d(TAG, "Impossible d'agréger distance/FC pour la séance ${ex.metadata.id}", me)
                    }

                    workoutsArray.put(wObj)
                }
                if (workoutsArray.length() > 0) {
                    payload.put("workouts", workoutsArray)
                }
            } catch (e: Exception) {
                Log.w(TAG, "Impossible de lire les séances de sport depuis Health Connect", e)
            }

            // Calcul du nombre de métriques / types envoyés
            var metricsCount = 0
            if (payload.has("steps") && payload.getLong("steps") > 0) metricsCount++
            if (payload.has("active_calories_kcal")) metricsCount++
            if (payload.has("weight_kg")) metricsCount++
            if (payload.has("body_fat_pct")) metricsCount++
            if (payload.has("muscle_mass_kg")) metricsCount++
            if (payload.has("hrv_ms")) metricsCount++
            if (payload.has("resting_hr_bpm")) metricsCount++
            if (payload.has("spo2_pct")) metricsCount++
            if (payload.has("sleep_sessions")) metricsCount += payload.getJSONArray("sleep_sessions").length()
            if (payload.has("workouts")) metricsCount += payload.getJSONArray("workouts").length()
            if (payload.has("intraday_samples")) metricsCount += payload.getJSONArray("intraday_samples").length()

            // 8. Envoi au Webhook VitalTrack avec Token individuel
            val jsonMedia = "application/json; charset=utf-8".toMediaType()
            val requestBody = payload.toString().toRequestBody(jsonMedia)

            val request = Request.Builder()
                .url(webhookUrl)
                .addHeader("X-Webhook-Token", deviceToken)
                .addHeader("Content-Type", "application/json")
                .post(requestBody)
                .build()

            httpClient.newCall(request).execute().use { response ->
                val respBody = response.body?.string() ?: ""
                val editor = prefs.edit()
                editor.putInt("last_http_code", response.code)
                editor.putString("last_sync_attempt", now.toString())
                if (response.isSuccessful) {
                    Log.i(TAG, "Ingestion VitalTrack réussie: ${response.code} - $respBody")
                    editor.putString("last_sync_timestamp", now.toString())
                    editor.putInt("last_sync_metrics_count", metricsCount)
                    editor.remove("last_sync_error")
                    if (isFirstSync) {
                        editor.putBoolean("has_completed_first_sync", true)
                    }
                    editor.apply()
                    val output = Data.Builder()
                        .putInt("metrics_count", metricsCount)
                        .putInt("http_code", response.code)
                        .build()
                    Result.success(output)
                } else {
                    Log.e(TAG, "Erreur serveur VitalTrack HTTP: ${response.code} - $respBody")
                    editor.putString("last_sync_error", "HTTP ${response.code}: ${respBody.take(100)}")
                    editor.apply()
                    val output = Data.Builder()
                        .putInt("http_code", response.code)
                        .putString("error_message", "HTTP ${response.code}: ${respBody.take(100)}")
                        .build()
                    Result.failure(output)
                }
            }
        } catch (e: Exception) {
            Log.e(TAG, "Erreur synchronisation Health Connect", e)
            val prefs = applicationContext.getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
            prefs.edit()
                .putString("last_sync_attempt", Instant.now().toString())
                .putString("last_sync_error", e.message?.take(100) ?: "Exception réseau/locale")
                .apply()
            val output = Data.Builder()
                .putString("error_message", e.message?.take(100) ?: "Exception")
                .build()
            Result.failure(output)
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

    private fun mapExerciseType(exerciseCode: Int): String {
        return when (exerciseCode) {
            ExerciseSessionRecord.EXERCISE_TYPE_RUNNING -> "running"
            ExerciseSessionRecord.EXERCISE_TYPE_WALKING -> "walking"
            ExerciseSessionRecord.EXERCISE_TYPE_BIKING -> "cycling"
            ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_POOL,
            ExerciseSessionRecord.EXERCISE_TYPE_SWIMMING_OPEN_WATER -> "swimming"
            ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING,
            ExerciseSessionRecord.EXERCISE_TYPE_STRENGTH_TRAINING -> "strength"
            ExerciseSessionRecord.EXERCISE_TYPE_YOGA -> "yoga"
            else -> "workout"
        }
    }

    companion object {
        const val TAG = "HealthSyncWorker"
    }
}
