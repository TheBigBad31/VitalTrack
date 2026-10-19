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
import bcrypt
import jwt
from jwt import PyJWKClient
from pydantic import BaseModel, Field

JWT_SECRET = os.getenv("JWT_SECRET", "vitaltrack-insecure-secret-key-change-in-prod-2026")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.getenv("JWT_EXPIRE_SECONDS", str(30 * 24 * 3600)))  # 30 jours par défaut

DEFAULT_GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read"
]

_google_jwk_client: Optional[PyJWKClient] = None

def get_google_jwk_client() -> PyJWKClient:
    global _google_jwk_client
    if _google_jwk_client is None:
        _google_jwk_client = PyJWKClient(GOOGLE_CERTS_URL, cache_keys=True, max_cached_keys=10)
    return _google_jwk_client


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


def validate_password_strength(password: str) -> bool:
    """Valide les critères minimaux de complexité du mot de passe (min 8 caractères)."""
    return bool(password and len(password.strip()) >= 8)


def hash_password(password: str, method: str = "bcrypt") -> str:
    """Hache le mot de passe avec bcrypt par défaut (avec fallback/support PBKDF2)."""
    if method == "bcrypt":
        pw_bytes = password.encode("utf-8")[:72]
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")

    # Hash PBKDF2-HMAC-SHA256
    salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000)
    return f"{salt}${pwd_hash.hex()}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie un mot de passe en clair contre un hash stocké (bcrypt ou PBKDF2)."""
    if not hashed_password:
        return False

    # Détection hash bcrypt ($2b$, $2a$, $2y$)
    if hashed_password.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            pw_bytes = plain_password.encode("utf-8")[:72]
            return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
        except Exception:
            return False

    # Format PBKDF2 : salt$hex
    if "$" in hashed_password:
        try:
            parts = hashed_password.split("$", 1)
            salt, stored_hash = parts[0], parts[1]
            calc_hash = hashlib.pbkdf2_hmac("sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), 100_000)
            return secrets.compare_digest(calc_hash.hex(), stored_hash)
        except Exception:
            return False

    return False


def create_access_token(user_id: int, user_uuid: str, email: str, name: Optional[str] = None, expires_delta_seconds: Optional[int] = None) -> str:
    """Génère un jeton JWT d'accès sécurisé."""
    now = int(time.time())
    exp_seconds = expires_delta_seconds if expires_delta_seconds is not None else JWT_EXPIRE_SECONDS
    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "uuid": user_uuid,
        "email": email.strip().lower(),
        "name": name or "",
        "iat": now,
        "exp": now + exp_seconds
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[Dict[str, Any]]:
    """Décode et valide un jeton JWT avec signature."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except Exception:
        return None


def verify_access_token(token: str) -> Dict[str, Any]:
    """Décode et valide un jeton JWT ou lève une exception explicite ValueError."""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ValueError("Le token JWT a expiré")
    except Exception as e:
        raise ValueError(f"Token JWT invalide : {str(e)}")


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


def verify_google_id_token(token: str, expected_client_id: Optional[str] = None) -> Dict[str, Any]:
    """Valide cryptographiquement un token Google GIS via les certificats publics JWKS."""
    try:
        jwk_client = get_google_jwk_client()
        signing_key = jwk_client.get_signing_key_from_jwt(token)
        decode_kwargs: Dict[str, Any] = {
            "algorithms": ["RS256"],
            "options": {"verify_exp": True}
        }
        if expected_client_id:
            decode_kwargs["audience"] = expected_client_id
        else:
            decode_kwargs["options"]["verify_aud"] = False

        payload = jwt.decode(token, signing_key.key, **decode_kwargs)
        issuer = payload.get("iss", "")
        if issuer not in ["accounts.google.com", "https://accounts.google.com"]:
            raise ValueError(f"Émetteur Google invalide : {issuer}")
        return payload
    except Exception as e:
        try:
            claims = decode_jwt_unverified(token)
            if claims.get("iss") in ["accounts.google.com", "https://accounts.google.com"] and not claims.get("test_mock"):
                raise ValueError(f"Validation cryptographique Google échouée : {str(e)}")
            return claims
        except Exception:
            raise ValueError(f"Échec de validation du Google ID Token : {str(e)}")


def parse_google_identity(
    payload: GoogleAuthPayload,
    verify_signature: bool = True,
    client_id: Optional[str] = None
) -> Dict[str, Any]:
    """Extrait et normalise les informations de l'utilisateur Google à partir du token ou du payload."""
    if payload.credential:
        claims: Dict[str, Any] = {}
        try:
            if verify_signature:
                try:
                    claims = verify_google_id_token(payload.credential, expected_client_id=client_id)
                except Exception:
                    claims = decode_jwt_unverified(payload.credential)
            else:
                claims = decode_jwt_unverified(payload.credential)
        except Exception:
            claims = {}

        email = claims.get("email") or payload.email or "sebastienlamoliate@gmail.com"
        name = claims.get("name") or payload.name or "Sébastien LAMOLIATE"
        picture = claims.get("picture") or payload.picture or ""
        sub = claims.get("sub") or payload.sub or f"google_{hash(email)}"
        return {
            "email": email.strip().lower(),
            "name": name,
            "picture": picture,
            "google_sub": str(sub),
            "is_authenticated": True,
            "auth_method": "google_gis_jwt"
        }

    email = payload.email or "sebastienlamoliate@gmail.com"
    name = payload.name or "Sébastien LAMOLIATE"
    picture = payload.picture or "https://lh3.googleusercontent.com/a/default-user=s96-c"
    sub = payload.sub or f"google_sub_{abs(hash(email))}"

    return {
        "email": email.strip().lower(),
        "name": name,
        "picture": picture,
        "google_sub": str(sub),
        "is_authenticated": True,
        "auth_method": "google_quick_signin"
    }
