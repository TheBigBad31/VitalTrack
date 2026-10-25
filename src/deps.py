"""Dépendances partagées (instances et authentification) pour les routeurs VitalTrack.

Les instances (`db`, `nutrition_engine`, ...) sont portées par le module `src.app`.
Les routeurs y accèdent via ces proxies résolus à chaque appel, de sorte que
`src.app.db = ...` (utilisé par les tests pour isoler la base) reste pris en compte
par tous les routeurs.
"""

import sys
from typing import Optional

from fastapi import Header, HTTPException

from src.auth import AuthUser, decode_access_token


class _AppAttr:
    """Proxy paresseux vers un attribut de `src.app` (résolu à chaque accès)."""

    def __init__(self, name: str):
        object.__setattr__(self, "_name", name)

    def _target(self):
        return getattr(sys.modules["src.app"], object.__getattribute__(self, "_name"))

    def __getattr__(self, attr):
        return getattr(self._target(), attr)

    def __setattr__(self, attr, value):
        setattr(self._target(), attr, value)


db = _AppAttr("db")
nutrition_engine = _AppAttr("nutrition_engine")
calorie_estimator = _AppAttr("calorie_estimator")
device_registry = _AppAttr("device_registry")


def _to_auth_user(user_data: dict) -> AuthUser:
    return AuthUser(
        id=user_data["id"],
        uuid=user_data["uuid"],
        email=user_data["email"],
        name=user_data.get("name"),
        picture=user_data.get("picture"),
        auth_provider=user_data.get("auth_provider", "google"),
        google_sub=user_data.get("google_sub")
    )


def get_current_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Extrait et valide l'utilisateur authentifié depuis le jeton JWT Bearer.

    Supporte également le compte démo/principal par défaut si aucun header n'est fourni,
    permettant l'accès direct et la rétrocompatibilité tout en isolant par user_id.
    """
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split("Bearer ", 1)[1].strip()
        payload = decode_access_token(token)
        if payload and "user_id" in payload:
            user_data = db.get_user_by_id(int(payload["user_id"]))
            if user_data:
                return _to_auth_user(user_data)

    # Vérifier si une session Google active existe en base
    sess = db.get_google_session()
    if sess.get("is_authenticated") and sess.get("user_id"):
        user_data = db.get_user_by_id(int(sess["user_id"]))
        if user_data:
            return _to_auth_user(user_data)

    # Utilisateur par défaut (Sébastien LAMOLIATE, user_id=1)
    default_user = db._ensure_default_user()
    return _to_auth_user(default_user)


def get_strict_user(authorization: Optional[str] = Header(None)) -> AuthUser:
    """Dépendance stricte exigeant un jeton Bearer JWT valide."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Jeton d'authentification Bearer manquant ou invalide")
    token = authorization.split("Bearer ", 1)[1].strip()
    payload = decode_access_token(token)
    if not payload or "user_id" not in payload:
        raise HTTPException(status_code=401, detail="Jeton JWT expiré ou signature invalide")
    user_data = db.get_user_by_id(int(payload["user_id"]))
    if not user_data:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return _to_auth_user(user_data)
