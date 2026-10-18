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


@pytest.fixture
def client():
    """Client de test FastAPI."""
    return TestClient(app)


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
    assert len(data["weights_history"]) > 0
    assert "activities_history" in data
    assert len(data["activities_history"]) > 0
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

    # 2. Récupération
    get_res = client.get("/api/weights?limit=5")
    assert get_res.status_code == 200
    weights = get_res.json()
    assert any(w["weight_kg"] == 78.5 for w in weights)


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
    """Teste l'enregistrement d'un repas dans le journal alimentaire."""
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

    # Bague Oura
    assert "ring_integration" in data
    assert "Oura" in data["ring_integration"]["name"]


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
        "/api/devices"
    ]
    for ep in endpoints:
        res = client.get(ep)
        assert res.status_code == 200, f"Endpoint {ep} a renvoyé {res.status_code} au lieu de 200"


def test_daily_sync_execution():
    """Vérifie que le script de synchronisation journalière s'exécute correctement."""
    from src.daily_sync import run_daily_sync
    run_daily_sync()

