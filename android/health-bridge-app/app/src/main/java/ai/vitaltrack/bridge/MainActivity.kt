package ai.vitaltrack.bridge

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.util.Base64
import android.view.Gravity
import android.view.View
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.cardview.widget.CardView
import androidx.core.widget.NestedScrollView
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.work.*
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.text.SimpleDateFormat
import java.util.*
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
                Toast.makeText(this, "Autorisations partielles accordées (${granted.size}/${permissions.size})", Toast.LENGTH_LONG).show()
            }
        }

    // Capture photo de repas
    private var capturedBitmap: Bitmap? = null
    private var lastPhotoDataUrl: String? = null
    private var currentEstimateResult: JSONObject? = null
    private var selectedMealType: String = "lunch"

    private lateinit var photoPreview: ImageView
    private lateinit var btnRetakePhoto: Button
    private lateinit var btnEstimatePhoto: Button
    private lateinit var estimateProgressBar: ProgressBar
    private lateinit var resultCard: CardView
    private lateinit var resultTitle: TextView
    private lateinit var resultCalories: TextView
    private lateinit var resultMacros: TextView
    private lateinit var resultIngredients: TextView
    private lateinit var btnSaveToJournal: Button

    private val takePicturePreviewLauncher =
        registerForActivityResult(ActivityResultContracts.TakePicturePreview()) { bitmap: Bitmap? ->
            if (bitmap != null) {
                capturedBitmap = bitmap
                photoPreview.setImageBitmap(bitmap)
                photoPreview.visibility = View.VISIBLE
                btnRetakePhoto.visibility = View.VISIBLE
                btnEstimatePhoto.visibility = View.VISIBLE
                resultCard.visibility = View.GONE
                currentEstimateResult = null

                // Convertir en Base64 data-url
                val outputStream = ByteArrayOutputStream()
                bitmap.compress(Bitmap.CompressFormat.JPEG, 85, outputStream)
                val base64Str = Base64.encodeToString(outputStream.toByteArray(), Base64.NO_WRAP)
                lastPhotoDataUrl = "data:image/jpeg;base64,$base64Str"
                Toast.makeText(this, "Photo capturée avec succès !", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Prise de photo annulée", Toast.LENGTH_SHORT).show()
            }
        }

    private val requestCameraPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { isGranted ->
            if (isGranted) {
                takePicturePreviewLauncher.launch(null)
            } else {
                Toast.makeText(this, "Permission Appareil Photo requise pour photographier votre plat", Toast.LENGTH_LONG).show()
            }
        }

    private val httpClient = OkHttpClient.Builder()
        .connectTimeout(30, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)

        val scrollView = NestedScrollView(this).apply {
            isFillViewport = true
        }

        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(36, 48, 36, 48)
        }

        // En-tête
        val titleView = TextView(this).apply {
            text = "VitalTrack — Passerelle Health & Vision"
            textSize = 21f
            setTextColor(Color.parseColor("#111827"))
            setTypeface(null, Typeface.BOLD)
        }
        layout.addView(titleView)

        val descView = TextView(this).apply {
            text = "Synchronisation santé (Health Connect / RingConn / Withings) & Analyse photo instantanée de repas par IA."
            setTextColor(Color.parseColor("#4B5563"))
            textSize = 14f
            setPadding(0, 12, 0, 24)
        }
        layout.addView(descView)

        val defaultUrl = "https://vital-track-one.vercel.app/api/webhooks/health-connect"
        val savedUrl = prefs.getString("webhook_url", null) ?: defaultUrl
        val savedToken = prefs.getString("device_token", null) ?: ""

        val urlInput = EditText(this).apply {
            hint = "URL Webhook (ex: $defaultUrl)"
            setText(savedUrl)
            textSize = 14f
        }
        layout.addView(urlInput)

        val tokenInput = EditText(this).apply {
            hint = "Jeton d'appareil individuel (X-Webhook-Token)"
            setText(savedToken)
            textSize = 14f
        }
        layout.addView(tokenInput)

        // ==========================================
        // SECTION 1 : CAPTURE PHOTO & ESTIMATION IA
        // ==========================================
        val sectionPhotoTitle = TextView(this).apply {
            text = "📸 Nutrition Photo & Estimation IA"
            textSize = 17f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#1E3A8A"))
            setPadding(0, 28, 0, 12)
        }
        layout.addView(sectionPhotoTitle)

        // Sélecteur de type de repas
        val mealTypeLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, 12)
        }
        val mealTypeLabel = TextView(this).apply {
            text = "Type de repas : "
            textSize = 14f
            setTextColor(Color.parseColor("#374151"))
        }
        val mealTypeSpinner = Spinner(this)
        val mealTypes = arrayOf("Déjeuner (lunch)", "Dîner (dinner)", "Petit-déjeuner (breakfast)", "Collation (snack)")
        val mealTypeCodes = arrayOf("lunch", "dinner", "breakfast", "snack")
        val spinnerAdapter = ArrayAdapter(this, android.R.layout.simple_spinner_dropdown_item, mealTypes)
        mealTypeSpinner.adapter = spinnerAdapter
        mealTypeSpinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                selectedMealType = mealTypeCodes[position]
            }
            override fun onNothingSelected(parent: AdapterView<*>?) {}
        }
        mealTypeLayout.addView(mealTypeLabel)
        mealTypeLayout.addView(mealTypeSpinner)
        layout.addView(mealTypeLayout)

        // Bouton Prise de photo
        val btnTakePhoto = Button(this).apply {
            text = "📷 Prendre en photo mon assiette"
            setBackgroundColor(Color.parseColor("#2563EB"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                requestCameraPermissionLauncher.launch(android.Manifest.permission.CAMERA)
            }
        }
        layout.addView(btnTakePhoto)

        // Aperçu de l'image capturée
        photoPreview = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                550
            ).apply {
                setMargins(0, 16, 0, 12)
            }
            scaleType = ImageView.ScaleType.CENTER_CROP
            visibility = View.GONE
            setBackgroundColor(Color.parseColor("#F3F4F6"))
        }
        layout.addView(photoPreview)

        // Actions photo (Reprendre / Analyser)
        val photoActionsLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 12)
        }

        btnRetakePhoto = Button(this).apply {
            text = "🔄 Reprendre"
            visibility = View.GONE
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginEnd = 8
            }
            setOnClickListener {
                requestCameraPermissionLauncher.launch(android.Manifest.permission.CAMERA)
            }
        }

        btnEstimatePhoto = Button(this).apply {
            text = "✨ Analyser avec l'IA"
            visibility = View.GONE
            setBackgroundColor(Color.parseColor("#10B981"))
            setTextColor(Color.WHITE)
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                marginStart = 8
            }
            setOnClickListener {
                val serverBaseUrl = extractBaseUrl(urlInput.text.toString().trim())
                val token = tokenInput.text.toString().trim()
                if (serverBaseUrl.isEmpty()) {
                    Toast.makeText(this@MainActivity, "Veuillez configurer l'URL du serveur VitalTrack", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                if (lastPhotoDataUrl == null) {
                    Toast.makeText(this@MainActivity, "Veuillez d'abord prendre une photo", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                analyzeMealPhoto(serverBaseUrl, token, lastPhotoDataUrl!!, selectedMealType)
            }
        }

        photoActionsLayout.addView(btnRetakePhoto)
        photoActionsLayout.addView(btnEstimatePhoto)
        layout.addView(photoActionsLayout)

        estimateProgressBar = ProgressBar(this).apply {
            visibility = View.GONE
            setPadding(0, 16, 0, 16)
        }
        layout.addView(estimateProgressBar)

        // Carte des résultats de l'estimation
        resultCard = CardView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply {
                setMargins(0, 12, 0, 20)
            }
            radius = 16f
            cardElevation = 6f
            setCardBackgroundColor(Color.parseColor("#F8FAFC"))
            visibility = View.GONE
            setContentPadding(28, 28, 28, 28)
        }

        val cardInnerLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
        }

        resultTitle = TextView(this).apply {
            text = "Plat estimé"
            textSize = 18f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#0F172A"))
        }
        cardInnerLayout.addView(resultTitle)

        resultCalories = TextView(this).apply {
            text = "0 kcal"
            textSize = 22f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#EA580C"))
            setPadding(0, 8, 0, 8)
        }
        cardInnerLayout.addView(resultCalories)

        resultMacros = TextView(this).apply {
            text = "P: 0g | G: 0g | L: 0g"
            textSize = 14f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#334155"))
        }
        cardInnerLayout.addView(resultMacros)

        resultIngredients = TextView(this).apply {
            text = "Ingrédients détectés"
            textSize = 13f
            setTextColor(Color.parseColor("#64748B"))
            setPadding(0, 8, 0, 16)
        }
        cardInnerLayout.addView(resultIngredients)

        btnSaveToJournal = Button(this).apply {
            text = "💾 Enregistrer dans mon journal"
            setBackgroundColor(Color.parseColor("#4F46E5"))
            setTextColor(Color.WHITE)
            setOnClickListener {
                val serverBaseUrl = extractBaseUrl(urlInput.text.toString().trim())
                val token = tokenInput.text.toString().trim()
                if (currentEstimateResult != null) {
                    saveMealToJournal(serverBaseUrl, token, currentEstimateResult!!, lastPhotoDataUrl, selectedMealType)
                }
            }
        }
        cardInnerLayout.addView(btnSaveToJournal)
        resultCard.addView(cardInnerLayout)
        layout.addView(resultCard)

        // ==========================================
        // SECTION 2 : SANTÉ CONNECTÉE & WORKMANAGER
        // ==========================================
        val sectionHealthTitle = TextView(this).apply {
            text = "⌚ Synchronisation Health Connect"
            textSize = 17f
            setTypeface(null, Typeface.BOLD)
            setTextColor(Color.parseColor("#1E3A8A"))
            setPadding(0, 24, 0, 12)
        }
        layout.addView(sectionHealthTitle)

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
            text = "3. Synchroniser Santé Maintenant (Test Immédiat)"
            setOnClickListener {
                val url = urlInput.text.toString().trim()
                val tok = tokenInput.text.toString().trim()
                if (url.isNotEmpty() && tok.isNotEmpty()) {
                    prefs.edit()
                        .putString("webhook_url", url)
                        .putString("device_token", tok)
                        .apply()
                }

                val inputData = Data.Builder()
                    .putBoolean("is_catchup", true)
                    .build()

                val oneTimeWork = OneTimeWorkRequestBuilder<HealthSyncWorker>()
                    .setInputData(inputData)
                    .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
                    .build()
                WorkManager.getInstance(applicationContext).enqueue(oneTimeWork)
                Toast.makeText(this@MainActivity, "Synchronisation lancée ! Vérifiez vos métriques.", Toast.LENGTH_SHORT).show()
            }
        }
        layout.addView(btnSyncNow)

        scrollView.addView(layout)
        setContentView(scrollView)
    }

    private fun extractBaseUrl(url: String): String {
        if (url.isEmpty()) return ""
        val index = url.indexOf("/api/")
        return if (index != -1) {
            url.substring(0, index)
        } else {
            url.trimEnd('/')
        }
    }

    private fun analyzeMealPhoto(baseUrl: String, token: String, photoDataUrl: String, mealType: String) {
        estimateProgressBar.visibility = View.VISIBLE
        btnEstimatePhoto.isEnabled = false

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val endpoint = "$baseUrl/api/meals/estimate"
                val jsonBody = JSONObject().apply {
                    put("photo_data_url", photoDataUrl)
                    put("meal_type", mealType)
                    put("portion_scale", 1.0)
                }

                val reqBuilder = Request.Builder()
                    .url(endpoint)
                    .post(jsonBody.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))

                if (token.isNotEmpty()) {
                    reqBuilder.addHeader("X-Webhook-Token", token)
                    reqBuilder.addHeader("Authorization", "Bearer $token")
                }

                val response = httpClient.newCall(reqBuilder.build()).execute()
                val bodyStr = response.body?.string() ?: ""

                withContext(Dispatchers.Main) {
                    estimateProgressBar.visibility = View.GONE
                    btnEstimatePhoto.isEnabled = true

                    if (response.isSuccessful && bodyStr.isNotEmpty()) {
                        val json = JSONObject(bodyStr)
                        currentEstimateResult = json
                        displayEstimateResult(json)
                        Toast.makeText(this@MainActivity, "Estimation calorique réussie !", Toast.LENGTH_SHORT).show()
                    } else {
                        Toast.makeText(this@MainActivity, "Erreur lors de l'analyse : ${response.code}", Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    estimateProgressBar.visibility = View.GONE
                    btnEstimatePhoto.isEnabled = true
                    Toast.makeText(this@MainActivity, "Erreur réseau / serveur : ${e.localizedMessage}", Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun displayEstimateResult(json: JSONObject) {
        val dishName = json.optString("dish_name", "Plat analysé")
        val calories = json.optDouble("total_calories_kcal", 0.0)
        val protein = json.optDouble("protein_g", 0.0)
        val carbs = json.optDouble("carbs_g", 0.0)
        val fat = json.optDouble("fat_g", 0.0)
        val fiber = json.optDouble("fiber_g", 0.0)

        resultTitle.text = dishName
        resultCalories.text = "${calories.toInt()} kcal"
        resultMacros.text = "Protéines : ${protein}g | Glucides : ${carbs}g | Lipides : ${fat}g | Fibres : ${fiber}g"

        val itemsArray = json.optJSONArray("items") ?: JSONArray()
        val itemsSummary = StringBuilder()
        for (i in 0 until itemsArray.length()) {
            val itemObj = itemsArray.getJSONObject(i)
            val name = itemObj.optString("name", "Aliment")
            val cal = itemObj.optDouble("calories_kcal", 0.0)
            itemsSummary.append("• ").append(name).append(" (").append(cal.toInt()).append(" kcal)\n")
        }

        if (itemsSummary.isEmpty()) {
            resultIngredients.text = "Analyse globale estimée."
        } else {
            resultIngredients.text = itemsSummary.toString().trimEnd()
        }

        resultCard.visibility = View.VISIBLE
    }

    private fun saveMealToJournal(baseUrl: String, token: String, estimate: JSONObject, photoDataUrl: String?, mealType: String) {
        estimateProgressBar.visibility = View.VISIBLE
        btnSaveToJournal.isEnabled = false

        CoroutineScope(Dispatchers.IO).launch {
            try {
                val endpoint = "$baseUrl/api/meals"
                val todayStr = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(Date())

                val jsonBody = JSONObject().apply {
                    put("date", todayStr)
                    put("meal_type", mealType)
                    put("photo_data_url", photoDataUrl)
                    put("portion_scale", estimate.optDouble("portion_scale", 1.0))
                    put("total_calories_kcal", estimate.optDouble("total_calories_kcal", 0.0))
                    put("protein_g", estimate.optDouble("protein_g", 0.0))
                    put("carbs_g", estimate.optDouble("carbs_g", 0.0))
                    put("fat_g", estimate.optDouble("fat_g", 0.0))
                    put("fiber_g", estimate.optDouble("fiber_g", 0.0))
                    put("meal_name", estimate.optString("dish_name", "Repas photo"))
                    if (estimate.has("items")) {
                        put("items", estimate.getJSONArray("items"))
                    }
                }

                val reqBuilder = Request.Builder()
                    .url(endpoint)
                    .post(jsonBody.toString().toRequestBody("application/json; charset=utf-8".toMediaType()))

                if (token.isNotEmpty()) {
                    reqBuilder.addHeader("X-Webhook-Token", token)
                    reqBuilder.addHeader("Authorization", "Bearer $token")
                }

                val response = httpClient.newCall(reqBuilder.build()).execute()
                val bodyStr = response.body?.string() ?: ""

                withContext(Dispatchers.Main) {
                    estimateProgressBar.visibility = View.GONE
                    btnSaveToJournal.isEnabled = true

                    if (response.isSuccessful) {
                        Toast.makeText(this@MainActivity, "✅ Repas enregistré dans votre journal VitalTrack !", Toast.LENGTH_LONG).show()
                        btnSaveToJournal.text = "✓ Enregistré dans le journal"
                        btnSaveToJournal.isEnabled = false
                    } else {
                        Toast.makeText(this@MainActivity, "Erreur enregistrement : ${response.code} ($bodyStr)", Toast.LENGTH_LONG).show()
                    }
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    estimateProgressBar.visibility = View.GONE
                    btnSaveToJournal.isEnabled = true
                    Toast.makeText(this@MainActivity, "Erreur réseau lors de l'enregistrement : ${e.localizedMessage}", Toast.LENGTH_LONG).show()
                }
            }
        }
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
