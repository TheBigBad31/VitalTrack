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

import os

from fastapi import APIRouter, Depends, HTTPException

from src.auth import (
    AuthUser,
    GoogleAuthPayload,
    GoogleConfigUpdate,
    LoginRequest,
    RegisterRequest,
    UserPublicResponse,
    _is_production,
    create_access_token,
    hash_password,
    parse_google_identity,
    validate_password_strength,
    verify_password,
)
from src.db import Database
from src.dependencies import get_current_user, get_db, get_strict_user
from src.rate_limit import rate_limit_login, rate_limit_register


router = APIRouter(tags=["auth"])


def _is_admin_user(user: AuthUser) -> bool:
    """Vérifie si l'utilisateur dispose des privilèges d'administration."""
    raw_admins = os.getenv("ADMIN_EMAIL", "").strip()
    if raw_admins:
        admin_emails = {e.strip().lower() for e in raw_admins.split(",") if e.strip()}
        if user.email.strip().lower() in admin_emails:
            return True
    return user.id == 1


@router.get("/api/auth/config")
def get_auth_config(db: Database = Depends(get_db)):
    """Retourne la configuration Google OAuth/GIS (Client ID, scopes et statut)."""
    return db.get_google_config()


@router.put("/api/auth/config")
def update_auth_config(
    payload: GoogleConfigUpdate,
    current_user: AuthUser = Depends(get_strict_user),
    db: Database = Depends(get_db),
):
    """Enregistre ou met à jour le Google Client ID (Bearer admin requis, désactivé en prod)."""
    if _is_production():
        raise HTTPException(
            status_code=403,
            detail="En production, GOOGLE_CLIENT_ID est configuré uniquement via variable d'environnement.",
        )
    if not _is_admin_user(current_user):
        raise HTTPException(
            status_code=403,
            detail="Droits administrateur requis pour modifier la configuration Google OAuth.",
        )
    res = db.set_google_client_id(payload.google_client_id)
    return {
        "status": "success",
        "message": "Configuration Google Client ID enregistrée avec succès",
        "config": res,
    }


@router.post("/api/auth/register", dependencies=[Depends(rate_limit_register)])
@router.post("/api/register", dependencies=[Depends(rate_limit_register)], include_in_schema=False)
@router.post("/register", dependencies=[Depends(rate_limit_register)], include_in_schema=False)
def register_user(payload: RegisterRequest, db: Database = Depends(get_db)):
    """Inscription classique avec email et mot de passe sécurisé (hash bcrypt / PBKDF2)."""
    if not validate_password_strength(payload.password):
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au minimum 8 caractères")

    # Vérification stricte de doublon d'email (y compris comptes OAuth Google sans password_hash)
    existing = db.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=400, detail="Un compte avec cet email existe déjà")

    pwd_hash = hash_password(payload.password, method="bcrypt")
    user = db.get_or_create_user(
        email=payload.email,
        name=payload.name or payload.email.split("@")[0],
        password_hash=pwd_hash,
        auth_provider="email",
    )
    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    user_public = UserPublicResponse(
        id=user["id"],
        uuid=user["uuid"],
        email=user["email"],
        name=user.get("name"),
        picture=user.get("picture"),
        auth_provider=user.get("auth_provider", "email"),
        google_sub=user.get("google_sub"),
        created_at=user.get("created_at"),
        updated_at=user.get("updated_at"),
    ).model_dump()
    return {
        "status": "success",
        "message": "Compte créé avec succès",
        "access_token": token,
        "token_type": "bearer",
        "user": user_public,
    }


@router.post("/api/auth/login", dependencies=[Depends(rate_limit_login)])
@router.post("/api/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
@router.post("/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
def login_user(payload: LoginRequest, db: Database = Depends(get_db)):
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
    user_public = UserPublicResponse(
        id=user["id"],
        uuid=user["uuid"],
        email=user["email"],
        name=user.get("name"),
        picture=user.get("picture"),
        auth_provider=user.get("auth_provider", "email"),
        google_sub=user.get("google_sub"),
        created_at=user.get("created_at"),
        updated_at=user.get("updated_at"),
    ).model_dump()
    return {
        "status": "success",
        "message": "Connexion réussie",
        "access_token": token,
        "token_type": "bearer",
        "user": user_public,
    }


@router.post("/api/auth/google")
def authenticate_google_user(payload: GoogleAuthPayload, db: Database = Depends(get_db)):
    """Authentifie l'utilisateur via Google GIS (ID Token JWT vérifié cryptographiquement).

    Associe automatiquement le compte Google au profil utilisateur et génère un jeton JWT d'accès.
    """
    if not payload.credential or not payload.credential.strip():
        raise HTTPException(
            status_code=401,
            detail="ID Token Google (credential) requis pour l'authentification.",
        )

    cfg = db.get_google_config()
    client_id = (cfg.get("google_client_id") or "").strip() or None
    try:
        user_info = parse_google_identity(payload, verify_signature=True, client_id=client_id)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    session = db.login_google_user(
        email=user_info["email"],
        name=user_info["name"],
        picture=user_info.get("picture", ""),
        google_sub=user_info.get("google_sub", ""),
        auth_method=user_info.get("auth_method", "google_gis_jwt"),
    )
    user_id = session.get("user_id")
    user_uuid = session.get("uuid")
    if not user_id or not user_uuid:
        raise HTTPException(status_code=500, detail="Impossible d'initialiser la session utilisateur Google")

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
        user_id=user_id,
    )

    return {
        "status": "success",
        "message": f"Connecté avec succès en tant que {user_info['name']} ({user_info['email']})",
        "access_token": access_token,
        "token_type": "bearer",
        "session": session,
        "profile": user_profile,
    }


@router.get("/api/auth/me")
def get_current_google_session(
    current_user: AuthUser = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Retourne la session active, le jeton JWT et le profil associé."""
    session = db.get_google_session(email=current_user.email)
    profile = db.get_user_profile(user_id=current_user.id)
    token = create_access_token(current_user.id, current_user.uuid, current_user.email, current_user.name)
    return {
        "session": session,
        "profile": profile,
        "current_user": current_user.model_dump(),
        "access_token": token,
    }


@router.post("/api/auth/logout")
def logout_google_session(
    current_user: AuthUser = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Déconnecte la session active Google de l'utilisateur authentifié."""
    res = db.logout_google_user(email=current_user.email)
    return res
