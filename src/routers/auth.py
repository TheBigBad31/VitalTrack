"""Router FastAPI pour l'authentification Google Sign-In (OAuth2 / GIS), JWT court et Refresh Tokens (VitalTrack).

Endpoints :
- GET  /api/auth/config     : configuration Google OAuth/GIS (Client ID, scopes et statut)
- PUT  /api/auth/config     : enregistrement du Google Client ID depuis l'interface
- POST /api/auth/register   : inscription classique email + mot de passe (access + refresh token)
- POST /api/auth/login      : connexion classique email + mot de passe (access + refresh token)
- POST /api/auth/google     : authentification via Google GIS ID Token JWT (access + refresh token)
- POST /api/auth/refresh    : renouvellement d'access token avec rotation du refresh token
- GET  /api/auth/me         : session active, jeton JWT et profil associé
- POST /api/auth/logout     : déconnexion et révocation des refresh tokens
"""

import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request

from src.auth import (
    JWT_EXPIRE_SECONDS,
    AuthUser,
    GoogleAuthPayload,
    GoogleConfigUpdate,
    LoginRequest,
    LogoutRequest,
    RefreshTokenRequest,
    RegisterRequest,
    UserPublicResponse,
    _is_production,
    create_access_token,
    decode_access_token,
    hash_password,
    is_strict_auth_enabled,
    parse_google_identity,
    validate_password_strength,
    verify_password,
)
from src.dependencies import get_db
from src.rate_limit import rate_limit_login, rate_limit_refresh, rate_limit_register


router = APIRouter(tags=["auth"])


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token")
) -> AuthUser:
    """Résout l'utilisateur courant via src.app.get_current_user de manière dynamique."""
    import sys
    app_module = sys.modules.get("src.app")
    if app_module and hasattr(app_module, "get_current_user"):
        return app_module.get_current_user(authorization=authorization, x_webhook_token=x_webhook_token)

    # Résolution directe en fallback
    db = get_db()
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        payload = decode_access_token(token)
        if payload and "user_id" in payload:
            user_data = db.get_user_by_id(int(payload["user_id"]))
            if user_data:
                return AuthUser(
                    id=user_data["id"],
                    uuid=user_data["uuid"],
                    email=user_data["email"],
                    name=user_data.get("name"),
                    picture=user_data.get("picture"),
                    auth_provider=user_data.get("auth_provider", "google"),
                    google_sub=user_data.get("google_sub"),
                )
    raise HTTPException(status_code=401, detail="Authentification requise")


def get_strict_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Exige un jeton Bearer JWT valide (sans fallback dev ni session globale)."""
    import sys
    app_module = sys.modules.get("src.app")
    if app_module and hasattr(app_module, "get_strict_user"):
        return app_module.get_strict_user(authorization=authorization)

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant ou invalide")
    token = authorization.split("Bearer ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Jeton JWT expiré ou signature invalide")
    db = get_db()
    user_data = db.get_user_by_id(int(payload["user_id"]))
    if not user_data:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return AuthUser(
        id=user_data["id"],
        uuid=user_data["uuid"],
        email=user_data["email"],
        name=user_data.get("name"),
        picture=user_data.get("picture"),
        auth_provider=user_data.get("auth_provider", "google"),
        google_sub=user_data.get("google_sub"),
    )


def _is_admin_user(user: AuthUser) -> bool:
    """Vérifie si l'utilisateur dispose des privilèges d'administration."""
    raw_admins = os.getenv("ADMIN_EMAIL", "").strip()
    if raw_admins:
        admin_emails = {e.strip().lower() for e in raw_admins.split(",") if e.strip()}
        if user.email.strip().lower() in admin_emails:
            return True
    return user.id == 1


def _to_user_public(user: Dict[str, Any]) -> Dict[str, Any]:
    return UserPublicResponse(
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


@router.get("/api/auth/config")
def get_auth_config():
    """Retourne la configuration Google OAuth/GIS (Client ID, scopes et statut)."""
    db = get_db()
    return db.get_google_config()


@router.put("/api/auth/config")
def update_auth_config(
    payload: GoogleConfigUpdate,
    current_user: AuthUser = Depends(get_strict_user),
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
def register_user(payload: RegisterRequest, request: Request):
    """Inscription classique avec email et mot de passe sécurisé (hash bcrypt / PBKDF2)."""
    db = get_db()
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
        auth_provider="email"
    )
    token = create_access_token(user["id"], user["uuid"], user["email"], user.get("name"))
    refresh_data = db.create_refresh_token(
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "status": "success",
        "message": "Compte créé avec succès",
        "access_token": token,
        "refresh_token": refresh_data["refresh_token"],
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_SECONDS,
        "user": _to_user_public(user),
    }


@router.post("/api/auth/login", dependencies=[Depends(rate_limit_login)])
@router.post("/api/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
@router.post("/login", dependencies=[Depends(rate_limit_login)], include_in_schema=False)
def login_user(payload: LoginRequest, request: Request):
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
    refresh_data = db.create_refresh_token(
        user_id=user["id"],
        user_agent=request.headers.get("user-agent"),
    )
    return {
        "status": "success",
        "message": "Connexion réussie",
        "access_token": token,
        "refresh_token": refresh_data["refresh_token"],
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_SECONDS,
        "user": _to_user_public(user),
    }


@router.post("/api/auth/google")
def authenticate_google_user(payload: GoogleAuthPayload, request: Request):
    """Authentifie l'utilisateur via Google GIS (ID Token JWT vérifié cryptographiquement).

    Associe automatiquement le compte Google au profil utilisateur et génère un access token court
    ainsi qu'un refresh token révocable.
    """
    if not payload.credential or not payload.credential.strip():
        raise HTTPException(
            status_code=401,
            detail="ID Token Google (credential) requis pour l'authentification.",
        )

    db = get_db()
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
        auth_method=user_info.get("auth_method", "google_gis_jwt")
    )
    user_id = session.get("user_id")
    user_uuid = session.get("uuid")
    if not user_id or not user_uuid:
        raise HTTPException(status_code=500, detail="Impossible d'initialiser la session utilisateur Google")

    user_profile = db.get_user_profile(user_id=user_id)

    # Générer le token JWT Bearer court + refresh token révocable
    access_token = create_access_token(user_id, user_uuid, user_info["email"], user_info["name"])
    refresh_data = db.create_refresh_token(
        user_id=user_id,
        user_agent=request.headers.get("user-agent"),
    )

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
        "refresh_token": refresh_data["refresh_token"],
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_SECONDS,
        "session": session,
        "profile": user_profile
    }


@router.post("/api/auth/refresh", dependencies=[Depends(rate_limit_refresh)])
def refresh_access_token(payload: RefreshTokenRequest, request: Request):
    """Échange un refresh token valide contre un nouvel access token court et un nouveau refresh token (rotation)."""
    db = get_db()
    rotated = db.rotate_refresh_token(
        raw_token=payload.refresh_token,
        user_agent=request.headers.get("user-agent"),
    )
    if not rotated:
        raise HTTPException(
            status_code=401,
            detail="Refresh token invalide, expiré ou révoqué",
        )

    user = rotated["user"]
    new_access_token = create_access_token(
        user["id"],
        user["uuid"],
        user["email"],
        user.get("name"),
    )
    return {
        "status": "success",
        "access_token": new_access_token,
        "refresh_token": rotated["refresh_token"],
        "token_type": "bearer",
        "expires_in": JWT_EXPIRE_SECONDS,
        "user": _to_user_public(user),
    }


@router.get("/api/auth/me")
def get_current_google_session(current_user: AuthUser = Depends(get_current_user)):
    """Retourne la session active, le jeton JWT et le profil associé."""
    db = get_db()
    session = db.get_google_session(email=current_user.email)
    profile = db.get_user_profile(user_id=current_user.id)
    token = create_access_token(current_user.id, current_user.uuid, current_user.email, current_user.name)
    return {
        "session": session,
        "profile": profile,
        "current_user": current_user.model_dump(),
        "access_token": token,
        "expires_in": JWT_EXPIRE_SECONDS,
    }


@router.post("/api/auth/logout")
def logout_google_session(
    payload: Optional[LogoutRequest] = Body(default=None),
    current_user: AuthUser = Depends(get_current_user),
):
    """Déconnecte l'utilisateur authentifié et révoque ses refresh tokens."""
    db = get_db()
    revoked_count = 0

    if payload and payload.refresh_token and not payload.revoke_all:
        if db.revoke_refresh_token(payload.refresh_token, user_id=current_user.id):
            revoked_count = 1
    else:
        revoked_count = db.revoke_all_user_refresh_tokens(user_id=current_user.id)

    res = db.logout_google_user(email=current_user.email)
    res["revoked_tokens"] = revoked_count
    return res
