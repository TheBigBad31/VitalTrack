package ai.vitaltrack.bridge

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

object SecurePrefs {
    private const val ENCRYPTED_PREFS_NAME = "vitaltrack_secure_prefs"
    private const val LEGACY_PREFS_NAME = "vitaltrack_bridge_prefs"
    private const val KEY_DEVICE_TOKEN = "device_token"

    private fun getEncryptedPrefs(context: Context): SharedPreferences {
        val masterKey = MasterKey.Builder(context)
            .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
            .build()
        return EncryptedSharedPreferences.create(
            context,
            ENCRYPTED_PREFS_NAME,
            masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM
        )
    }

    fun getDeviceToken(context: Context): String? {
        val securePrefs = getEncryptedPrefs(context)
        val existing = securePrefs.getString(KEY_DEVICE_TOKEN, null)
        if (!existing.isNullOrBlank()) {
            return existing
        }
        // Migration automatique depuis l'ancien SharedPreferences non chiffré
        val legacyPrefs = context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
        val legacyToken = legacyPrefs.getString(KEY_DEVICE_TOKEN, null)
        if (!legacyToken.isNullOrBlank()) {
            securePrefs.edit().putString(KEY_DEVICE_TOKEN, legacyToken).apply()
            legacyPrefs.edit().remove(KEY_DEVICE_TOKEN).apply()
            return legacyToken
        }
        return null
    }

    fun setDeviceToken(context: Context, token: String) {
        getEncryptedPrefs(context).edit().putString(KEY_DEVICE_TOKEN, token).apply()
        context.getSharedPreferences(LEGACY_PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .remove(KEY_DEVICE_TOKEN)
            .apply()
    }
}
