"""Tests automatisés pour la gestion des objets connectés et le chiffrement au repos (Stage 10.4).

Couvre :
1. Chiffrement et déchiffrement transparents des tokens d'appareils (src/crypto.py).
2. Endpoints REST /api/devices (GET, POST /connect, DELETE /{id}, POST /{id}/sync).
3. Isolation multi-utilisateurs stricte : chaque utilisateur ne voit et ne pilote que ses propres appareils.
4. Absence totale de clés d'API et tokens en clair dans les réponses API publiques.
5. Intégration et mise à jour des préférences de profil (bague RingConn et balance Withings).
"""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.crypto import (
    MissingEncryptionKeyError,
    _resolve_key_seed,
    encrypt_data,
    decrypt_data,
    encrypt_credentials,
    decrypt_credentials,
)
import src.app as app_module


@pytest.fixture
def isolated_client():
    """Client de test FastAPI avec base temporaire isolée pour chaque test."""
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
    yield client, test_db

    app_module.db = old_db
    app_module.nutrition_engine.db = old_nutri_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_crypto_encryption_and_decryption():
    """Vérifie le fonctionnement du module de chiffrement symétrique fort Fernet."""
    secret = "rc_live_secret_ringconn_token_999888"
    enc = encrypt_data(secret)
    assert enc is not None
    assert enc != secret
    assert enc.startswith("enc::")

    dec = decrypt_data(enc)
    assert dec == secret

    # Test avec dictionnaire structuré de credentials
    creds = {
        "api_key": "rc_live_key_123",
        "refresh_token": "google_refresh_token_456",
        "client_secret": "withings_secret_789"
    }
    enc_creds = encrypt_credentials(creds)
    assert enc_creds.startswith("enc::")
    assert "rc_live_key_123" not in enc_creds

    dec_creds = decrypt_credentials(enc_creds)
    assert dec_creds == creds

    # Rétrocompatibilité : chaînes déjà en clair (acceptées hors production)
    assert decrypt_data("plain_key_123") == "plain_key_123"
    assert decrypt_credentials("plain_key_123") == {"api_key": "plain_key_123"}


def test_data_encryption_key_required_in_production_and_random_in_dev(monkeypatch):
    """Vérifie que DATA_ENCRYPTION_KEY lève RuntimeError en production si absente et génère une clé aléatoire en dev."""
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    # 1. En dev : génère une clé aléatoire
    seed1 = _resolve_key_seed()
    seed2 = _resolve_key_seed()
    assert len(seed1) >= 32
    assert seed1 != seed2

    # 2. En production (VERCEL=1) sans DATA_ENCRYPTION_KEY : lève RuntimeError (MissingEncryptionKeyError)
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="DATA_ENCRYPTION_KEY"):
        _resolve_key_seed()

    # 3. En production (ENV=production) sans DATA_ENCRYPTION_KEY : lève RuntimeError
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(MissingEncryptionKeyError):
        _resolve_key_seed()

    # 4. En production avec DATA_ENCRYPTION_KEY configurée : retourne la clé configurée
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "prod-encryption-key-strong-2026")
    assert _resolve_key_seed() == "prod-encryption-key-strong-2026"


def test_decrypt_data_rejects_unencrypted_in_production(monkeypatch):
    """Vérifie qu'en production, decrypt_data refuse et lève une exception sur les credentials non préfixés 'enc::'."""
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(ValueError, match="préfixe 'enc::' manquant"):
        decrypt_data("plain_unencrypted_token_123")


def test_devices_endpoints_lifecycle(isolated_client):
    """Teste le cycle de vie complet des appareils : liste, ajout/connect, sync et déconnexion."""
    client, test_db = isolated_client

    # Inscription d'un utilisateur
    reg = client.post("/api/auth/register", json={
        "email": "user1@vitaltrack.io",
        "password": "PasswordUser1!",
        "name": "Utilisateur 1"
    })
    token1 = reg.json()["access_token"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # 1. Lister les appareils
    res_list = client.get("/api/devices", headers=headers1)
    assert res_list.status_code == 200
    devices = res_list.json()
    assert isinstance(devices, list)
    device_ids = [d["id"] for d in devices]
    assert "ringconn" in device_ids
    assert "withings" in device_ids
    assert "health_connect" in device_ids

    # 2. Connecter une bague RingConn Gen 3 avec une clé secrète
    secret_key = "rc_live_token_for_user1"
    res_connect = client.post("/api/devices/connect", json={
        "device_id": "ringconn",
        "name": "RingConn Gen 3 de Test",
        "device_type": "ring",
        "auth_type": "ringconn_openapi",
        "api_key": secret_key,
        "connected": True
    }, headers=headers1)
    assert res_connect.status_code == 200
    conn_data = res_connect.json()
    assert conn_data["status"] == "success"
    assert "device" in conn_data
    # Vérifier qu'aucune clé en clair n'est retournée dans l'API
    assert "encrypted_credentials" not in conn_data["device"]
    assert conn_data["device"].get("api_key") is None
    assert conn_data["device"]["has_credentials"] is True
    assert conn_data["device"]["api_key_masked"] == "rc_l...ser1"

    # 3. Vérifier en base SQLite/Postgres que la clé est bien chiffrée
    raw_dev = test_db.get_user_device("ringconn", user_id=reg.json()["user"]["id"], reveal_secrets=True)
    assert raw_dev is not None
    assert raw_dev["credentials"]["api_key"] == secret_key

    # 4. Déclencher une synchronisation ciblée
    res_sync = client.post("/api/devices/ringconn/sync", headers=headers1)
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data["status"] == "success"
    assert sync_data["device_id"] == "ringconn"
    assert sync_data["sync_status"] == "connected"

    # 5. Déconnecter et révoquer l'appareil
    res_del = client.delete("/api/devices/ringconn", headers=headers1)
    assert res_del.status_code == 200
    assert res_del.json()["deleted"] is True

    # Vérifier que l'appareil est bien supprimé de la base
    dev_after_del = test_db.get_user_device("ringconn", user_id=reg.json()["user"]["id"])
    assert dev_after_del is None


def test_multi_user_device_isolation(isolated_client):
    """Vérifie l'étanchéité stricte : chaque profil n'accède qu'à ses propres appareils et secrets."""
    client, test_db = isolated_client

    # Création de deux utilisateurs distincts
    u1 = client.post("/api/auth/register", json={
        "email": "userA@vitaltrack.io", "password": "PasswordA!", "name": "User A"
    }).json()
    t1 = u1["access_token"]
    h1 = {"Authorization": f"Bearer {t1}"}

    u2 = client.post("/api/auth/register", json={
        "email": "userB@vitaltrack.io", "password": "PasswordB!", "name": "User B"
    }).json()
    t2 = u2["access_token"]
    h2 = {"Authorization": f"Bearer {t2}"}

    # User A configure sa RingConn avec clé secrète A
    client.post("/api/devices/connect", json={
        "device_id": "ringconn",
        "name": "Bague de A",
        "device_type": "ring",
        "api_key": "rc_secret_key_user_A"
    }, headers=h1)

    # User B configure sa Withings avec email B
    client.post("/api/devices/connect", json={
        "device_id": "withings",
        "name": "Balance de B",
        "device_type": "scale",
        "account_email": "userB_withings@example.com"
    }, headers=h2)

    # User A inspecte ses appareils : RingConn est connectée, Withings ne l'est pas
    devs_a = {d["id"]: d for d in client.get("/api/devices", headers=h1).json()}
    assert devs_a["ringconn"]["connected"] is True
    assert devs_a["ringconn"]["name"] == "Bague de A"
    assert devs_a["withings"]["connected"] is False

    # User B inspecte ses appareils : Withings est connectée, RingConn ne l'est pas
    devs_b = {d["id"]: d for d in client.get("/api/devices", headers=h2).json()}
    assert devs_b["withings"]["connected"] is True
    assert devs_b["withings"]["name"] == "Balance de B"
    assert devs_b["ringconn"]["connected"] is False

    # User B ne peut pas déconnecter l'appareil de User A
    del_res = client.delete("/api/devices/ringconn", headers=h2)
    assert del_res.json()["deleted"] is False

    # La bague de User A est toujours bien intacte en base
    dev_a_still_there = test_db.get_user_device("ringconn", user_id=u1["user"]["id"])
    assert dev_a_still_there is not None
    assert dev_a_still_there["name"] == "Bague de A"


def test_devices_data_map_with_fixtures_and_diagnostic(isolated_client):
    """Vérifie l'endpoint GET /api/devices/data-map (BALI-197) :
    - Matrice complète des 17 métriques avec statuts lu/stocké/rendu/7j/dernier point.
    - Diagnostic explicite de l'origine des pesées (Withings vs Santé Connect).
    - Coloration/statuts : 'unrendered' pour ingérés jamais affichés (SpO2, température, hydratation, etc.).
    """
    from datetime import date
    from src.models import (
        WeightEntry, DailyMetricsEntry, HydrationLogEntry, IntradaySampleEntry
    )

    client, test_db = isolated_client

    # 1. Inscription et token d'authentification
    reg = client.post("/api/auth/register", json={
        "email": "sebastien_diagnostic@vitaltrack.io",
        "password": "PasswordSebastien123!",
        "name": "Sébastien LAMOLIATE"
    })
    assert reg.status_code == 200
    user_id = reg.json()["user"]["id"]
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 2. Injection de données de fixtures
    # A. Pesée Santé Connect
    w_hc = WeightEntry(
        date=date.today(),
        weight_kg=78.5,
        body_fat_pct=18.2,
        muscle_mass_kg=39.1,
        water_pct=58.0,
        bmi=24.8,
        source="health_connect",
        external_id="hc_weight_uuid_101",
        measured_at=f"{date.today().isoformat()}T07:15:00Z"
    )
    test_db.insert_weight(w_hc, user_id=user_id)

    # B. Pesée Withings
    w_withings = WeightEntry(
        date=date.today(),
        weight_kg=78.7,
        body_fat_pct=18.4,
        muscle_mass_kg=39.0,
        water_pct=57.8,
        bmi=24.9,
        source="withings",
        external_id="withings_measure_202",
        measured_at=f"{date.today().isoformat()}T08:30:00Z"
    )
    test_db.insert_weight(w_withings, user_id=user_id)

    # C. Métriques enrichies de Santé Connect (SpO2, température cutanée, HRV SDNN - jamais affichés dans l'UI)
    dm = DailyMetricsEntry(
        user_id=user_id,
        date=date.today(),
        source="health_connect",
        steps=10450,
        active_calories_kcal=420.0,
        resting_hr_bpm=55,
        hrv_rmssd_ms=64.0,
        hrv_sdnn_ms=71.0,
        spo2_pct=98.5,
        skin_temperature_c=36.4,
        sleep_score=88
    )
    test_db.insert_daily_metric(dm, user_id=user_id)

    # D. Hydratation (non rendue dans l'UI)
    hyd = HydrationLogEntry(
        user_id=user_id,
        date=date.today(),
        timestamp=f"{date.today().isoformat()}T10:00:00Z",
        volume_ml=750.0,
        source="health_connect",
        external_id="hc_hydration_303"
    )
    test_db.insert_hydration_log(hyd, user_id=user_id)

    # E. Échantillon intraday FC (non rendu)
    sample = IntradaySampleEntry(
        user_id=user_id,
        source="health_connect",
        metric_type="hr",
        timestamp=f"{date.today().isoformat()}T07:15:30Z",
        value=62.0,
        unit="bpm"
    )
    test_db.insert_intraday_samples([sample], user_id=user_id)

    # F. Ingest brut avec masse osseuse
    test_db.insert_raw_ingest(
        source="health_connect",
        payload={"bone_mass_kg": 3.25, "date": date.today().isoformat()},
        user_id=user_id,
        endpoint="/api/webhook/health"
    )

    # G. Appareils configurés
    test_db.update_user_device(
        device_id="health_connect",
        name="Santé Connect (Xiaomi)",
        device_type="mobile_aggregator",
        connected=True,
        user_id=user_id
    )
    test_db.update_user_device(
        device_id="withings",
        name="Withings Body Smart",
        device_type="scale",
        connected=True,
        user_id=user_id
    )

    # 3. Appel de l'endpoint
    res = client.get("/api/devices/data-map", headers=headers)
    assert res.status_code == 200
    data = res.json()

    # 4. Vérification de la structure globale
    assert "summary" in data
    assert "devices" in data
    assert "weights_diagnostic" in data
    assert "metrics" in data
    assert len(data["metrics"]) == 17

    summary = data["summary"]
    assert summary["total_metric_types"] == 17
    assert summary["ingested_count"] >= 8
    # Des métriques ingérées mais non affichées doivent être détectées
    assert summary["unrendered_ingested_count"] >= 4

    # 5. Diagnostic des pesées de Sébastien
    diag = data["weights_diagnostic"]
    assert diag["total_weights"] == 2
    assert diag["by_source"]["health_connect"] == 1
    assert diag["by_source"]["withings"] == 1
    assert "Santé Connect" in diag["diagnosis_summary"]
    assert "Withings" in diag["diagnosis_summary"]
    assert "hybrid" in diag["primary_source"]

    recent_w = diag["recent_weights"]
    assert len(recent_w) == 2
    sources = [w["source_normalized"] for w in recent_w]
    assert "health_connect" in sources
    assert "withings" in sources

    # 6. Vérification fine par métrique
    metrics_by_key = {m["metric_key"]: m for m in data["metrics"]}

    # A. Poids (affiché dans l'UI)
    m_weight = metrics_by_key["weight"]
    assert m_weight["rendered_in_ui"] is True
    assert m_weight["global_status"] == "rendered"
    assert m_weight["by_source"]["health_connect"]["status"] == "rendered"
    assert m_weight["by_source"]["withings"]["status"] == "rendered"
    assert m_weight["by_source"]["health_connect"]["last_point"]["value"] == 78.5
    assert m_weight["by_source"]["withings"]["last_point"]["value"] == 78.7
    assert m_weight["by_source"]["oura"]["status"] == "unsupported"

    # B. SpO2 (ingéré mais jamais affiché -> ROUGE 'unrendered')
    m_spo2 = metrics_by_key["spo2_pct"]
    assert m_spo2["rendered_in_ui"] is False
    assert m_spo2["global_status"] == "unrendered"
    assert m_spo2["by_source"]["health_connect"]["status"] == "unrendered"
    assert m_spo2["by_source"]["health_connect"]["last_point"]["value"] == 98.5
    assert m_spo2["by_source"]["withings"]["status"] == "unsupported"

    # C. Température cutanée (ingéré mais jamais affiché -> ROUGE 'unrendered')
    m_temp = metrics_by_key["skin_temperature_c"]
    assert m_temp["rendered_in_ui"] is False
    assert m_temp["global_status"] == "unrendered"
    assert m_temp["by_source"]["health_connect"]["last_point"]["value"] == 36.4

    # D. HRV SDNN (ingéré mais jamais affiché -> ROUGE 'unrendered')
    m_sdnn = metrics_by_key["hrv_sdnn_ms"]
    assert m_sdnn["rendered_in_ui"] is False
    assert m_sdnn["global_status"] == "unrendered"
    assert m_sdnn["by_source"]["health_connect"]["last_point"]["value"] == 71.0

    # E. Hydratation (ingéré mais jamais affiché -> ROUGE 'unrendered')
    m_hyd = metrics_by_key["hydration"]
    assert m_hyd["rendered_in_ui"] is False
    assert m_hyd["global_status"] == "unrendered"
    assert "ml" in m_hyd["by_source"]["health_connect"]["last_point"]["value"]

    # F. FC Intraday (ingéré mais jamais affiché -> ROUGE 'unrendered')
    m_intra = metrics_by_key["intraday_hr"]
    assert m_intra["rendered_in_ui"] is False
    assert m_intra["global_status"] == "unrendered"

    # G. Masse osseuse (détectée via raw_ingest)
    m_bone = metrics_by_key["bone_mass_kg"]
    assert m_bone["rendered_in_ui"] is False
    assert m_bone["global_status"] == "unrendered"

    # 7. Vérification des sources et sync
    devs = data["devices"]
    assert devs["health_connect"]["connected"] is True
    assert devs["withings"]["connected"] is True
    assert devs["health_connect"]["last_sync_at"] is not None


def test_devices_data_map_empty_user(isolated_client):
    """Vérifie le comportement de /api/devices/data-map sur un profil vierge sans aucune donnée."""
    client, test_db = isolated_client

    reg = client.post("/api/auth/register", json={
        "email": "virgin_user@vitaltrack.io",
        "password": "PasswordVirgin1!",
        "name": "Utilisateur Vierge"
    })
    token = reg.json()["access_token"]

    res = client.get("/api/devices/data-map", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["summary"]["ingested_count"] == 0
    assert data["weights_diagnostic"]["total_weights"] == 0
    assert data["weights_diagnostic"]["primary_source"] == "none"
    assert len(data["metrics"]) == 17


def test_devices_ui_data_map_panel_presence():
    """Vérifie la présence du panneau 'Données connectées' dans le hub devices (BALI-197)."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    assert 'id="connected-data-panel"' in html
    assert 'id="data-map-weights-diagnostic"' in html
    assert 'id="diag-weights-tbody"' in html
    assert 'id="data-map-tbody"' in html
    assert "Données Connectées" in html
    assert "Diagnostic Pesées" in html

    with open("static/modules/dashboard.js", "r", encoding="utf-8") as f:
        js = f.read()

    assert "function loadConnectedDataMap" in js
    assert "function renderConnectedDataMap" in js
    assert "function filterDataMap" in js
    assert "/api/devices/data-map" in js


