"""Module d'authentification et de gestion des identités pour VitalTrack.

Prend en charge :
- Génération et validation de jetons JWT sécurisés (HS256) avec expiration
- Hashage et vérification de mots de passe (SHA256 avec sel aléatoire)
- Décodage des identités Google GIS (ID Token JWT ou connexion directe)
- Dépendance FastAPI pour extraction d'utilisateur connecté (JWT Bearer) ou compte par défaut
"""

import base64
import hashlib
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import jwt
from pydantic import BaseModel, Field

JWT_SECRET = os.getenv("JWT_SECRET", "vitaltrack-insecure-secret-key-change-in-prod-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", str(30 * 24 * 3600)))  # 30 jours par défaut

DEFAULT_GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
    "https://www.googleapis.com/auth/fitness.sleep.read"
]


class GoogleAuthPayload(BaseModel):
    """Payload envoyé par le client PWA lors de la connexion Google."""
    credential: Optional[str] = Field(None, description="Google GIS ID Token (JWT) ou Token OAuth")
    email: Optional[str] = Field(None, description="Email du compte Google")
    name: Optional[str] = Field(None, description="Nom complet de l'utilisateur")
    picture: Optional[str] = Field(None, description="URL de la photo de profil Google")
    sub: Optional[str] = Field(None, description="Google Subject Unique Identifier (sub)")


class GoogleConfigUpdate(BaseModel):
    """Mise à jour du Google Client ID depuis l'interface."""
    google_client_id: str


class LoginRequest(BaseModel):
    """Requête de connexion standard par email/mot de passe."""
    email: str
    password: str


class RegisterRequest(BaseModel):
    """Requête d'inscription standard par email/mot de passe."""
    email: str
    password: str
    name: Optional[str] = None


class AuthUser(BaseModel):
    """Utilisateur authentifié injecté dans les dépendances FastAPI."""
    id: int
    uuid: str
    email: str
    name: Optional[str] = None
    picture: Optional[str] = None
    auth_provider: str = "google"
    google_sub: Optional[str] = None


def hash_password(password: str) -> str:
    """Génère un sel aléatoire et calcule un hash PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${pwd_hash.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe en clair contre un hash stocké."""
    if not hashed_password or "$" not in hashed_password:
        return False
    try:
        salt, stored_hash = hashed_password.split("$", 1)
        calc_hash = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), 100_000)
        return secrets.compare_digest(calc_hash.hex(), stored_hash)
    except Exception:
        return False


def create_access_token(user_id: int, user_uuid: str, email: str, name: Optional[str] = None) -> str:
    """Génère un jeton JWT d'accès sécurisé."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "uuid": user_uuid,
        "email": email,
        "name": name or "",
        "iat": now,
        "exp": now + JWT_EXPIRE_SECONDS
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Décode et valide un jeton JWT avec signature."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def decode_jwt_unverified(token: str) -> Dict[str, Any]:
    """Décode la charge utile d'un JWT Google sans vérification externe de signature."""
    parts = token.split(".")
    if len(parts) < 2:
        raise ValueError("Format JWT invalide")
    payload_b64 = parts[1]
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    decoded_bytes = base64.urlsafe_b64decode(payload_b64)
    return json.loads(decoded_bytes.decode("utf-8"))


def parse_google_identity(payload: GoogleAuthPayload) -> Dict[str, Any]:
    """Extrait et normalise les informations de l'utilisateur Google à partir du token ou du payload."""
    if payload.credential:
        try:
            claims = decode_jwt_unverified(payload.credential)
            email = claims.get("email") or payload.email or "sebastienlamoliate@gmail.com"
            name = claims.get("name") or payload.name or "Sébastien LAMOLIATE"
            picture = claims.get("picture") or payload.picture or ""
            sub = claims.get("sub") or payload.sub or f"google_{hash(email)}"
            return {
                "email": email,
                "name": name,
                "picture": picture,
                "google_sub": str(sub),
                "is_authenticated": True,
                "auth_method": "google_gis_jwt"
            }
        except Exception:
            pass

    email = payload.email or "sebastienlamoliate@gmail.com"
    name = payload.name or "Sébastien LAMOLIATE"
    picture = payload.picture or "https://lh3.googleusercontent.com/a/default-user=s96-c"
    sub = payload.sub or f"google_sub_{abs(hash(email))}"

    return {
        "email": email,
        "name": name,
        "picture": picture,
        "google_sub": str(sub),
        "is_authenticated": True,
        "auth_method": "google_quick_signin"
    }
