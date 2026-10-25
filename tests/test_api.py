"""Tests automatisés pour l'API REST FastAPI de VitalTrack (src/app.py).

Couvre :
- /api/health : statut du serveur et configuration
- /api/dashboard : données consolidées sur les 5 vues
- /api/weights (GET \u0026 POST) : enregistrement et récupération des pesées avec recalcul de tendance 7j
- /api/activities (GET \u0026 POST) : pas, calories actives et métriques biométriques
- /api/meals (GET \u0026 POST) : journal des repas et persistance des aliments
- /api/meals/estimate (POST) : estimation calorique avec curseur de portion interactif (0.5x - 2.0x)
- /api/devices (GET \u0026 POST) : connecteurs IoT et synchronisation
"""

from datetime import date, timedelta
import pytest
from fastapi.testclient import TestClient

from src.app import app


import tempfile
import os
from src.db import Database
import src.app as app_module

@pytest.fixture
def client():
    """Client de test FastAPI avec base temporaire isolée."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutrition_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db

    yield TestClient(app)

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutrition_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_api_health(client):
    """Vérifie le point de terminaison de santé."""
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "VitalTrack API" in data["service"]
    assert "db_path" in data


def test_api_dashboard_structure(client):
    """Vérifie la présence des 5 vues et métriques clés dans /api/dashboard."""
    res = client.get("/api/dashboard")
    assert res.status_code == 200
    data = res.json()

    # Synthèse générale
    assert "summary" in data
    summary = data["summary"]
    assert "current_weight_kg" in summary
    assert "weight_trend_7d_kg" in summary
    assert "calories_intake_kcal" in summary
    assert "calories_burned_kcal" in summary
    assert "net_energy_balance_kcal" in summary
    assert "steps" in summary
    assert "macros" in summary

    # Historiques pour les graphiques
    assert "weights_history" in data
    assert isinstance(data["weights_history"], list)
    assert "activities_history" in data
    assert isinstance(data["activities_history"], list)
    assert "recent_meals" in data
    assert "meals_by_day_7d" in data
    assert "devices" in data
    assert len(data["devices"]) >= 2


def test_api_weight_crud(client):
    """Teste l'insertion et la lecture d'une pesée via l'API."""
    today_str = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "date": today_str,
        "weight_kg": 78.5,
        "body_fat_pct": 19.8,
        "muscle_mass_kg": 38.5,
        "water_pct": 57.0,
        "source": "manual",
        "notes": "Pesée de test API"
    }
    
    # 1. Insertion
    post_res = client.post("/api/weights", json=payload)
    assert post_res.status_code == 200
    created = post_res.json()
    assert created["weight_kg"] == 78.5
    assert created["trend_7d_kg"] is not None
    assert created["bmi"] is not None
    weight_id = created["id"]

    # 2. Récupération
    get_res = client.get("/api/weights?limit=5")
    assert get_res.status_code == 200
    weights = get_res.json()
    assert any(w["weight_kg"] == 78.5 for w in weights)

    # 3. Modification (PUT)
    update_payload = {
        "date": today_str,
        "weight_kg": 78.2,
        "body_fat_pct": 19.5,
        "notes": "Pesée corrigée"
    }
    put_res = client.put(f"/api/weights/{weight_id}", json=update_payload)
    assert put_res.status_code == 200
    updated = put_res.json()
    assert updated["weight_kg"] == 78.2
    assert updated["body_fat_pct"] == 19.5
    assert updated["notes"] == "Pesée corrigée"

    # 4. Suppression (DELETE)
    del_res = client.delete(f"/api/weights/{weight_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # Vérification disparition
    get_res2 = client.get("/api/weights?limit=50")
    assert not any(w["id"] == weight_id for w in get_res2.json())


def test_api_activity_crud(client):
    """Teste l'insertion et la lecture d'une activité via l'API."""
    today_str = (date.today() + timedelta(days=1)).isoformat()
    payload = {
        "date": today_str,
        "steps": 12500,
        "active_calories_kcal": 550.0,
        "workout_minutes": 50,
        "workout_type": "Course à pied",
        "resting_hr_bpm": 56,
        "hrv_ms": 62.0,
        "sleep_score": 88,
        "source": "health_connect"
    }

    # 1. Insertion
    post_res = client.post("/api/activities", json=payload)
    assert post_res.status_code == 200
    created = post_res.json()
    assert created["steps"] == 12500
    assert created["total_burned_kcal"] > 1700

    # 2. Récupération
    get_res = client.get("/api/activities?limit=5")
    assert get_res.status_code == 200
    acts = get_res.json()
    assert any(a["steps"] == 12500 for a in acts)


def test_api_meal_estimation_and_portion_scaling(client):
    """Teste l'estimation calorique avec multiplicateur de portion (0.5x, 1.0x, 2.0x)."""
    # 1. Portion normale 1.0x
    payload_1x = {
        "description": "Blanc de poulet 150g, riz basmati 180g, brocoli 150g",
        "portion_scale": 1.0,
        "meal_type": "lunch"
    }
    res_1x = client.post("/api/meals/estimate", json=payload_1x)
    assert res_1x.status_code == 200
    data_1x = res_1x.json()
    cals_1x = data_1x["total_calories_kcal"]
    assert cals_1x > 400

    # 2. Portion double 2.0x
    payload_2x = {
        "description": "Blanc de poulet 150g, riz basmati 180g, brocoli 150g",
        "portion_scale": 2.0,
        "meal_type": "lunch"
    }
    res_2x = client.post("/api/meals/estimate", json=payload_2x)
    assert res_2x.status_code == 200
    data_2x = res_2x.json()
    cals_2x = data_2x["total_calories_kcal"]
    assert pytest.approx(cals_2x, rel=0.1) == cals_1x * 2.0


def test_api_meal_save_to_journal(client):
    """Teste l'enregistrement d'un repas dans le journal alimentaire, modification et suppression."""
    payload = {
        "date": date.today().isoformat(),
        "meal_type": "dinner",
        "portion_scale": 1.0,
        "items": [
            {
                "name": "Pavé de saumon",
                "portion_g": 140.0,
                "calories_kcal": 290.0,
                "protein_g": 28.0,
                "carbs_g": 0.0,
                "fat_g": 18.0,
                "fiber_g": 0.0
            },
            {
                "name": "Haricots verts",
                "portion_g": 200.0,
                "calories_kcal": 62.0,
                "protein_g": 3.6,
                "carbs_g": 14.0,
                "fat_g": 0.4,
                "fiber_g": 5.4
            }
        ]
    }
    res = client.post("/api/meals", json=payload)
    assert res.status_code == 200
    saved = res.json()
    assert saved["meal_type"] == "dinner"
    assert pytest.approx(saved["total_calories_kcal"], abs=1.0) == 352.0
    assert len(saved["items"]) == 2
    meal_id = saved["id"]

    # Modification (PUT)
    put_payload = {
        "date": date.today().isoformat(),
        "meal_type": "dinner",
        "portion_scale": 1.0,
        "items": [
            {
                "name": "Pavé de saumon grand format",
                "portion_g": 200.0,
                "calories_kcal": 410.0,
                "protein_g": 40.0,
                "carbs_g": 0.0,
                "fat_g": 25.0,
                "fiber_g": 0.0
            }
        ]
    }
    put_res = client.put(f"/api/meals/{meal_id}", json=put_payload)
    assert put_res.status_code == 200
    updated_meal = put_res.json()
    assert updated_meal["total_calories_kcal"] == 410.0
    assert updated_meal["protein_g"] == 40.0

    # Suppression (DELETE)
    del_res = client.delete(f"/api/meals/{meal_id}")
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "success"

    # Test saisie rapide directe globale (kcal, macros sans décomposition d'aliments)
    direct_payload = {
        "date": date.today().isoformat(),
        "meal_type": "lunch",
        "total_calories_kcal": 650.0,
        "protein_g": 35.0,
        "carbs_g": 70.0,
        "fat_g": 20.0,
        "fiber_g": 6.0,
        "meal_name": "Déjeuner rapide restaurant"
    }
    direct_res = client.post("/api/meals", json=direct_payload)
    assert direct_res.status_code == 200
    direct_saved = direct_res.json()
    assert direct_saved["total_calories_kcal"] == 650.0
    assert direct_saved["protein_g"] == 35.0
    assert direct_saved["carbs_g"] == 70.0
    assert direct_saved["fat_g"] == 20.0
    assert len(direct_saved["items"]) == 1
    assert direct_saved["items"][0]["name"] == "Déjeuner rapide restaurant"



def test_api_devices_hub_and_sync(client):
    """Teste la liste des appareils IoT et le déclencheur de synchronisation."""
    # Liste des appareils
    res = client.get("/api/devices")
    assert res.status_code == 200
    devices = res.json()
    assert len(devices) >= 3
    ids = [d["id"] for d in devices]
    assert "withings" in ids
    assert "oura" in ids

    # Synchronisation
    sync_res = client.post("/api/devices/sync", json={"device_id": "withings"})
    assert sync_res.status_code == 200
    sync_data = sync_res.json()
    assert sync_data["status"] == "success"
    assert sync_data["device_id"] == "withings"


def test_api_serve_index_html(client):
    """Vérifie que la racine / sert bien le fichier HTML PWA."""
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "VitalTrack" in res.text
    assert "📸 Analyser mon repas" in res.text


def test_api_goals_presets(client):
    """Vérifie le point de terminaison des profils métaboliques prédéfinis 1-clic."""
    res = client.get("/api/goals/presets")
    assert res.status_code == 200
    data = res.json()
    assert "profiles" in data
    profiles = data["profiles"]
    
    # 1. Perte de poids durable (-0,5 kg/sem)
    assert "weight_loss" in profiles
    wl = profiles["weight_loss"]
    assert wl["calorie_target_delta"] == -500
    assert wl["protein_per_kg"] == 1.8
    assert wl["target_steps"] == 10000

    # 2. Maintien & vitalité (0 kcal)
    assert "maintenance" in profiles
    maint = profiles["maintenance"]
    assert maint["calorie_target_delta"] == 0
    assert maint["target_steps"] == 8500

    # 3. Recomposition corporelle (-200 kcal, P+ 2.2g/kg)
    assert "recomposition" in profiles
    recomp = profiles["recomposition"]
    assert recomp["calorie_target_delta"] == -200
    assert recomp["protein_per_kg"] == 2.2


def test_api_devices_comparison(client):
    """Vérifie le point de terminaison du guide comparatif des balances connectées."""
    res = client.get("/api/devices/comparison")
    assert res.status_code == 200
    data = res.json()
    assert "scales" in data
    scales = data["scales"]
    scale_ids = [s["id"] for s in scales]
    assert "withings" in scale_ids
    assert "garmin" in scale_ids
    assert "xiaomi" in scale_ids

    # Withings doit être la balance n°1 recommandée
    assert "Withings" in data["recommendation"]
    withings_scale = next(s for s in scales if s["id"] == "withings")
    assert "OAuth" in withings_scale["api_type"]
    assert "Wi-Fi" in withings_scale["connectivity"]

    # Bague RingConn & Oura
    assert "ring_integration" in data
    assert "RingConn" in data["ring_integration"]["name"] or "Oura" in data["ring_integration"]["name"]


def test_user_profile_crud(client):
    """Vérifie la récupération et la mise à jour du profil utilisateur personnalisé."""
    # 1. Lecture profil existant
    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()
    assert "profile" in data
    assert data["profile"]["name"] == "Sébastien"

    # 2. Mise à jour profil
    payload = {
        "name": "Sébastien L.",
        "gender": "male",
        "age": 36,
        "height_cm": 178.0,
        "target_weight_kg": 76.5,
        "preferred_ring": "ringconn",
        "preferred_scale": "withings"
    }
    update_res = client.post("/api/profile", json=payload)
    assert update_res.status_code == 200
    up_data = update_res.json()
    assert up_data["status"] == "success"
    assert up_data["profile"]["name"] == "Sébastien L."
    assert up_data["profile"]["target_weight_kg"] == 76.5


def test_connection_wizard_ringconn_and_health_connect(client):
    """Vérifie la connexion de la bague RingConn Gen 3 et de Google Health Connect via l'assistant."""
    # 1. Connexion RingConn Gen 3
    ring_payload = {
        "device_id": "ringconn",
        "name": "RingConn Gen 3 Smart Ring",
        "device_type": "ring",
        "auth_type": "google_health_connect",
        "connected": True
    }
    res_ring = client.post("/api/devices/connect", json=ring_payload)
    assert res_ring.status_code == 200
    data_ring = res_ring.json()
    assert data_ring["status"] == "success"
    assert data_ring["device"]["connected"] == 1

    # 2. Connexion Google Health Connect
    health_payload = {
        "device_id": "health_connect",
        "name": "Google Health Connect",
        "device_type": "mobile_aggregator",
        "auth_type": "google_health_connect",
        "connected": True
    }
    res_health = client.post("/api/devices/connect", json=health_payload)
    assert res_health.status_code == 200
    data_health = res_health.json()
    assert data_health["status"] == "success"


def test_vercel_endpoints_status_200(client):
    """Vérifie que les endpoints requis pour le déploiement Vercel répondent tous avec un statut 200."""
    endpoints = [
        "/",
        "/api/health",
        "/api/dashboard",
        "/api/meals/analyze-photo",
        "/api/weight",
        "/api/weights",
        "/api/activity",
        "/api/activities",
        "/api/devices",
        "/api/profile",
        "/api/backup/export"
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"Endpoint {ep} a renvoyé {res.status_code} au lieu de 200"


def test_backup_export_and_import(client):
    """Vérifie l'export complet JSON et la restauration/synchronisation."""
    # Insérer une pesée réelle pour tester l'export/import sans données démo
    client.post("/api/weights", json={"weight_kg": 78.4, "source": "manual"})

    # 1. Export
    exp_res = client.get("/api/backup/export")
    assert exp_res.status_code == 200
    backup = exp_res.json()
    assert "profile" in backup
    assert "weights" in backup
    assert "activities" in backup
    assert "meals" in backup
    assert isinstance(backup["weights"], list)

    # 2. Test Clear History
    clear_res = client.post("/api/profile/clear-history")
    assert clear_res.status_code == 200
    w_empty = client.get("/api/weights").json()
    assert len(w_empty) == 0

    # 3. Test Import / Restore
    imp_res = client.post("/api/backup/import", json={"data": backup, "overwrite": True})
    assert imp_res.status_code == 200
    imp_data = imp_res.json()
    assert imp_data["status"] == "success"
    assert imp_data["imported"]["weights"] >= 1

    w_restored = client.get("/api/weights").json()
    assert len(w_restored) >= 1


def test_reset_demo_data(client):
    """Vérifie la réinitialisation des données de démo 30 jours."""
    client.post("/api/profile/clear-history")
    assert len(client.get("/api/weights").json()) == 0

    res = client.post("/api/profile/reset-demo")
    assert res.status_code == 200
    assert len(client.get("/api/weights").json()) >= 30


def test_health_webhook_endpoints(client):
    """Vérifie la réception de pesées et d'activités via les endpoints webhooks."""
    webhook_payload = {
        "date": "2026-10-17",
        "source": "ringconn_gen3",
        "weight_kg": 78.9,
        "body_fat_pct": 19.1,
        "steps": 14200,
        "active_calories_kcal": 610.0,
        "resting_hr_bpm": 55,
        "hrv_ms": 64.0,
        "sleep_score": 89
    }
    res = client.post("/api/webhooks/ringconn", json=webhook_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["ingested"]["weight"] is not None
    assert data["ingested"]["weight"]["weight_kg"] == 78.9
    assert data["ingested"]["activity"] is not None
    assert data["ingested"]["activity"]["steps"] == 14200


def test_daily_sync_execution():
    """Vérifie que le script de synchronisation journalière s'exécute correctement."""
    from src.daily_sync import run_daily_sync
    run_daily_sync()


# =====================================================================
# Tests Stage 7 : Authentification Google Sign-In & Liaison Profil
# =====================================================================

def test_google_auth_config(client):
    """Vérifie la récupération et la mise à jour de la configuration Google OAuth."""
    # 1. Lecture de la config initiale
    res = client.get("/api/auth/config")
    assert res.status_code == 200
    cfg = res.json()
    assert "google_client_id" in cfg
    assert "scopes" in cfg
    assert len(cfg["scopes"]) >= 3
    assert cfg["demo_fallback_account"] == "sebastienlamoliate@gmail.com"

    # 2. Mise à jour du client_id
    test_id = "test-client-id-12345.apps.googleusercontent.com"
    put_res = client.put("/api/auth/config", json={"google_client_id": test_id})
    assert put_res.status_code == 200
    updated_cfg = put_res.json()["config"]
    assert updated_cfg["google_client_id"] == test_id
    assert updated_cfg["is_configured"] is True


def test_google_auth_and_profile_binding(client):
    """Vérifie l'authentification Google, la session active /api/auth/me et la liaison avec /api/profile."""
    # 1. État non-authentifié au départ
    me_init = client.get("/api/auth/me").json()
    assert me_init["session"]["is_authenticated"] is False

    # 2. Authentification Google (avec compte Sébastien LAMOLIATE)
    auth_payload = {
        "email": "sebastienlamoliate@gmail.com",
        "name": "Sébastien LAMOLIATE",
        "picture": "https://lh3.googleusercontent.com/a/test-avatar=s96-c",
        "sub": "google_sub_1092837465"
    }
    auth_res = client.post("/api/auth/google", json=auth_payload)
    assert auth_res.status_code == 200
    auth_data = auth_res.json()
    assert auth_data["status"] == "success"
    assert auth_data["session"]["is_authenticated"] is True
    assert auth_data["session"]["email"] == "sebastienlamoliate@gmail.com"

    # 3. Vérification de la session active via /api/auth/me
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["session"]["is_authenticated"] is True
    assert me_data["session"]["email"] == "sebastienlamoliate@gmail.com"
    assert me_data["profile"]["google_email"] == "sebastienlamoliate@gmail.com"

    # 4. Vérification de la liaison automatique dans /api/profile
    prof_res = client.get("/api/profile")
    assert prof_res.status_code == 200
    prof_data = prof_res.json()
    assert prof_data["profile"]["google_email"] == "sebastienlamoliate@gmail.com"
    assert prof_data["profile"]["google_name"] == "Sébastien LAMOLIATE"

    # 5. Déconnexion
    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    logout_data = logout_res.json()
    assert logout_data["status"] == "success"

    # Vérifier que la session active est désactivée
    me_after = client.get("/api/auth/me").json()
    assert me_after["session"]["is_authenticated"] is False


def test_api_health_aliases(client):
    """Vérifie que les alias /api, /api/ et /health répondent tous avec le statut 200."""
    for path in ["/api", "/api/", "/health", "/api/health"]:
        res = client.get(path)
        assert res.status_code == 200, f"Échec pour {path}: {res.status_code}"
        assert res.json()["status"] == "ok"


def test_vercel_path_resolver():
    """Vérifie que VercelPathResolver redirige fidèlement les requêtes serverless Vercel."""
    from api.index import app as vercel_app
    from fastapi.testclient import TestClient

    vercel_client = TestClient(vercel_app)

    # 1. Test du paramètre de rewrite Vercel ?__path=health
    res_health = vercel_client.get("/api/index.py?__path=health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "ok"

    # 2. Test du paramètre de rewrite Vercel ?__path=dashboard
    res_dash = vercel_client.get("/api/index.py?__path=dashboard")
    assert res_dash.status_code == 200
    assert "summary" in res_dash.json()

    # 3. Test de l'appel direct /api/index.py
    res_direct = vercel_client.get("/api/index.py")
    assert res_direct.status_code == 200
    assert res_direct.json()["status"] == "ok"


def test_api_serve_frontend_modules(client):
    """Vérifie que les modules front découplés et le thème CSS sont bien servis."""
    for path in [
        "/static/modules/theme.css",
        "/static/modules/api.js",
        "/static/modules/lazy.js",
        "/static/modules/dashboard.js",
        "/static/modules/nutrition.js",
        "/static/manifest.json"
    ]:
        res = client.get(path)
        assert res.status_code == 200, f"Échec pour {path}"
