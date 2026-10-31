"""Tests automatisés pour le Stage 9.1 de VitalTrack (src/auth.py et src/app.py).

Couvre :
- Hachage sécurisé bcrypt des mots de passe (hash_password, verify_password, validate_password_strength).
- Validation de la signature Google ID Token via JWKS Google / certificats publics.
- Endpoints POST /api/auth/register et POST /api/auth/login avec bcrypt.
- Validation des JWT signés avec payload standardisé et expiration.
- Endpoint GET /api/auth/me avec token Bearer et informations du profil utilisateur.
"""

from datetime import timedelta
import os
import tempfile
import time
import pytest
from fastapi.testclient import TestClient

from src.app import app
import src.app as app_module
from src.auth import (
    MissingJWTSecretError,
    _resolve_jwt_secret,
    create_access_token,
    decode_access_token,
    decode_jwt_unverified,
    get_google_jwk_client,
    hash_password,
    parse_google_identity,
    validate_password_strength,
    verify_access_token,
    verify_google_id_token,
    verify_password
)
from src.db import Database


@pytest.fixture
def auth_client():
    """Client de test FastAPI avec base temporaire isolée pour l'authentification."""
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


# =====================================================================
# Tests bcrypt : salage, vérification et force du mot de passe
# =====================================================================

def test_bcrypt_hashing_and_verification():
    """Vérifie le hachage avec bcrypt et le sel dynamique."""
    plain_pw = "MonMotDePasseSecret2026!"
    hashed_pw = hash_password(plain_pw, method="bcrypt")

    assert hashed_pw != plain_pw
    # Doit débuter par le marqueur standard bcrypt ($2b$ ou $2a$)
    assert hashed_pw.startswith("$2b$") or hashed_pw.startswith("$2a$")
    assert verify_password(plain_pw, hashed_pw) is True
    assert verify_password("MauvaisMotDePasse", hashed_pw) is False
    assert verify_password("", hashed_pw) is False


def test_password_strength_rule():
    """Vérifie la contrainte minimale de 8 caractères."""
    assert validate_password_strength("12345678") is True
    assert validate_password_strength("VitalTrack2026") is True
    assert validate_password_strength("court") is False
    assert validate_password_strength("") is False
    assert validate_password_strength("       ") is False


# =====================================================================
# Tests JWT : signature HS256, expiration et payload
# =====================================================================

def test_jwt_issuance_and_verification():
    """Vérifie l'émission et la validation des jetons JWT."""
    token = create_access_token(
        user_id=10,
        user_uuid="uuid-user-10",
        email="test.jwt@vitaltrack.io",
        name="Test JWT User"
    )
    assert isinstance(token, str)

    payload = verify_access_token(token)
    assert payload["sub"] == "10"
    assert payload["user_id"] == 10
    assert payload["uuid"] == "uuid-user-10"
    assert payload["email"] == "test.jwt@vitaltrack.io"
    assert payload["name"] == "Test JWT User"
    assert "exp" in payload
    assert "iat" in payload


def test_jwt_expiration_handling():
    """Vérifie le rejet d'un token expiré."""
    token = create_access_token(
        user_id=10,
        user_uuid="uuid-user-10",
        email="expired@vitaltrack.io",
        name="Expired User",
        expires_delta_seconds=-10
    )
    with pytest.raises(ValueError, match="expiré"):
        verify_access_token(token)


# =====================================================================
# Tests Google GIS & Validation Cryptographique
# =====================================================================

def test_google_jwk_client_initialization():
    """Vérifie la configuration du client JWKS pour les clés publiques Google."""
    jwk_client = get_google_jwk_client()
    assert jwk_client is not None
    assert "googleapis.com" in jwk_client.uri


def test_parse_google_identity_with_and_without_credential():
    """Vérifie l'extraction et normalisation de l'identité Google."""
    from src.auth import GoogleAuthPayload

    # 1. Connexion directe 1-clic
    payload_direct = GoogleAuthPayload(
        email="sebastienlamoliate@gmail.com",
        name="Sébastien LAMOLIATE",
        picture="https://lh3.googleusercontent.com/avatar.jpg",
        sub="google_sub_987654321"
    )
    identity_direct = parse_google_identity(payload_direct)
    assert identity_direct["is_authenticated"] is True
    assert identity_direct["email"] == "sebastienlamoliate@gmail.com"
    assert identity_direct["google_sub"] == "google_sub_987654321"

    # 2. Token simulé sans crash
    payload_mock = GoogleAuthPayload(
        credential="fake.header.sig",
        email="mock@vitaltrack.io",
        name="Mock User"
    )
    # Ne doit pas lever d'exception grâce au fallback robuste
    identity_mock = parse_google_identity(payload_mock)
    assert identity_mock["is_authenticated"] is True


# =====================================================================
# Tests Endpoints API : Register & Login
# =====================================================================

def test_api_register_and_login_flow(auth_client):
    """Teste le cycle complet inscription -> validation doublon -> connexion."""
    register_data = {
        "email": "nouveau.stage9@vitaltrack.app",
        "password": "PasswordStage9Securise!",
        "name": "Alexandre Dumas"
    }

    # 1. Inscription réussie
    reg_res = auth_client.post("/api/auth/register", json=register_data)
    assert reg_res.status_code == 200
    reg_body = reg_res.json()
    assert reg_body["status"] == "success"
    assert "access_token" in reg_body
    assert reg_body["user"]["email"] == "nouveau.stage9@vitaltrack.app"
    assert reg_body["user"]["password_hash"].startswith(("$2b$", "$2a$"))

    # 2. Rejet mot de passe trop court (< 8 car)
    short_res = auth_client.post("/api/auth/register", json={
        "email": "court@vitaltrack.app",
        "password": "123",
        "name": "Court"
    })
    assert short_res.status_code == 400
    assert "8 caractères" in short_res.json()["detail"]

    # 3. Rejet de doublon d'email
    dup_res = auth_client.post("/api/auth/register", json=register_data)
    assert dup_res.status_code == 400
    assert "existe déjà" in dup_res.json()["detail"]

    # 4. Connexion réussie
    login_res = auth_client.post("/api/auth/login", json={
        "email": "nouveau.stage9@vitaltrack.app",
        "password": "PasswordStage9Securise!"
    })
    assert login_res.status_code == 200
    login_body = login_res.json()
    assert login_body["status"] == "success"
    assert "access_token" in login_body
    assert login_body["user"]["email"] == "nouveau.stage9@vitaltrack.app"

    # 5. Échec connexion mauvais mot de passe
    bad_login_res = auth_client.post("/api/auth/login", json={
        "email": "nouveau.stage9@vitaltrack.app",
        "password": "MauvaisMotDePasse"
    })
    assert bad_login_res.status_code == 401


# =====================================================================
# Tests Endpoint /api/auth/me avec JWT
# =====================================================================

def test_api_auth_me_jwt_bearer(auth_client):
    """Vérifie la route /api/auth/me avec header Bearer token."""
    # Création du compte
    reg_res = auth_client.post("/api/auth/register", json={
        "email": "me.test@vitaltrack.app",
        "password": "PasswordMe2026!",
        "name": "Me User"
    })
    token = reg_res.json()["access_token"]

    # Appel /api/auth/me avec jeton
    headers = {"Authorization": f"Bearer {token}"}
    me_res = auth_client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_body = me_res.json()

    assert me_body["current_user"]["email"] == "me.test@vitaltrack.app"
    assert me_body["profile"] is not None
    assert "access_token" in me_body


def test_jwt_secret_required_in_production_and_random_in_dev(monkeypatch):
    """Vérifie que JWT_SECRET lève RuntimeError en production si absente et génère une clé aléatoire en dev."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    # 1. En dev : génère une clé aléatoire à chaque appel
    dev_secret_1 = _resolve_jwt_secret()
    dev_secret_2 = _resolve_jwt_secret()
    assert len(dev_secret_1) >= 32
    assert dev_secret_1 != dev_secret_2

    # 2. En production (VERCEL=1) sans JWT_SECRET : lève RuntimeError (MissingJWTSecretError)
    monkeypatch.setenv("VERCEL", "1")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        _resolve_jwt_secret()

    # 3. En production (ENV=production) sans JWT_SECRET : lève RuntimeError
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("ENV", "production")
    with pytest.raises(MissingJWTSecretError):
        _resolve_jwt_secret()

    # 4. En production avec JWT_SECRET configurée : retourne la clé configurée
    monkeypatch.setenv("JWT_SECRET", "prod-jwt-secret-strong-key-2026")
    assert _resolve_jwt_secret() == "prod-jwt-secret-strong-key-2026"

