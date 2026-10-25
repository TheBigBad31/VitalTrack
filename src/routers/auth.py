"""Routeur FastAPI : auth."""

import os
import datetime as dt_module
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
import yaml

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, MealType, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.nutrition_rules import evaluate_dish_benefits
from src.connectors.webhook import MobileHealthWebhookConnector
from src.auth import (
    AuthUser, GoogleAuthPayload, GoogleConfigUpdate, LoginRequest, RegisterRequest,
    create_access_token, decode_access_token, hash_password, parse_google_identity,
    validate_password_strength, verify_password
)
from src.deps import (
    db, nutrition_engine, calorie_estimator, device_registry,
    get_current_user, get_strict_user
)
from src.schemas import *  # noqa: F401,F403

router = APIRouter()


# =====================================================================
# Endpoints Authentification Google Sign-In (OAuth2 / GIS) & JWT
# =====================================================================

@router.get("/api/auth/config")
def get_auth_config():
    """Retourne la configuration Google OAuth/GIS (Client ID, scopes et statut)."""
    return db.get_google_config()


@router.put("/api/auth/config")
def update_auth_config(payload: GoogleConfigUpdate):
    """Enregistre ou met à jour le Google Client ID depuis l'interface."""
    res = db.set_google_client_id(payload.google_client_id)
    return {
        "status": "success",
        "message": "Configuration Google Client ID enregistrée avec succès",
        "config": res
    }


@router.post("/api/auth/register")
def register_user(payload: RegisterRequest):
    """Inscription classique avec email et mot de passe sécurisé (hash bcrypt / PBKDF2)."""
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


@router.post("/api/auth/login")
def login_user(payload: LoginRequest):
    """Connexion classique par email et mot de passe."""
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
def get_current_google_session(current_user: AuthUser = Depends(get_current_user)):
    """Retourne la session active, le jeton JWT et le profil associé."""
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
    res = db.logout_google_user()
    return res


# =====================================================================
# Endpoints Profil Utilisateur & Assistant de Connexion
# =====================================================================

@router.get("/api/profile")
def get_user_profile(current_user: AuthUser = Depends(get_current_user)):
    """Renvoie le profil utilisateur personnalisé et ses préférences d'objets pour l'utilisateur connecté."""
    profile = db.get_user_profile(user_id=current_user.id)
    devices = db.get_user_devices(user_id=current_user.id)
    return {
        "profile": profile,
        "connected_devices": devices
    }


@router.post("/api/profile")
@router.put("/api/profile")
def update_user_profile(profile_in: UserProfileInput, current_user: AuthUser = Depends(get_current_user)):
    """Met à jour ou crée le profil utilisateur pour l'utilisateur connecté."""
    updated = db.update_user_profile(profile_in.model_dump(), user_id=current_user.id)
    return {
        "status": "success",
        "message": "Profil mis à jour avec succès",
        "profile": updated
    }


@router.get("/api/backup/export")
def export_backup(current_user: AuthUser = Depends(get_current_user)):
    """Exporte l'intégralité du profil utilisateur, des appareils configurés et de l'historique."""
    backup_data = db.export_full_backup(user_id=current_user.id)
    return backup_data


@router.post("/api/backup/import")
def import_backup(payload: BackupRestoreInput, current_user: AuthUser = Depends(get_current_user)):
    """Restaure ou synchronise les données depuis un export JSON ou le localStorage/IndexedDB."""
    result = db.import_full_backup(payload.data, overwrite=payload.overwrite, user_id=current_user.id)
    return result


@router.post("/api/profile/reset-demo")
def reset_demo(current_user: AuthUser = Depends(get_current_user)):
    """Réinitialise et recharge le jeu complet de données de démonstration réaliste 30 jours."""
    db.reset_demo_data(user_id=current_user.id)
    return {
        "status": "success",
        "message": "Données de démonstration 30 jours réinitialisées avec succès"
    }


@router.post("/api/profile/clear-history")
def clear_history(current_user: AuthUser = Depends(get_current_user)):
    """Efface l'historique tout en conservant les paramètres de profil pour un suivi personnel réel."""
    db.clear_all_history(keep_profile=True, user_id=current_user.id)
    return {
        "status": "success",
        "message": "Historique effacé. Vous pouvez démarrer votre suivi réel !"
    }

