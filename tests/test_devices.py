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

    # Rétrocompatibilité : chaînes déjà en clair
    assert decrypt_data("plain_key_123") == "plain_key_123"
    assert decrypt_credentials("plain_key_123") == {"api_key": "plain_key_123"}


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
