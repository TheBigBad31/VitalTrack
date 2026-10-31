"""Router FastAPI pour l'authentification Google Sign-In (OAuth2 / GIS) et JWT (VitalTrack).

Endpoints :
- GET  /api/auth/config     : configuration Google OAuth/GIS (Client ID, scopes et statut)
- PUT  /api/auth/config     : enregistrement du Google Client ID depuis l'interface
- POST /api/auth/register   : inscription classique email + mot de passe
- POST /api/auth/login      : connexion classique email + mot de passe
- POST /api/auth/google     : authentification via Google GIS (ID Token JWT)
- GET  /api/auth/me         : session active, jeton JWT et profil associé
- POST /api/auth/logout     : déconnexion de la session active Google
"""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import (
    AuthUser,
    GoogleAuthPayload,
    GoogleConfigUpdate,
    LoginRequest,
    RegisterRequest,
    create_access_token,
    decode_access_token,
    hash_password,
    parse_google_identity,
    validate_password_strength,
    verify_password
)
from src.db import Database
from src.rate_limit import rate_limit_login, rate_limit_register


router = APIRouter(tags=["auth"])


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


@router.get("/api/auth/config")
def get_auth_config():
    """Retourne la configuration Google OAuth/GIS (Client ID, scopes et statut)."""
    db = get_db()
    return db.get_google_config()


@router.put("/api/auth/config")
def update_auth_config(payload: GoogleConfigUpdate):
    """Enregistre ou met à jour le Google Client ID depuis l'interface."""
    db = get_db()
    res = db.set_google_client_id(payload.google_client_id)
    return {
        "status": "success",
        "message": "Configuration Google Client ID enregistrée avec succès",
        "config": res
    }


@router.post("/api/auth/register", dependencies=[Depends(rate_limit_register)])
@router.post("/api/register", dependencies=[Depends(rate_limit_register)], include_in_schema=False)
@router.post("/register", dependencies=[Depends(rate_limit_register)], include_in_schema=False)
def register_user(payload: RegisterRequest):
    """Inscription classique avec email et mot de passe sécurisé (hash bcrypt / PBKDF2)."""
    db = get_db()
    if not validate_password_strength(payload.password):
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au minimum 8 caractères")

    # Vérification de doublon d'email
    existing = db.get_user_by_email(payload.email)
    if existing and existing.get("password_hash"):
        raise HTTPException(status_code=400, detail="Un compte avec cet email existe déjà")

    pwd_hash = hash_password(payload.password, method="bcrypt")
    user = db.get_or_create_user(
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        password_hash=pwd_hash,
        auth_provider="email"
    )
    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    return {
        "status": "success",
        "message": "Compte créé avec succès",
        "access_token": token,
        "token_type": "bearer",
        "user": user
    }


@router.post("/api/auth/login", dependencies=[Depends(rate_limit_login)])
@router.post("/api/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
@router.post("/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
def login_user(payload: LoginRequest):
    """Connexion classique par email et mot de passe."""
    db = get_db()
    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (payload.email.strip().lower(),))
        user = cursor.fetchone()

    if not user or not user.get("password_hash"):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    if not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email ou mot de passe incorrect")

    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    return {
        "status": "success",
        "message": "Connexion réussie",
        "access_token": token,
        "token_type": "bearer",
        "user": dict(user)
    }


@router.post("/api/auth/google")
def authenticate_google_user(payload: GoogleAuthPayload):
    """Authentifie l'utilisateur via Google GIS (ID Token JWT) ou connexion directe 1-clic.

    Associe automatiquement le compte Google au profil utilisateur et génère un jeton JWT d'accès.
    """
    db = get_db()
    cfg = db.get_google_config()
    client_id = cfg.get("google_client_id")
    user_info = parse_google_identity(payload, verify_signature=True, client_id=client_id)
    session = db.login_google_user(
        email=user_info["email"],
        name=user_info["name"],
        picture=user_info.get("picture", ""),
        google_sub=user_info.get("google_sub", ""),
        auth_method=user_info.get("auth_method", "google")
    )
    user_id = session.get("user_id") or 1
    user_uuid = session.get("uuid") or "00000000-0000-4000-8000-000000000001"
    user_profile = db.get_user_profile(user_id=user_id)

    # Générer le token JWT Bearer pour les requêtes futures
    access_token = create_access_token(user_id, user_uuid, user_info["email"], user_info["name"])

    # Assurer que l'appareil Google Health Connect est configuré pour cet utilisateur
    db.update_user_device(
        device_id="health_connect",
        name="Google Health Connect (Android)",
        device_type="mobile_aggregator",
        connected=True,
        auth_type="google_health_connect",
        account_email=user_info["email"],
        user_id=user_id
    )

    return {
        "status": "success",
        "message": f"Connecté avec succès en tant que {user_info['name']} ({user_info['email']})",
        "access_token": access_token,
        "token_type": "bearer",
        "session": session,
        "profile": user_profile
    }


@router.get("/api/auth/me")
def get_current_google_session(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Retourne la session active, le jeton JWT et le profil associé."""
    db = get_db()
    session = db.get_google_session()
    profile = db.get_user_profile(user_id=current_user.id)
    token = create_access_token(current_user.id, current_user.uuid, current_user.email, current_user.name)
    return {
        "session": session,
        "profile": profile,
        "current_user": current_user.model_dump(),
        "access_token": token
    }


@router.post("/api/auth/logout")
def logout_google_session():
    """Déconnecte la session active Google."""
    db = get_db()
    res = db.logout_google_user()
    return res
