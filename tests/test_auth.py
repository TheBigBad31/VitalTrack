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
    """Vérifie la contrainte minimale de 8 caractères et de diversité des caractères."""
    assert validate_password_strength("12345678") is True
    assert validate_password_strength("VitalTrack2026") is True
    assert validate_password_strength("court") is False
    assert validate_password_strength("") is False
    assert validate_password_strength("       ") is False
    assert validate_password_strength("aaaaaaaa") is False
    assert validate_password_strength("11111111") is False
    assert validate_password_strength("!@#$%^&*") is False


def test_bcrypt_long_password_over_72_bytes_no_truncation():
    """Vérifie que le pré-hachage SHA-256 empêche la troncature à 72 octets sur bcrypt."""
    base_72 = "A" * 72
    pw1 = base_72 + "_suffixe_secret_1"
    pw2 = base_72 + "_suffixe_secret_2"

    hashed_pw1 = hash_password(pw1, method="bcrypt")
    assert verify_password(pw1, hashed_pw1) is True
    # Sans pré-hachage SHA-256, pw2 aurait été accepté à cause de la troncature à 72 octets
    assert verify_password(pw2, hashed_pw1) is False


def test_pbkdf2_600k_iterations_and_backward_compatibility():
    """Vérifie le hachage PBKDF2 à >= 600 000 itérations et la rétrocompatibilité (PBKDF2 100k et bcrypt legacy)."""
    import bcrypt
    import hashlib
    import secrets
    from src.auth import PBKDF2_ITERATIONS

    assert PBKDF2_ITERATIONS >= 600_000

    # 1. Nouveau hash PBKDF2 (>= 600 000 itérations)
    plain = "MotDePassePBKDF2Fort2026!"
    new_pbkdf2 = hash_password(plain, method="pbkdf2")
    assert "600000" in new_pbkdf2
    assert verify_password(plain, new_pbkdf2) is True
    assert verify_password("AutreMotDePasse", new_pbkdf2) is False

    # 2. Rétrocompatibilité avec ancien hash PBKDF2 à 100 000 itérations (format salt$hex)
    legacy_salt = secrets.token_hex(16)
    legacy_digest = hashlib.pbkdf2_hmac("sha256", plain.encode("utf-8"), legacy_salt.encode("utf-8"), 100_000).hex()
    legacy_pbkdf2_hash = f"{legacy_salt}${legacy_digest}"
    assert verify_password(plain, legacy_pbkdf2_hash) is True
    assert verify_password("MauvaisMotDePasse", legacy_pbkdf2_hash) is False

    # 3. Rétrocompatibilité avec ancien hash bcrypt direct (sans pré-hachage SHA-256)
    legacy_bcrypt_hash = bcrypt.hashpw(plain.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode("utf-8")
    assert verify_password(plain, legacy_bcrypt_hash) is True
    assert verify_password("MauvaisMotDePasse", legacy_bcrypt_hash) is False


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


def test_parse_google_identity_with_and_without_credential(monkeypatch):
    """Vérifie le rejet strict sans credential et la validation cryptographique du jeton Google GIS."""
    from src.auth import GoogleAuthPayload
    import src.auth as auth_module

    # 1. Absence de credential (tentative 1-clic non signée) -> rejet strict
    payload_direct = GoogleAuthPayload(
        email="spoofed@vitaltrack.test",
        name="Spoofed User",
        picture="https://lh3.googleusercontent.com/avatar.jpg",
        sub="google_sub_987654321"
    )
    with pytest.raises(ValueError, match="credential"):
        parse_google_identity(payload_direct)

    # 2. Token avec signature invalide -> Rejet strict par exception ValueError
    payload_invalid = GoogleAuthPayload(
        credential="fake.header.sig",
        email="mock@vitaltrack.io",
        name="Mock User"
    )
    with pytest.raises(ValueError, match="Validation cryptographique Google échouée"):
        parse_google_identity(payload_invalid, verify_signature=True)

    # 3. Token validé cryptographiquement -> utilise uniquement les claims signés (ignore payload.email/name)
    monkeypatch.setattr(
        auth_module,
        "verify_google_id_token",
        lambda token, expected_client_id=None: {
            "email": "verified.user@vitaltrack.test",
            "email_verified": True,
            "name": "Verified User",
            "picture": "https://lh3.googleusercontent.com/verified.jpg",
            "sub": "google_sub_verified_123",
        },
    )
    payload_valid = GoogleAuthPayload(
        credential="valid.signed.idtoken",
        email="attacker@evil.test",
        name="Attacker",
    )
    identity = parse_google_identity(payload_valid, verify_signature=True, client_id="client-id.apps.googleusercontent.com")
    assert identity["is_authenticated"] is True
    assert identity["email"] == "verified.user@vitaltrack.test"
    assert identity["name"] == "Verified User"
    assert identity["google_sub"] == "google_sub_verified_123"
    assert identity["auth_method"] == "google_gis_jwt"


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
    assert "password_hash" not in reg_body["user"]

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
    assert "password_hash" not in login_body["user"]

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

def test_strict_auth_enforced_in_production_and_strict_mode(monkeypatch):
    """Valide que sans token, 401 est retourne sur /api/dashboard, /api/devices/*/token, /api/meals en mode strict/prod."""
    import src.app as app_module
    from src.app import app

    client = TestClient(app)

    # 1. Tester sous REQUIRE_STRICT_AUTH=1
    monkeypatch.setenv("REQUIRE_STRICT_AUTH", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("ENV", raising=False)

    res_dash = client.get("/api/dashboard")
    assert res_dash.status_code == 401

    res_meals = client.get("/api/meals")
    assert res_meals.status_code == 401

    res_dev = client.post("/api/devices/withings/token")
    assert res_dev.status_code == 401

    res_friends = client.get("/api/friends")
    assert res_friends.status_code == 401

    # 2. Tester sous VERCEL=1
    monkeypatch.delenv("REQUIRE_STRICT_AUTH", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    res_dash_prod = client.get("/api/dashboard")
    assert res_dash_prod.status_code == 401

    res_meals_prod = client.get("/api/meals")
    assert res_meals_prod.status_code == 401

    res_dev_prod = client.post("/api/devices/withings/token")
    assert res_dev_prod.status_code == 401

    res_friends_prod = client.get("/api/friends")
    assert res_friends_prod.status_code == 401


# =====================================================================
# Tests de non-régression Sécurité P0 (BALI-308)
# =====================================================================

def test_google_auth_rejects_missing_credential_and_forged_token(auth_client, monkeypatch):
    """POST /api/auth/google sans credential ou avec jeton falsifié renvoie 401 (dev et prod)."""
    import src.auth as auth_module

    # 1. Sans credential en prod -> 401
    monkeypatch.setenv("VERCEL", "1")
    res_prod_no_cred = auth_client.post(
        "/api/auth/google",
        json={"email": "victim@vitaltrack.test", "name": "Victim"},
    )
    assert res_prod_no_cred.status_code == 401

    # 2. Sans credential hors prod -> 401 également (aucun bypass 1-clic)
    monkeypatch.delenv("VERCEL", raising=False)
    res_dev_no_cred = auth_client.post(
        "/api/auth/google",
        json={"email": "victim@vitaltrack.test", "name": "Victim"},
    )
    assert res_dev_no_cred.status_code == 401

    # 3. Credential falsifié -> 401 (jamais 500)
    res_forged = auth_client.post(
        "/api/auth/google",
        json={"credential": "forged.jwt.signature"},
    )
    assert res_forged.status_code == 401

    # 4. En prod sans GOOGLE_CLIENT_ID -> 401 (refuse verify_aud=False)
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
    res_no_aud = auth_client.post(
        "/api/auth/google",
        json={"credential": "some.jwt.token"},
    )
    assert res_no_aud.status_code == 401

    # 5. Avec ID Token Google vérifié et GOOGLE_CLIENT_ID configuré -> 200
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "valid-client-id.apps.googleusercontent.com")
    monkeypatch.setattr(
        auth_module,
        "verify_google_id_token",
        lambda token, expected_client_id=None: {
            "email": "gis.valid@vitaltrack.test",
            "email_verified": True,
            "name": "GIS Valid User",
            "picture": "https://lh3.googleusercontent.com/pic.jpg",
            "sub": "google_sub_valid_42",
        },
    )
    res_ok = auth_client.post(
        "/api/auth/google",
        json={"credential": "valid.signed.gis.token"},
    )
    assert res_ok.status_code == 200
    body = res_ok.json()
    assert body["access_token"]
    assert body["session"]["email"] == "gis.valid@vitaltrack.test"


def test_strict_auth_rejects_anonymous_even_with_active_google_session(auth_client, monkeypatch):
    """Une ligne google_sessions.is_active=1 ne doit jamais contourner l'auth Bearer en mode strict/prod."""
    # Créer une session Google active dans la table globale google_sessions
    sess = app_module.db.login_google_user(
        email="active.session@vitaltrack.test",
        name="Active Google User",
        google_sub="google_sub_active_99",
        auth_method="google_gis_jwt",
    )
    assert sess["is_authenticated"] is True

    # Activer le mode strict / prod
    monkeypatch.setenv("REQUIRE_STRICT_AUTH", "1")
    monkeypatch.setenv("VERCEL", "1")

    # Sans Bearer : /api/dashboard, /api/auth/me et /api/auth/logout doivent renvoyer 401
    assert auth_client.get("/api/dashboard").status_code == 401
    assert auth_client.get("/api/auth/me").status_code == 401
    assert auth_client.post("/api/auth/logout").status_code == 401

    # Avec Bearer valide : /api/dashboard renvoie 200
    token = create_access_token(sess["user_id"], sess["uuid"], sess["email"], sess["name"])
    res_auth = auth_client.get("/api/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert res_auth.status_code == 200


def test_auth_config_requires_strict_bearer_admin_and_disabled_in_prod(auth_client, monkeypatch):
    """PUT /api/auth/config renvoie 401 sans Bearer, 403 si non-admin ou en prod, 200 pour admin en dev."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)

    # 1. Sans Bearer (même hors mode strict) -> 401
    res_anon = auth_client.put(
        "/api/auth/config",
        json={"google_client_id": "hijacked.apps.googleusercontent.com"},
    )
    assert res_anon.status_code == 401

    # 2. Utilisateur standard (id != 1) -> 403
    reg_std = auth_client.post(
        "/api/auth/register",
        json={
            "email": "standard.user@vitaltrack.test",
            "password": "StandardPassword2026!",
            "name": "Standard User",
        },
    )
    assert reg_std.status_code == 200
    std_token = reg_std.json()["access_token"]
    res_std = auth_client.put(
        "/api/auth/config",
        json={"google_client_id": "hijacked.apps.googleusercontent.com"},
        headers={"Authorization": f"Bearer {std_token}"},
    )
    assert res_std.status_code == 403

    # 3. Admin (id == 1) hors prod -> 200
    admin_user = app_module.db._ensure_default_user()
    admin_token = create_access_token(
        admin_user["id"], admin_user["uuid"], admin_user["email"], admin_user.get("name")
    )
    res_admin = auth_client.put(
        "/api/auth/config",
        json={"google_client_id": "dev-admin-client.apps.googleusercontent.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["config"]["google_client_id"] == "dev-admin-client.apps.googleusercontent.com"

    # 4. En production : PUT refusé (403) et GET lit uniquement GOOGLE_CLIENT_ID env
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-prod-client.apps.googleusercontent.com")
    res_prod_put = auth_client.put(
        "/api/auth/config",
        json={"google_client_id": "override-attempt.apps.googleusercontent.com"},
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res_prod_put.status_code == 403

    cfg_prod = auth_client.get("/api/auth/config").json()
    assert cfg_prod["google_client_id"] == "env-prod-client.apps.googleusercontent.com"
    assert "demo_fallback_account" not in cfg_prod


def test_register_prevents_google_account_takeover(auth_client):
    """Un compte créé via Google (password_hash=None) ne peut pas être repris via /api/auth/register."""
    app_module.db.login_google_user(
        email="google.owner@vitaltrack.test",
        name="Google Owner",
        google_sub="google_sub_owner_777",
        auth_method="google_gis_jwt",
    )
    existing = app_module.db.get_user_by_email("google.owner@vitaltrack.test")
    assert existing is not None
    assert existing.get("password_hash") is None

    res_takeover = auth_client.post(
        "/api/auth/register",
        json={
            "email": "google.owner@vitaltrack.test",
            "password": "AttackerNewPassword2026!",
            "name": "Attacker",
        },
    )
    assert res_takeover.status_code == 400
    assert "existe déjà" in res_takeover.json()["detail"]
    assert "access_token" not in res_takeover.json()


def test_logout_requires_auth_and_scoped_to_user(auth_client, monkeypatch):
    """POST /api/auth/logout exige une auth en mode strict et ne déconnecte que l'utilisateur courant."""
    sess_a = app_module.db.login_google_user(
        email="logout.a@vitaltrack.test",
        name="User A",
        google_sub="sub_a",
        auth_method="google_gis_jwt",
    )
    sess_b = app_module.db.login_google_user(
        email="logout.b@vitaltrack.test",
        name="User B",
        google_sub="sub_b",
        auth_method="google_gis_jwt",
    )

    monkeypatch.setenv("REQUIRE_STRICT_AUTH", "1")
    assert auth_client.post("/api/auth/logout").status_code == 401

    token_a = create_access_token(sess_a["user_id"], sess_a["uuid"], sess_a["email"], sess_a["name"])
    token_b = create_access_token(sess_b["user_id"], sess_b["uuid"], sess_b["email"], sess_b["name"])

    res_logout_a = auth_client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token_a}"})
    assert res_logout_a.status_code == 200

    # User A est déconnecté, User B reste actif
    me_a = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_a}"}).json()
    me_b = auth_client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_b}"}).json()
    assert me_a["session"]["is_authenticated"] is False
    assert me_b["session"]["is_authenticated"] is True
    assert me_b["session"]["email"] == "logout.b@vitaltrack.test"
