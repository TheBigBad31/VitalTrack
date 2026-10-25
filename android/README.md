# Passerelle Android Gratuite Health Connect -> VitalTrack (APK & MacroDroid / Tasker)

Ce module fournit la passerelle 100 % gratuite permettant à tout smartphone **Xiaomi / Android (HyperOS & MIUI)** de lire les données locales consolidées dans **Google Health Connect** (alimentées en continu par la bague **RingConn Gen 3**, le podomètre Xiaomi et la balance Withings) et de les pousser vers le webhook sécurisé de **VitalTrack** sans aucun abonnement tiers payant.

---

## Option 1 : Application Android Légère (Kotlin / WorkManager)

Le code source complet de l'application est disponible dans le dossier `android/health-bridge-app/` :
- **Architecture** : Kotlin, AndroidX Health Connect Client 1.1, WorkManager périodique (15 min).
- **Consommation** : Zéro réveil processeur inutile, respect des contraintes Doze mode.
- **Sécurité** : Authentification par header `X-Webhook-Token` avec le jeton d'appareil individuel (stocké de manière chiffrée côté backend).

### Compilation directe :
```bash
cd android/health-bridge-app
./gradlew assembleRelease
```
L'APK installable se trouve dans `app/build/outputs/apk/release/app-release.apk`.

---

## Option 2 : Profil Clé en Main MacroDroid / Tasker (Zéro compilation)

Si vous préférez ne pas compiler d'APK, vous pouvez utiliser l'application gratuite **MacroDroid** (ou **Tasker**) avec le profil JSON d'automatisation fourni dans `android/macrodroid_health_connect_profile.json` :

1. **Déclencheur (Trigger)** :
   - Périodique (toutes les 15 ou 30 minutes) + Événement au réveil / débranchement du chargeur.
2. **Action** :
   - Requête HTTP POST vers votre instance VitalTrack :
     - URL : `https://<votre-domaine-vitaltrack>/api/webhook/health`
     - Headers :
       - `Content-Type: application/json`
       - `X-Webhook-Token: <votre_jeton_d_appareil>`
     - Corps JSON (Payload) :
       ```json
       {
         "source": "health_connect",
         "date": "{year}-{month_digit_2}-{day_digit_2}",
         "steps": {system_step_counter},
         "resting_hr_bpm": {ringconn_last_hr},
         "hrv_ms": {ringconn_last_hrv},
         "sleep_score": {ringconn_sleep_score}
       }
       ```

---

## Configuration Requise sur Xiaomi HyperOS & MIUI

Les smartphones Xiaomi appliquent par défaut des restrictions de batterie agressives pouvant tuer les processus d'arrière-plan. Appliquez ces 3 étapes simples :

### 1. Démarrage Automatique (Autostart)
1. Ouvrez l'application **Sécurité** (ou **Paramètres > Applications > Gérer les applications**).
2. Sélectionnez **VitalTrack Bridge** (ou **MacroDroid**).
3. Activez l'option **Démarrage automatique** (Autostart) et autorisez le démarrage en arrière-plan.

### 2. Économiseur de Batterie MIUI / HyperOS
1. Dans la même fiche d'application, faites défiler jusqu'à **Économiseur de batterie**.
2. Choisissez **Pas de restrictions** (No restrictions).
   *(Empêche le système de fermer le worker de synchronisation lors de la veille prolongée).*

### 3. Autorisations Health Connect
1. Allez dans **Paramètres > Sécurité et confidentialité > Confidentialité > Health Connect**.
2. Cliquez sur **Applications autorisées**.
3. Sélectionnez **VitalTrack Bridge** (ou votre agrégateur) et activez toutes les autorisations de lecture :
   - *Pas*, *Calories brûlées*, *Sommeil*, *Fréquence cardiaque*, *Variabilité FC (HRV)*, *Poids*, *Séances d'exercice*.
