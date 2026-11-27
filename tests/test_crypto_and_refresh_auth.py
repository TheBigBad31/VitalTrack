"""Tests de sécurité Palier 2 (BALI-315) :
- Chiffrement fail-closed en production (src/crypto.py)
- Rotation de clés versionnées MultiFernet (v1 -> v2 + rétrocompatibilité enc::)
- Access tokens courts (30 min) et refresh tokens SHA-256 révocables avec rotation et détection de réutilisation
"""

import pytest
from fastapi.testclient import TestClient

import src.app as app_module
import src.auth as auth_module
from src.app import app
from src.auth import (
    JWT_EXPIRE_SECONDS,
    create_access_token,
    decode_access_token,
    hash_refresh_token,
)
from src.crypto import (
    MissingEncryptionKeyError,
    decrypt_credentials,
    decrypt_data,
    encrypt_credentials,
    encrypt_data,
    get_active_key_version,
    is_encrypted_value,
    rotate_encrypted_data,
)


# =====================================================================
# 1. Crypto fail-closed en production & Rotation MultiFernet
# =====================================================================


def test_encrypt_data_fails_closed_in_production_without_key(monkeypatch):
    """En prod sans DATA_ENCRYPTION_KEYS / DATA_ENCRYPTION_KEY / SECRET_KEY, encrypt_data échoue explicitement."""
    monkeypatch.delenv("DATA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    with pytest.raises(MissingEncryptionKeyError, match="fail-closed"):
        encrypt_data("super_secret_iot_token")

    with pytest.raises(MissingEncryptionKeyError, match="fail-closed"):
        encrypt_credentials({"api_key": "withings_secret"})

    with pytest.raises(MissingEncryptionKeyError):
        decrypt_data("enc:v1::gAAAAABfake")


def test_device_connect_returns_503_in_prod_without_encryption_key(client, monkeypatch):
    """L'écriture d'un credential d'appareil en prod sans clé de chiffrement renvoie HTTP 503 (jamais clé jetable)."""
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "failclosed.crypto@vitaltrack.test",
            "password": "StrongPassword2026!",
            "name": "Fail Closed Crypto",
        },
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]

    monkeypatch.delenv("DATA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    res = client.post(
        "/api/devices/connect",
        json={
            "device_id": "ringconn",
            "name": "RingConn Prod",
            "device_type": "ring",
            "api_key": "rc_prod_secret_key",
            "connected": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 503
    assert "DATA_ENCRYPTION_KEY" in res.json()["detail"]


def test_multifernet_key_rotation_v1_to_v2_and_legacy_compat(monkeypatch):
    """Rotation v1 -> v2 : déchiffre les secrets legacy (enc::) et v1 (enc:v1::), chiffre les nouveaux en enc:v2::."""
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    # Étape 0 : secret chiffré avec l'ancien format mono-clé DATA_ENCRYPTION_KEY (enc::...)
    monkeypatch.delenv("DATA_ENCRYPTION_KEYS", raising=False)
    monkeypatch.setenv("DATA_ENCRYPTION_KEY", "legacy_v1_master_seed_2025")
    legacy_cipher = encrypt_data("legacy_withings_token_abc")
    assert legacy_cipher is not None
    assert legacy_cipher.startswith("enc::")
    assert is_encrypted_value(legacy_cipher) is True

    # Étape 1 : activation de DATA_ENCRYPTION_KEYS avec v1
    monkeypatch.delenv("DATA_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", "v1:legacy_v1_master_seed_2025")
    assert get_active_key_version() == "v1"
    v1_cipher = encrypt_data("v1_ringconn_secret_xyz")
    assert v1_cipher is not None
    assert v1_cipher.startswith("enc:v1::")
    assert is_encrypted_value(v1_cipher) is True
    assert decrypt_data(legacy_cipher) == "legacy_withings_token_abc"
    assert decrypt_data(v1_cipher) == "v1_ringconn_secret_xyz"

    # Étape 2 : rotation vers v2 en conservant v1 en lecture
    monkeypatch.setenv(
        "DATA_ENCRYPTION_KEYS",
        "v2:new_v2_master_seed_2026,v1:legacy_v1_master_seed_2025",
    )
    assert get_active_key_version() == "v2"

    # Anciens secrets legacy et v1 toujours lisibles sans perte
    assert decrypt_data(legacy_cipher) == "legacy_withings_token_abc"
    assert decrypt_data(v1_cipher) == "v1_ringconn_secret_xyz"

    # Nouveaux secrets chiffrés en v2
    v2_cipher = encrypt_data("v2_oura_secret_999")
    assert v2_cipher is not None
    assert v2_cipher.startswith("enc:v2::")
    assert decrypt_data(v2_cipher) == "v2_oura_secret_999"

    # Credentials dict en v2 + ré-encryption (rotation explicite d'un secret v1 -> v2)
    creds = {"access_token": "tok_v2", "refresh_token": "ref_v2"}
    enc_creds = encrypt_credentials(creds)
    assert enc_creds is not None and enc_creds.startswith("enc:v2::")
    assert decrypt_credentials(enc_creds) == creds

    rotated_cipher = rotate_encrypted_data(v1_cipher)
    assert rotated_cipher is not None
    assert rotated_cipher.startswith("enc:v2::")
    assert decrypt_data(rotated_cipher) == "v1_ringconn_secret_xyz"

    # Étape 3 : retrait de v1 après migration -> les secrets ré-encryptés en v2 restent lisibles
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", "v2:new_v2_master_seed_2026")
    assert decrypt_data(rotated_cipher) == "v1_ringconn_secret_xyz"
    assert decrypt_data(v2_cipher) == "v2_oura_secret_999"
    # L'ancien secret v1 non migré échoue proprement (InvalidToken -> None)
    assert decrypt_data(v1_cipher) is None


# =====================================================================
# 2. Access tokens courts & Refresh tokens SHA-256 révocables + rotation
# =====================================================================


def test_short_lived_access_token_default_ttl():
    """La durée de vie par défaut des access tokens est courte (entre 15 et 60 min)."""
    assert 15 * 60 <= JWT_EXPIRE_SECONDS <= 60 * 60

    token = create_access_token(1, "uuid-1", "short@vitaltrack.test", "Short User")
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["exp"] - payload["iat"] == JWT_EXPIRE_SECONDS


def test_refresh_token_stored_hashed_and_rotation_flow(client, db):
    """Register/Login émettent un refresh token hashé SHA-256 en DB ; /api/auth/refresh effectue une rotation."""
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "refresh.flow@vitaltrack.test",
            "password": "RefreshPassword2026!",
            "name": "Refresh Flow",
        },
    )
    assert reg.status_code == 200
    reg_body = reg.json()
    assert reg_body["access_token"]
    assert reg_body["refresh_token"]
    assert reg_body["expires_in"] == JWT_EXPIRE_SECONDS

    raw_rt_1 = reg_body["refresh_token"]
    expected_hash_1 = hash_refresh_token(raw_rt_1)

    # Vérifier que le token brut n'est jamais stocké en clair en base, seul son hash SHA-256
    with db.get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM refresh_tokens WHERE token_hash = ?", (expected_hash_1,))
        row = cur.fetchone()
        assert row is not None
        assert row["token_hash"] == expected_hash_1
        assert row["token_hash"] != raw_rt_1
        assert row["revoked_at"] is None

    # Rotation via POST /api/auth/refresh
    ref_res = client.post("/api/auth/refresh", json={"refresh_token": raw_rt_1})
    assert ref_res.status_code == 200
    ref_body = ref_res.json()
    assert ref_body["status"] == "success"
    assert ref_body["access_token"]
    assert ref_body["refresh_token"]
    assert ref_body["refresh_token"] != raw_rt_1
    assert ref_body["user"]["email"] == "refresh.flow@vitaltrack.test"

    raw_rt_2 = ref_body["refresh_token"]

    # Le nouvel access token fonctionne sur une route protégée
    me_res = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {ref_body['access_token']}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["current_user"]["email"] == "refresh.flow@vitaltrack.test"

    # Rejouer l'ancien refresh token (déjà tourné) -> 401 ET révocation de toute la famille (reuse detection)
    replay_res = client.post("/api/auth/refresh", json={"refresh_token": raw_rt_1})
    assert replay_res.status_code == 401

    # Le token successeur de la famille compromise est également révoqué
    compromised_res = client.post("/api/auth/refresh", json={"refresh_token": raw_rt_2})
    assert compromised_res.status_code == 401


def test_logout_revokes_refresh_token_and_blocks_refresh(client):
    """Un refresh token révoqué au logout ne permet plus d'obtenir un nouvel access token."""
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "logout.refresh@vitaltrack.test",
            "password": "LogoutPassword2026!",
            "name": "Logout Refresh",
        },
    )
    assert reg.status_code == 200
    access_1 = reg.json()["access_token"]
    refresh_1 = reg.json()["refresh_token"]

    # Deuxième session (ex: second appareil)
    login_2 = client.post(
        "/api/auth/login",
        json={
            "email": "logout.refresh@vitaltrack.test",
            "password": "LogoutPassword2026!",
        },
    )
    assert login_2.status_code == 200
    access_2 = login_2.json()["access_token"]
    refresh_2 = login_2.json()["refresh_token"]

    # 1. Logout ciblé sur refresh_1
    out_1 = client.post(
        "/api/auth/logout",
        json={"refresh_token": refresh_1},
        headers={"Authorization": f"Bearer {access_1}"},
    )
    assert out_1.status_code == 200
    assert out_1.json()["revoked_tokens"] == 1

    # refresh_1 est désormais rejeté
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh_1}).status_code == 401

    # refresh_2 (autre appareil) reste valide
    ref_2 = client.post("/api/auth/refresh", json={"refresh_token": refresh_2})
    assert ref_2.status_code == 200
    refresh_2_rotated = ref_2.json()["refresh_token"]

    # 2. Logout sans body (révocation globale de l'utilisateur courant)
    out_all = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {access_2}"},
    )
    assert out_all.status_code == 200
    assert out_all.json()["revoked_tokens"] >= 1

    # refresh_2_rotated est désormais également rejeté
    assert client.post("/api/auth/refresh", json={"refresh_token": refresh_2_rotated}).status_code == 401


def test_expired_refresh_token_rejected(client, db):
    """Un refresh token expiré est rejeté par POST /api/auth/refresh."""
    reg = client.post(
        "/api/auth/register",
        json={
            "email": "expired.rt@vitaltrack.test",
            "password": "ExpiredRTPassword2026!",
            "name": "Expired RT",
        },
    )
    user_id = reg.json()["user"]["id"]
    expired = db.create_refresh_token(user_id=user_id, expires_in_seconds=-5)

    res = client.post("/api/auth/refresh", json={"refresh_token": expired["refresh_token"]})
    assert res.status_code == 401


def test_google_auth_issues_refresh_token_and_revokes_on_logout(client, monkeypatch):
    """POST /api/auth/google délivre un refresh_token révocable au logout."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-client-rt.apps.googleusercontent.com")
    monkeypatch.setattr(
        auth_module,
        "verify_google_id_token",
        lambda token, expected_client_id=None: {
            "email": "google.rt@vitaltrack.test",
            "email_verified": True,
            "name": "Google RT User",
            "picture": "https://lh3.googleusercontent.com/rt.jpg",
            "sub": "google_sub_rt_123",
        },
    )

    res = client.post("/api/auth/google", json={"credential": "valid.signed.google.jwt"})
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["refresh_token"]

    # Logout révoque le refresh token Google
    out = client.post(
        "/api/auth/logout",
        json={"refresh_token": body["refresh_token"]},
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert out.status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]}).status_code == 401
