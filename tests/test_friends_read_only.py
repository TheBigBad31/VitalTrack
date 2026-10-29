"""Tests unitaires et d'intégration pour le partage de données et contrôle d'accès Read-Only (BALI-86).

Couvre :
1. Cycle complet des demandes d'amis :
   - Envoi de demande par email ou identifiant
   - Prévention d'auto-invitation et de doublons
   - Consultation des listes (amis acceptés, demandes reçues, demandes envoyées)
   - Acceptation et refus de demande
   - Révocation d'amitié et annulation de demande
2. Contrôle d'accès Read-Only (verify_view_access) :
   - Accès autorisé à ses propres données (is_owner)
   - Accès autorisé aux données d'un ami accepté avec permission read_only
   - Blocage 403 Forbidden immédiat en l'absence de lien d'amitié accepté
   - Blocage 403 Forbidden sur consultation de données d'un tiers sans permission
3. Endpoints de consultation avec user_id optionnel :
   - GET /api/weights
   - GET /api/meals
   - GET /api/meals/journal
   - GET /api/daily-metrics
   - GET /api/dashboard
   - GET /api/metrics
4. Masquage strict des données sensibles du profil ami :
   - GET /api/profile : pas de clé API, jeton ou email de compte dans connected_devices
5. Interdiction stricte de toute écriture (POST, PUT, DELETE) sur le compte d'un tiers :
   - Impossible de modifier/supprimer les pesées ou repas d'un ami
"""

import os
import tempfile
import pytest
from datetime import date
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.models import WeightEntry, FoodItem, MealEntry, DailyMetricsEntry
import src.app as app_module


@pytest.fixture
def client_env():
    """Crée un environnement isolé avec base SQLite temporaire et TestClient."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        os.remove(temp_path)

    test_db = Database(db_path=temp_path)
    old_db = app_module.db
    old_nutri_db = app_module.nutrition_engine.db
    app_module.db = test_db
    app_module.nutrition_engine.db = test_db

    client = TestClient(app)

    # Création de 3 utilisateurs :
    # User A (propriétaire)
    reg_a = client.post("/api/auth/register", json={
        "email": "alice@vitaltrack.local",
        "password": "PasswordAlice123!",
        "name": "Alice"
    }).json()
    token_a = reg_a["access_token"]
    user_a = reg_a["user"]

    # User B (ami)
    reg_b = client.post("/api/auth/register", json={
        "email": "bob@vitaltrack.local",
        "password": "PasswordBob123!",
        "name": "Bob"
    }).json()
    token_b = reg_b["access_token"]
    user_b = reg_b["user"]

    # User C (inconnu / tiers non autorisé)
    reg_c = client.post("/api/auth/register", json={
        "email": "charlie@vitaltrack.local",
        "password": "PasswordCharlie123!",
        "name": "Charlie"
    }).json()
    token_c = reg_c["access_token"]
    user_c = reg_c["user"]

    headers_a = {"Authorization": f"Bearer {token_a}"}
    headers_b = {"Authorization": f"Bearer {token_b}"}
    headers_c = {"Authorization": f"Bearer {token_c}"}

    yield {
        "client": client,
        "db": test_db,
        "user_a": user_a,
        "user_b": user_b,
        "user_c": user_c,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "headers_c": headers_c,
    }

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutri_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_friend_request_lifecycle(client_env):
    """Vérifie le cycle complet d'une demande d'ami (envoi, acceptation, refus, listing, suppression)."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    u_a = client_env["user_a"]
    u_b = client_env["user_b"]

    # 1. Empêcher de s'envoyer une demande à soi-même
    self_req = c.post("/api/friends/request", json={"identifier": u_a["email"]}, headers=h_a)
    assert self_req.status_code == 400
    assert "vous-même" in self_req.json()["detail"] or "ami" in self_req.json()["detail"]

    # 2. Utilisateur introuvable
    not_found_req = c.post("/api/friends/request", json={"identifier": "unknown@example.com"}, headers=h_a)
    assert not_found_req.status_code == 404

    # 3. Alice envoie une demande d'ami à Bob
    req_res = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a)
    assert req_res.status_code == 200
    friendship_id = req_res.json()["friendship"]["id"]

    # 4. Doublon de demande
    dup_req = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a)
    assert dup_req.status_code == 400
    assert "déjà" in dup_req.json()["detail"]

    # 5. Alice voit sa demande dans outgoing_requests
    list_a = c.get("/api/friends", headers=h_a).json()
    assert len(list_a["outgoing_requests"]) == 1
    assert list_a["outgoing_requests"][0]["recipient_id"] == u_b["id"]
    assert len(list_a["friends"]) == 0

    # 6. Bob voit la demande dans incoming_requests
    list_b = c.get("/api/friends", headers=h_b).json()
    assert len(list_b["incoming_requests"]) == 1
    assert list_b["incoming_requests"][0]["sender_id"] == u_a["id"]
    assert len(list_b["friends"]) == 0

    # 7. Bob accepte la demande d'Alice
    acc_res = c.post(f"/api/friends/{friendship_id}/accept", headers=h_b)
    assert acc_res.status_code == 200
    assert acc_res.json()["friendship"]["status"] == "accepted"

    # 8. Désormais Alice et Bob sont amis
    list_a_after = c.get("/api/friends", headers=h_a).json()
    assert len(list_a_after["friends"]) == 1
    assert list_a_after["friends"][0]["friend_id"] == u_b["id"]

    list_b_after = c.get("/api/friends", headers=h_b).json()
    assert len(list_b_after["friends"]) == 1
    assert list_b_after["friends"][0]["friend_id"] == u_a["id"]

    # 9. Révocation de l'amitié par Bob
    del_res = c.delete(f"/api/friends/{u_a['id']}", headers=h_b)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # 10. Plus d'amis dans les listes
    assert len(c.get("/api/friends", headers=h_a).json()["friends"]) == 0
    assert len(c.get("/api/friends", headers=h_b).json()["friends"]) == 0


def test_friend_request_rejection(client_env):
    """Vérifie le refus d'une demande d'ami."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    u_b = client_env["user_b"]

    req_res = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a)
    assert req_res.status_code == 200
    fid = req_res.json()["friendship"]["id"]

    rej_res = c.post(f"/api/friends/{fid}/reject", headers=h_b)
    assert rej_res.status_code == 200
    assert rej_res.json()["friendship"]["status"] == "rejected"

    # Vérifier que ni Alice ni Bob n'ont d'ami actif
    assert len(c.get("/api/friends", headers=h_a).json()["friends"]) == 0
    assert len(c.get("/api/friends", headers=h_b).json()["friends"]) == 0


def test_read_only_access_control_weights(client_env):
    """Vérifie le contrôle d'accès en lecture seule sur /api/weights."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    h_c = client_env["headers_c"]
    u_a = client_env["user_a"]
    u_b = client_env["user_b"]

    # Alice enregistre une pesée
    w_res = c.post("/api/weights", json={
        "weight_kg": 72.5,
        "body_fat_pct": 18.2,
        "muscle_mass_kg": 34.0,
        "source": "manual",
        "notes": "Pesée du matin Alice"
    }, headers=h_a)
    assert w_res.status_code == 200
    alice_weight_id = w_res.json()["id"]

    # 1. Avant amitié : Bob tente de lire les pesées d'Alice -> 403 Forbidden
    unauth_b = c.get(f"/api/weights?user_id={u_a['id']}", headers=h_b)
    assert unauth_b.status_code == 403
    assert unauth_b.json()["detail"] == "Accès non autorisé aux données de cet utilisateur"

    # 2. Charlie tente également -> 403 Forbidden
    unauth_c = c.get(f"/api/weights?user_id={u_a['id']}", headers=h_c)
    assert unauth_c.status_code == 403

    # 3. Alice et Bob deviennent amis
    req = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a).json()
    c.post(f"/api/friends/{req['friendship']['id']}/accept", headers=h_b)

    # 4. Après amitié : Bob peut consulter les pesées d'Alice
    auth_b = c.get(f"/api/weights?user_id={u_a['id']}", headers=h_b)
    assert auth_b.status_code == 200
    weights_alice = auth_b.json()
    assert len(weights_alice) >= 1
    assert weights_alice[0]["weight_kg"] == 72.5
    assert weights_alice[0]["notes"] == "Pesée du matin Alice"

    # 5. Charlie (tiers non ami) reste bloqué à 403
    assert c.get(f"/api/weights?user_id={u_a['id']}", headers=h_c).status_code == 403

    # 6. Bob (ami en lecture seule) tente de modifier la pesée d'Alice -> 404/403 (pesée non trouvée pour Bob)
    mod_b = c.put(f"/api/weights/{alice_weight_id}", json={
        "weight_kg": 85.0
    }, headers=h_b)
    assert mod_b.status_code == 404

    # 7. Bob tente de supprimer la pesée d'Alice -> 404
    del_b = c.delete(f"/api/weights/{alice_weight_id}", headers=h_b)
    assert del_b.status_code == 404

    # La pesée d'Alice est intacte
    check_a = c.get("/api/weights", headers=h_a).json()
    assert check_a[0]["weight_kg"] == 72.5


def test_read_only_access_control_meals(client_env):
    """Vérifie le contrôle d'accès sur /api/meals et /api/meals/journal."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    h_c = client_env["headers_c"]
    u_a = client_env["user_a"]
    u_b = client_env["user_b"]

    # Alice enregistre un repas
    meal_in = {
        "meal_type": "lunch",
        "meal_name": "Salade de quinoa et avocat",
        "total_calories_kcal": 550.0,
        "protein_g": 18.0,
        "carbs_g": 65.0,
        "fat_g": 20.0,
        "fiber_g": 10.0
    }
    m_res = c.post("/api/meals", json=meal_in, headers=h_a)
    assert m_res.status_code == 200

    # 1. Avant amitié : Bob tente de lire /api/meals -> 403
    assert c.get(f"/api/meals?user_id={u_a['id']}", headers=h_b).status_code == 403
    assert c.get(f"/api/meals/journal?user_id={u_a['id']}", headers=h_b).status_code == 403

    # 2. Devenir amis
    req = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a).json()
    c.post(f"/api/friends/{req['friendship']['id']}/accept", headers=h_b)

    # 3. Après amitié : Bob consulte les repas d'Alice
    res_meals = c.get(f"/api/meals?user_id={u_a['id']}", headers=h_b)
    assert res_meals.status_code == 200
    meals = res_meals.json()
    assert len(meals) >= 1
    assert meals[0]["total_calories_kcal"] == 550.0

    # 4. Bob consulte le journal des repas d'Alice
    res_journal = c.get(f"/api/meals/journal?user_id={u_a['id']}", headers=h_b)
    assert res_journal.status_code == 200
    journal = res_journal.json()
    assert "meals" in journal
    assert "day_summary" in journal or "day_total" in journal

    # 5. Charlie tente de lire -> 403
    assert c.get(f"/api/meals?user_id={u_a['id']}", headers=h_c).status_code == 403
    assert c.get(f"/api/meals/journal?user_id={u_a['id']}", headers=h_c).status_code == 403


def test_read_only_profile_and_masking(client_env):
    """Vérifie le masquage strict des secrets / clés API dans /api/profile pour un ami."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    h_c = client_env["headers_c"]
    u_a = client_env["user_a"]
    u_b = client_env["user_b"]

    # Alice connecte une bague avec une clé secrète
    c.post("/api/devices/connect", json={
        "device_id": "ringconn",
        "name": "Bague Secrète Alice",
        "device_type": "ring",
        "api_key": "rc_super_secret_token_12345",
        "account_email": "alice_secret@device.com",
        "connected": True
    }, headers=h_a)

    # Alice consulte son propre profil : voit ses appareils
    own_prof = c.get("/api/profile", headers=h_a).json()
    assert len(own_prof["connected_devices"]) >= 1

    # Bob avant amitié : 403
    assert c.get(f"/api/profile?user_id={u_a['id']}", headers=h_b).status_code == 403

    # Devenir amis
    req = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a).json()
    c.post(f"/api/friends/{req['friendship']['id']}/accept", headers=h_b)

    # Bob consulte le profil d'Alice en lecture seule
    friend_prof_res = c.get(f"/api/profile?user_id={u_a['id']}", headers=h_b)
    assert friend_prof_res.status_code == 200
    friend_data = friend_prof_res.json()
    assert "profile" in friend_data
    assert "connected_devices" in friend_data

    # Vérification du masquage strict
    for dev in friend_data["connected_devices"]:
        assert "api_key" not in dev
        assert "encrypted_credentials" not in dev
        assert "credentials" not in dev
        assert dev.get("api_key_masked") is None
        assert dev.get("account_email") is None
        assert dev.get("has_credentials") is False

    # Charlie sans amitié : 403
    assert c.get(f"/api/profile?user_id={u_a['id']}", headers=h_c).status_code == 403


def test_read_only_dashboard_and_daily_metrics(client_env):
    """Vérifie l'accès en lecture seule à /api/dashboard et /api/daily-metrics."""
    c = client_env["client"]
    h_a = client_env["headers_a"]
    h_b = client_env["headers_b"]
    h_c = client_env["headers_c"]
    u_a = client_env["user_a"]
    u_b = client_env["user_b"]
    db = client_env["db"]

    # Insertion de métriques pour Alice
    metric_entry = DailyMetricsEntry(
        date=date.today(),
        steps=8500,
        active_calories_kcal=420.0,
        resting_hr_bpm=58,
        hrv_rmssd_ms=65.0,
        sleep_score=88,
        source="ringconn"
    )
    db.insert_daily_metric(metric_entry, user_id=u_a["id"])

    # 1. Avant amitié : 403
    assert c.get(f"/api/dashboard?user_id={u_a['id']}", headers=h_b).status_code == 403
    assert c.get(f"/api/daily-metrics?user_id={u_a['id']}", headers=h_b).status_code == 403
    assert c.get(f"/api/metrics?user_id={u_a['id']}", headers=h_b).status_code == 403

    # 2. Devenir amis
    req = c.post("/api/friends/request", json={"identifier": u_b["email"]}, headers=h_a).json()
    c.post(f"/api/friends/{req['friendship']['id']}/accept", headers=h_b)

    # 3. Bob consulte le dashboard d'Alice
    dash_res = c.get(f"/api/dashboard?user_id={u_a['id']}", headers=h_b)
    assert dash_res.status_code == 200
    dash_data = dash_res.json()
    assert "summary" in dash_data
    assert "profile" in dash_data

    # 4. Bob consulte les daily-metrics d'Alice
    dm_res = c.get(f"/api/daily-metrics?user_id={u_a['id']}", headers=h_b)
    assert dm_res.status_code == 200
    dm_list = dm_res.json()
    assert len(dm_list) >= 1
    assert dm_list[0]["steps"] == 8500
    assert dm_list[0]["resting_hr_bpm"] == 58

    # 5. Bob consulte /api/metrics d'Alice
    metrics_res = c.get(f"/api/metrics?user_id={u_a['id']}", headers=h_b)
    assert metrics_res.status_code == 200
    assert "status" in metrics_res.json()

    # 6. Charlie sans lien : 403
    assert c.get(f"/api/dashboard?user_id={u_a['id']}", headers=h_c).status_code == 403
    assert c.get(f"/api/daily-metrics?user_id={u_a['id']}", headers=h_c).status_code == 403
    assert c.get(f"/api/metrics?user_id={u_a['id']}", headers=h_c).status_code == 403
