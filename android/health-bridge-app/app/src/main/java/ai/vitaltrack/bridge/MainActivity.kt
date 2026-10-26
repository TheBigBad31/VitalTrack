package ai.vitaltrack.bridge

import android.animation.ObjectAnimator
import android.animation.ValueAnimator
import android.content.ClipboardManager
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.text.InputType
import android.text.method.HideReturnsTransformationMethod
import android.text.method.PasswordTransformationMethod
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.*
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.*
import androidx.lifecycle.lifecycleScope
import androidx.work.*
import com.google.android.material.button.MaterialButton
import com.google.android.material.card.MaterialCardView
import com.google.android.material.switchmaterial.SwitchMaterial
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
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

    private val stepPermissions = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class)
    )
    private val hrPermissions = setOf(
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(HeartRateVariabilityRmssdRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getReadPermission(OxygenSaturationRecord::class)
    )
    private val sleepPermissions = setOf(
        HealthPermission.getReadPermission(SleepSessionRecord::class)
    )
    private val weightPermissions = setOf(
        HealthPermission.getReadPermission(WeightRecord::class),
        HealthPermission.getReadPermission(BodyFatRecord::class),
        HealthPermission.getReadPermission(LeanBodyMassRecord::class),
        HealthPermission.getReadPermission(BoneMassRecord::class)
    )

    // UI state views
    private lateinit var statusBadgeDot: View
    private lateinit var statusBadgeText: TextView
    private lateinit var statusCard: MaterialCardView
    private lateinit var statusSubtext: TextView

    private lateinit var chipSteps: TextView
    private lateinit var chipHr: TextView
    private lateinit var chipSleep: TextView
    private lateinit var chipWeight: TextView

    private lateinit var tokenInput: EditText
    private lateinit var togglePasswordBtn: ImageView
    private var isTokenVisible = false

    private lateinit var lastSyncTimeText: TextView
    private lateinit var lastSyncCountText: TextView
    private lateinit var syncNowBtn: MaterialButton
    private lateinit var autoSyncSwitch: SwitchMaterial

    private lateinit var photoPreview: ImageView
    private lateinit var photoPlaceholderLayout: LinearLayout
    private lateinit var photoProgressLayout: LinearLayout

    private var pulseAnimator: ObjectAnimator? = null

    private val requestPermissionActivityContract =
        PermissionController.createRequestPermissionResultContract()

    private val requestPermissions =
        registerForActivityResult(requestPermissionActivityContract) { granted ->
            updatePermissionChips(granted)
            updateConnectionStatus(granted)
            if (granted.containsAll(permissions)) {
                Toast.makeText(this, "Toutes les autorisations Health Connect accordées", Toast.LENGTH_SHORT).show()
            } else {
                Toast.makeText(this, "Autorisations partielles accordées (${granted.size}/${permissions.size})", Toast.LENGTH_LONG).show()
            }
        }

    private val pickPhotoLauncher =
        registerForActivityResult(ActivityResultContracts.GetContent()) { uri: Uri? ->
            uri?.let { handleSelectedPhoto(it) }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(buildModernUi())
        checkCurrentPermissions()
        refreshSyncHistory()
    }

    override fun onResume() {
        super.onResume()
        checkCurrentPermissions()
        refreshSyncHistory()
    }

    override fun onDestroy() {
        pulseAnimator?.cancel()
        super.onDestroy()
    }

    private fun dp(value: Int): Int {
        return (value * resources.displayMetrics.density).toInt()
    }

    private fun buildModernUi(): View {
        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        val defaultUrl = "https://vital-track-one.vercel.app/api/webhooks/health-connect"
        val savedUrl = prefs.getString("webhook_url", null) ?: defaultUrl
        val savedToken = prefs.getString("device_token", null) ?: ""
        val isAutoSyncActive = prefs.getBoolean("auto_sync_enabled", true)

        val rootScrollView = ScrollView(this).apply {
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.parseColor("#0B0B1A"))
            isFillViewport = true
        }

        val container = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
            setPadding(dp(18), dp(24), dp(18), dp(40))
        }

        // --- 1. HEADER BRANDING ---
        val headerLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(20) }
        }

        val logoIcon = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(44), dp(44)).apply { rightMargin = dp(14) }
            setImageResource(R.drawable.ic_radar)
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_badge_cyan)
            setPadding(dp(8), dp(8), dp(8), dp(8))
        }
        headerLayout.addView(logoIcon)

        val titleContainer = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }

        val appTitle = TextView(this).apply {
            text = "VitalTrack"
            textSize = 22f
            setTypeface(Typeface.create("sans-serif-black", Typeface.BOLD))
            setTextColor(Color.parseColor("#F8FAFC"))
        }
        val appSubtitle = TextView(this).apply {
            text = "Passerelle Health Connect & Biométrie"
            textSize = 12f
            setTextColor(Color.parseColor("#22D3EE"))
            setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
        }
        titleContainer.addView(appTitle)
        titleContainer.addView(appSubtitle)
        headerLayout.addView(titleContainer)

        container.addView(headerLayout)

        // --- 2. STATUT DE CONNEXION AVEC BADGE PULSÉ ---
        statusCard = createGlassCard().apply {
            (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(16)
        }
        val statusInnerLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val statusRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }

        val statusTitle = TextView(this).apply {
            text = "ÉTAT DE LA PASSERELLE"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            letterSpacing = 0.08f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        statusRow.addView(statusTitle)

        // Badge pill
        val badgeLayout = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(10), dp(4), dp(12), dp(4))
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_badge_warning)
        }

        statusBadgeDot = View(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(8), dp(8)).apply { rightMargin = dp(6) }
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.ic_status_dot_warning)
        }
        badgeLayout.addView(statusBadgeDot)

        statusBadgeText = TextView(this).apply {
            text = "En attente"
            textSize = 12f
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            setTextColor(Color.parseColor("#F59E0B"))
        }
        badgeLayout.addView(statusBadgeText)
        statusRow.addView(badgeLayout)
        statusInnerLayout.addView(statusRow)

        statusSubtext = TextView(this).apply {
            text = "Vérification des autorisations et paramètres du serveur..."
            textSize = 13f
            setTextColor(Color.parseColor("#E2E8F0"))
            setPadding(0, dp(10), 0, 0)
        }
        statusInnerLayout.addView(statusSubtext)
        statusCard.addView(statusInnerLayout)
        container.addView(statusCard)

        // Démarrer l'animation de pulsation du badge
        pulseAnimator = ObjectAnimator.ofFloat(statusBadgeDot, "alpha", 1f, 0.35f).apply {
            duration = 900
            repeatMode = ValueAnimator.REVERSE
            repeatCount = ValueAnimator.INFINITE
            start()
        }

        // --- 3. CARTE CONFIGURATION SERVEUR & TOKEN ---
        val configCard = createGlassCard().apply {
            (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(16)
        }
        val configInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val configSectionTitle = TextView(this).apply {
            text = "SERVEUR VITALTRACK & AUTHENTIFICATION"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            letterSpacing = 0.08f
            setPadding(0, 0, 0, dp(12))
        }
        configInner.addView(configSectionTitle)

        // Champ URL
        val urlLabel = TextView(this).apply {
            text = "URL du Webhook API"
            textSize = 12f
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, 0, 0, dp(4))
        }
        configInner.addView(urlLabel)

        val urlInput = EditText(this).apply {
            setText(savedUrl)
            textSize = 13f
            setTextColor(Color.parseColor("#F8FAFC"))
            setHintTextColor(Color.parseColor("#475569"))
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_input_field)
            setPadding(dp(12), dp(12), dp(12), dp(12))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(14) }
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        }
        configInner.addView(urlInput)

        // Champ Token avec œil et coller
        val tokenLabel = TextView(this).apply {
            text = "Jeton d'appareil individuel (X-Webhook-Token)"
            textSize = 12f
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, 0, 0, dp(4))
        }
        configInner.addView(tokenLabel)

        val tokenRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_input_field)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        tokenInput = EditText(this).apply {
            setText(savedToken)
            textSize = 13f
            setTextColor(Color.parseColor("#F8FAFC"))
            hint = "ex: vtk_dev_xxxxxxxx"
            setHintTextColor(Color.parseColor("#475569"))
            background = null
            setPadding(dp(12), dp(12), dp(8), dp(12))
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            transformationMethod = PasswordTransformationMethod.getInstance()
        }
        tokenRow.addView(tokenInput)

        // Bouton Visibilité œil
        togglePasswordBtn = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(40), dp(40))
            setImageResource(R.drawable.ic_visibility_off)
            setPadding(dp(8), dp(8), dp(8), dp(8))
            isClickable = true
            isFocusable = true
            setOnClickListener {
                isTokenVisible = !isTokenVisible
                if (isTokenVisible) {
                    tokenInput.transformationMethod = HideReturnsTransformationMethod.getInstance()
                    setImageResource(R.drawable.ic_visibility)
                } else {
                    tokenInput.transformationMethod = PasswordTransformationMethod.getInstance()
                    setImageResource(R.drawable.ic_visibility_off)
                }
                tokenInput.setSelection(tokenInput.text.length)
            }
        }
        tokenRow.addView(togglePasswordBtn)

        // Bouton Coller
        val pasteBtn = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(40), dp(40))
            setImageResource(R.drawable.ic_content_paste)
            setPadding(dp(8), dp(8), dp(8), dp(8))
            isClickable = true
            isFocusable = true
            setOnClickListener {
                val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                val clip = clipboard.primaryClip
                if (clip != null && clip.itemCount > 0) {
                    val pasted = clip.getItemAt(0).text?.toString()?.trim() ?: ""
                    if (pasted.isNotEmpty()) {
                        tokenInput.setText(pasted)
                        Toast.makeText(this@MainActivity, "Jeton collé depuis le presse-papiers", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
        tokenRow.addView(pasteBtn)
        configInner.addView(tokenRow)

        configCard.addView(configInner)
        container.addView(configCard)

        // --- 4. CARTE PERMISSIONS HEALTH CONNECT ---
        val permsCard = createGlassCard().apply {
            (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(16)
        }
        val permsInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val permsHeaderRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(12))
        }

        val permsTitle = TextView(this).apply {
            text = "AUTORISATIONS HEALTH CONNECT"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            letterSpacing = 0.08f
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        permsHeaderRow.addView(permsTitle)

        val btnRequestPerms = TextView(this).apply {
            text = "Gérer ›"
            textSize = 13f
            setTextColor(Color.parseColor("#22D3EE"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            setPadding(dp(8), dp(4), dp(4), dp(4))
            isClickable = true
            isFocusable = true
            setOnClickListener {
                requestPermissions.launch(permissions)
            }
        }
        permsHeaderRow.addView(btnRequestPerms)
        permsInner.addView(permsHeaderRow)

        // Grille de statuts des 4 catégories
        val chipsRow1 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(8) }
        }

        chipSteps = createStatusChip("Pas & Calories", false)
        (chipSteps.layoutParams as LinearLayout.LayoutParams).weight = 1f
        (chipSteps.layoutParams as LinearLayout.LayoutParams).rightMargin = dp(6)
        chipsRow1.addView(chipSteps)

        chipHr = createStatusChip("Rythme / SpO2 / HRV", false)
        (chipHr.layoutParams as LinearLayout.LayoutParams).weight = 1f
        (chipHr.layoutParams as LinearLayout.LayoutParams).leftMargin = dp(6)
        chipsRow1.addView(chipHr)
        permsInner.addView(chipsRow1)

        val chipsRow2 = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }

        chipSleep = createStatusChip("Sommeil complet", false)
        (chipSleep.layoutParams as LinearLayout.LayoutParams).weight = 1f
        (chipSleep.layoutParams as LinearLayout.LayoutParams).rightMargin = dp(6)
        chipsRow2.addView(chipSleep)

        chipWeight = createStatusChip("Poids & Masse Grasse", false)
        (chipWeight.layoutParams as LinearLayout.LayoutParams).weight = 1f
        (chipWeight.layoutParams as LinearLayout.LayoutParams).leftMargin = dp(6)
        chipsRow2.addView(chipWeight)
        permsInner.addView(chipsRow2)

        permsCard.addView(permsInner)
        container.addView(permsCard)

        // --- 5. SYNCHRONISATION & ACTIONS ---
        val syncCard = createGlassCard().apply {
            (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(16)
        }
        val syncInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val syncTitle = TextView(this).apply {
            text = "SYNCHRONISATION & RYTHME"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            letterSpacing = 0.08f
            setPadding(0, 0, 0, dp(12))
        }
        syncInner.addView(syncTitle)

        // Toggle Auto-sync
        val switchRow = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, dp(14))
        }

        val switchTexts = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val switchTitle = TextView(this).apply {
            text = "Synchro automatique en arrière-plan"
            textSize = 14f
            setTextColor(Color.parseColor("#F8FAFC"))
            setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
        }
        val switchSub = TextView(this).apply {
            text = "Période de 15 minutes en tâche de fond (WorkManager)"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
        }
        switchTexts.addView(switchTitle)
        switchTexts.addView(switchSub)
        switchRow.addView(switchTexts)

        autoSyncSwitch = SwitchMaterial(this).apply {
            isChecked = isAutoSyncActive
            setOnCheckedChangeListener { _, isChecked ->
                prefs.edit().putBoolean("auto_sync_enabled", isChecked).apply()
                if (isChecked) {
                    val url = urlInput.text.toString().trim()
                    val tok = tokenInput.text.toString().trim()
                    saveConfig(url, tok)
                    scheduleSyncWorker()
                    Toast.makeText(this@MainActivity, "Synchronisation automatique activée", Toast.LENGTH_SHORT).show()
                } else {
                    WorkManager.getInstance(applicationContext).cancelUniqueWork("VitalTrackHealthSync")
                    Toast.makeText(this@MainActivity, "Synchronisation automatique désactivée", Toast.LENGTH_SHORT).show()
                }
            }
        }
        switchRow.addView(autoSyncSwitch)
        syncInner.addView(switchRow)

        // Historique & Dernières stats
        val statsContainer = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_glass_card_elevated)
            setPadding(dp(12), dp(10), dp(12), dp(10))
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = dp(16) }
        }

        val leftStat = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
        }
        val leftStatLabel = TextView(this).apply {
            text = "Dernière synchro réussie"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
        }
        lastSyncTimeText = TextView(this).apply {
            text = "Aucune synchro récente"
            textSize = 13f
            setTextColor(Color.parseColor("#22D3EE"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
        }
        leftStat.addView(leftStatLabel)
        leftStat.addView(lastSyncTimeText)
        statsContainer.addView(leftStat)

        val rightStat = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.END
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
        }
        val rightStatLabel = TextView(this).apply {
            text = "Métriques envoyées"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
        }
        lastSyncCountText = TextView(this).apply {
            text = "--"
            textSize = 13f
            setTextColor(Color.parseColor("#34D399"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
        }
        rightStat.addView(rightStatLabel)
        rightStat.addView(lastSyncCountText)
        statsContainer.addView(rightStat)
        syncInner.addView(statsContainer)

        // Bouton Synchroniser maintenant avec dégradé électrique
        syncNowBtn = MaterialButton(this).apply {
            text = "Synchroniser maintenant"
            textSize = 14f
            setTextColor(Color.WHITE)
            setTypeface(Typeface.create("sans-serif-black", Typeface.BOLD))
            icon = ContextCompat.getDrawable(this@MainActivity, R.drawable.ic_sync)
            iconGravity = MaterialButton.ICON_GRAVITY_TEXT_START
            iconPadding = dp(8)
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_btn_electric)
            cornerRadius = dp(12)
            elevation = dp(4).toFloat()
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(52)
            )
            setOnClickListener {
                val url = urlInput.text.toString().trim()
                val tok = tokenInput.text.toString().trim()
                if (url.isEmpty() || tok.isEmpty()) {
                    Toast.makeText(this@MainActivity, "Veuillez renseigner l'URL et le Jeton", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }
                saveConfig(url, tok)
                triggerImmediateSync()
            }
        }
        syncInner.addView(syncNowBtn)

        syncCard.addView(syncInner)
        container.addView(syncCard)

        // --- 6. SECTION PHOTO & ESTIMATION CALORIES (PRÉPARATION UI) ---
        val photoCard = createGlassCard().apply {
            (layoutParams as LinearLayout.LayoutParams).bottomMargin = dp(16)
        }
        val photoInner = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(16), dp(16), dp(16), dp(16))
        }

        val photoSectionTitle = TextView(this).apply {
            text = "PHOTO DE PLAT & VISION NUTRITION"
            textSize = 11f
            setTextColor(Color.parseColor("#94A3B8"))
            setTypeface(Typeface.create("sans-serif-bold", Typeface.BOLD))
            letterSpacing = 0.08f
            setPadding(0, 0, 0, dp(4))
        }
        photoInner.addView(photoSectionTitle)

        val photoSectionSub = TextView(this).apply {
            text = "Prenez une photo de votre assiette pour une estimation par IA Gemini Vision"
            textSize = 12f
            setTextColor(Color.parseColor("#94A3B8"))
            setPadding(0, 0, 0, dp(12))
        }
        photoInner.addView(photoSectionSub)

        // Zone de prévisualisation
        val previewContainer = FrameLayout(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(180)
            ).apply { bottomMargin = dp(12) }
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_glass_card_elevated)
        }

        photoPreview = ImageView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            scaleType = ImageView.ScaleType.CENTER_CROP
            visibility = View.GONE
        }
        previewContainer.addView(photoPreview)

        photoPlaceholderLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }
        val placeholderIcon = ImageView(this).apply {
            layoutParams = LinearLayout.LayoutParams(dp(48), dp(48)).apply { bottomMargin = dp(8) }
            setImageResource(R.drawable.ic_camera)
        }
        val placeholderText = TextView(this).apply {
            text = "Aucune photo sélectionnée"
            textSize = 13f
            setTextColor(Color.parseColor("#64748B"))
        }
        photoPlaceholderLayout.addView(placeholderIcon)
        photoPlaceholderLayout.addView(placeholderText)
        previewContainer.addView(photoPlaceholderLayout)

        // Overlay progression de capture / analyse
        photoProgressLayout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            setBackgroundColor(Color.parseColor("#B30B0B1A"))
            visibility = View.GONE
        }
        val progressBar = ProgressBar(this).apply {
            isIndeterminate = true
            indeterminateTintList = ColorStateList.valueOf(Color.parseColor("#22D3EE"))
        }
        val progressText = TextView(this).apply {
            text = "Traitement visuel de l'assiette en cours..."
            textSize = 12f
            setTextColor(Color.parseColor("#22D3EE"))
            setPadding(0, dp(8), 0, 0)
        }
        photoProgressLayout.addView(progressBar)
        photoProgressLayout.addView(progressText)
        previewContainer.addView(photoProgressLayout)

        photoInner.addView(previewContainer)

        // Bouton capturer / choisir photo
        val btnCapturePhoto = MaterialButton(this).apply {
            text = "Prendre / Choisir une photo"
            textSize = 13f
            setTextColor(Color.parseColor("#F8FAFC"))
            icon = ContextCompat.getDrawable(this@MainActivity, R.drawable.ic_camera)
            iconGravity = MaterialButton.ICON_GRAVITY_TEXT_START
            iconPadding = dp(8)
            background = ContextCompat.getDrawable(this@MainActivity, R.drawable.bg_btn_secondary)
            cornerRadius = dp(12)
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                dp(48)
            )
            setOnClickListener {
                pickPhotoLauncher.launch("image/*")
            }
        }
        photoInner.addView(btnCapturePhoto)

        photoCard.addView(photoInner)
        container.addView(photoCard)

        rootScrollView.addView(container)
        return rootScrollView
    }

    private fun createGlassCard(): MaterialCardView {
        return MaterialCardView(this).apply {
            layoutParams = LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
            )
            radius = dp(16).toFloat()
            cardElevation = dp(4).toFloat()
            setCardBackgroundColor(Color.parseColor("#14142B"))
            strokeWidth = dp(1)
            strokeColor = Color.parseColor("#25254A")
        }
    }

    private fun createStatusChip(label: String, granted: Boolean): TextView {
        return TextView(this).apply {
            text = if (granted) "✓ $label" else "○ $label"
            textSize = 11f
            setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL))
            setTextColor(if (granted) Color.parseColor("#34D399") else Color.parseColor("#94A3B8"))
            background = ContextCompat.getDrawable(
                this@MainActivity,
                if (granted) R.drawable.bg_badge_success else R.drawable.bg_stat_chip
            )
            setPadding(dp(10), dp(8), dp(10), dp(8))
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT)
        }
    }

    private fun updatePermissionChips(grantedSet: Set<String>) {
        val hasSteps = stepPermissions.any { grantedSet.contains(it) }
        val hasHr = hrPermissions.any { grantedSet.contains(it) }
        val hasSleep = sleepPermissions.any { grantedSet.contains(it) }
        val hasWeight = weightPermissions.any { grantedSet.contains(it) }

        updateChip(chipSteps, "Pas & Calories", hasSteps)
        updateChip(chipHr, "Rythme / SpO2 / HRV", hasHr)
        updateChip(chipSleep, "Sommeil", hasSleep)
        updateChip(chipWeight, "Poids & Masse", hasWeight)
    }

    private fun updateChip(chip: TextView, label: String, granted: Boolean) {
        chip.text = if (granted) "✓ $label" else "○ $label"
        chip.setTextColor(if (granted) Color.parseColor("#34D399") else Color.parseColor("#94A3B8"))
        chip.background = ContextCompat.getDrawable(
            this,
            if (granted) R.drawable.bg_badge_success else R.drawable.bg_stat_chip
        )
    }

    private fun checkCurrentPermissions() {
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val client = HealthConnectClient.getOrCreate(applicationContext)
                val granted = client.permissionController.getGrantedPermissions()
                withContext(Dispatchers.Main) {
                    updatePermissionChips(granted)
                    updateConnectionStatus(granted)
                }
            } catch (e: Exception) {
                withContext(Dispatchers.Main) {
                    updateConnectionStatus(emptySet())
                }
            }
        }
    }

    private fun updateConnectionStatus(granted: Set<String> = emptySet()) {
        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        val token = prefs.getString("device_token", "") ?: ""

        val hasAllPerms = granted.containsAll(permissions)
        val hasSomePerms = granted.isNotEmpty()
        val hasToken = token.isNotBlank()

        if (hasToken && hasAllPerms) {
            statusBadgeText.text = "Connecté"
            statusBadgeText.setTextColor(Color.parseColor("#34D399"))
            statusBadgeDot.background = ContextCompat.getDrawable(this, R.drawable.ic_status_dot_success)
            (statusBadgeDot.parent as? ViewGroup)?.background = ContextCompat.getDrawable(this, R.drawable.bg_badge_success)
            statusSubtext.text = "Passerelle opérationnelle. Données synchronisées vers VitalTrack."
        } else if (!hasToken) {
            statusBadgeText.text = "Jeton manquant"
            statusBadgeText.setTextColor(Color.parseColor("#F43F5E"))
            statusBadgeDot.background = ContextCompat.getDrawable(this, R.drawable.ic_status_dot_error)
            (statusBadgeDot.parent as? ViewGroup)?.background = ContextCompat.getDrawable(this, R.drawable.bg_badge_warning)
            statusSubtext.text = "Renseignez le jeton d'appareil (X-Webhook-Token) pour vous connecter."
        } else if (!hasSomePerms) {
            statusBadgeText.text = "Permissions requises"
            statusBadgeText.setTextColor(Color.parseColor("#F59E0B"))
            statusBadgeDot.background = ContextCompat.getDrawable(this, R.drawable.ic_status_dot_warning)
            (statusBadgeDot.parent as? ViewGroup)?.background = ContextCompat.getDrawable(this, R.drawable.bg_badge_warning)
            statusSubtext.text = "Accordez les permissions Health Connect pour synchroniser les métriques."
        } else {
            statusBadgeText.text = "Partiel (${granted.size}/${permissions.size})"
            statusBadgeText.setTextColor(Color.parseColor("#22D3EE"))
            statusBadgeDot.background = ContextCompat.getDrawable(this, R.drawable.ic_status_dot_success)
            (statusBadgeDot.parent as? ViewGroup)?.background = ContextCompat.getDrawable(this, R.drawable.bg_badge_cyan)
            statusSubtext.text = "Synchronisation active sur les métriques autorisées."
        }
    }

    private fun saveConfig(url: String, token: String) {
        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        prefs.edit()
            .putString("webhook_url", url)
            .putString("device_token", token)
            .apply()
    }

    private fun refreshSyncHistory() {
        val prefs = getSharedPreferences("vitaltrack_bridge_prefs", Context.MODE_PRIVATE)
        val lastSyncIso = prefs.getString("last_sync_timestamp", null)
        val metricsCount = prefs.getInt("last_sync_metrics_count", -1)

        if (!lastSyncIso.isNullOrBlank()) {
            try {
                val instant = Instant.parse(lastSyncIso)
                val formatter = DateTimeFormatter.ofPattern("dd/MM à HH:mm")
                    .withZone(ZoneId.systemDefault())
                lastSyncTimeText.text = formatter.format(instant)
            } catch (e: Exception) {
                lastSyncTimeText.text = lastSyncIso
            }
        } else {
            lastSyncTimeText.text = "Aucune synchro récente"
        }

        if (metricsCount >= 0) {
            lastSyncCountText.text = "$metricsCount métriques"
        } else {
            lastSyncCountText.text = "--"
        }
    }

    private fun triggerImmediateSync() {
        syncNowBtn.isEnabled = false
        syncNowBtn.text = "Synchronisation..."

        val inputData = Data.Builder()
            .putBoolean("is_catchup", true)
            .build()

        val oneTimeWork = OneTimeWorkRequestBuilder<HealthSyncWorker>()
            .setInputData(inputData)
            .setExpedited(OutOfQuotaPolicy.RUN_AS_NON_EXPEDITED_WORK_REQUEST)
            .build()

        val workManager = WorkManager.getInstance(applicationContext)
        workManager.enqueue(oneTimeWork)

        workManager.getWorkInfoByIdLiveData(oneTimeWork.id).observe(this) { workInfo ->
            if (workInfo != null) {
                when (workInfo.state) {
                    WorkInfo.State.SUCCEEDED -> {
                        syncNowBtn.isEnabled = true
                        syncNowBtn.text = "Synchroniser maintenant"
                        refreshSyncHistory()
                        updateConnectionStatus()
                        Toast.makeText(this, "Synchronisation réussie !", Toast.LENGTH_SHORT).show()
                    }
                    WorkInfo.State.FAILED -> {
                        syncNowBtn.isEnabled = true
                        syncNowBtn.text = "Synchroniser maintenant"
                        Toast.makeText(this, "Erreur lors de la synchronisation", Toast.LENGTH_LONG).show()
                    }
                    WorkInfo.State.CANCELLED -> {
                        syncNowBtn.isEnabled = true
                        syncNowBtn.text = "Synchroniser maintenant"
                    }
                    else -> {}
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

    private fun handleSelectedPhoto(uri: Uri) {
        photoPreview.setImageURI(uri)
        photoPreview.visibility = View.VISIBLE
        photoPlaceholderLayout.visibility = View.GONE
        photoProgressLayout.visibility = View.VISIBLE

        // Simulation visuelle de progression et notification ergonomique
        lifecycleScope.launch {
            kotlinx.coroutines.delay(1200)
            photoProgressLayout.visibility = View.GONE
            Toast.makeText(
                this@MainActivity,
                "Photo prête pour l'analyse nutritionnelle VitalTrack !",
                Toast.LENGTH_SHORT
            ).show()
        }
    }
}
