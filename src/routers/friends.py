"""Router FastAPI pour la gestion des relations d'amitié et partage de données de santé (VitalTrack).

Prend en charge :
- POST /api/friends/request : Envoi d'une demande d'ami par email / pseudonyme
- GET /api/friends : Liste des amis acceptés, demandes reçues et demandes envoyées
- POST /api/friends/{request_id}/accept : Acceptation d'une demande reçue
- POST /api/friends/{request_id}/reject : Refus d'une demande reçue
- DELETE /api/friends/{friend_id} : Révocation d'une amitié ou annulation de demande
"""

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field

from src.auth import AuthUser, decode_access_token
from src.db import Database

logger = logging.getLogger("vitaltrack.friends")

router = APIRouter(prefix="/api/friends", tags=["friends"])

_db_instance: Optional[Database] = None


def get_db() -> Database:
    """Retourne l'instance singleton Database ou celle partagée par l'application."""
    global _db_instance
    try:
        import src.app as app_module
        if hasattr(app_module, "db") and app_module.db is not None:
            return app_module.db
    except ImportError:
        logger.debug("Module src.app non disponible lors de la résolution de la base de données", exc_info=True)
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance


def get_current_user(
    authorization: Optional[str] = Header(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token")
) -> AuthUser:
    """Délègue à l'authentification centralisée de l'application (src.app.get_current_user)."""
    import src.app as app_module
    return app_module.get_current_user(authorization=authorization, x_webhook_token=x_webhook_token)


class FriendRequestPayload(BaseModel):
    """Payload pour envoyer une demande d'ami."""
    identifier: Optional[str] = Field(None, description="Email ou pseudonyme de l'ami")
    email: Optional[str] = Field(None, description="Email direct de l'ami")
    permission: str = Field("read_only", description="Permission accordée (read_only)")


def verify_view_access(
    target_user_id: int,
    current_user: AuthUser,
    database: Optional[Database] = None
) -> Dict[str, Any]:
    """Vérifie si current_user a l'autorisation de consulter les données de target_user_id.

    Règles strictes de contrôle d'accès (RBAC / Read-Only Guard) :
    - Autorise si target_user_id == current_user.id (propriétaire)
    - Autorise si une relation d'amitié existe avec status == 'accepted' et permission == 'read_only'
    - Lève HTTPException(403, detail="Accès non autorisé aux données de cet utilisateur") sinon
    """
    if target_user_id == current_user.id:
        return {"authorized": True, "is_owner": True, "permission": "owner"}

    db_inst = database or get_db()
    friendship = db_inst.check_friendship_access(
        observer_id=current_user.id,
        target_user_id=target_user_id
    )

    if not friendship:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé aux données de cet utilisateur"
        )

    perm = friendship.get("permission", "read_only")
    if perm != "read_only" and perm != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès non autorisé aux données de cet utilisateur"
        )

    return {"authorized": True, "is_owner": False, "permission": perm, "friendship": friendship}


@router.post("/request")
def send_friend_request(
    payload: FriendRequestPayload,
    current_user: AuthUser = Depends(get_current_user)
):
    """Envoie une demande d'ami à un utilisateur par son email ou pseudonyme."""
    target_id_str = payload.email or payload.identifier
    if not target_id_str or not str(target_id_str).strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Veuillez spécifier l'adresse email ou le pseudonyme de l'ami à inviter"
        )

    db_inst = get_db()
    try:
        req = db_inst.create_friend_request(
            user_id=current_user.id,
            target_identifier=str(target_id_str).strip(),
            permission=payload.permission or "read_only"
        )
        return {
            "status": "success",
            "message": "Demande d'ami transmise avec succès",
            "friendship": req
        }
    except ValueError as e:
        msg = str(e)
        if "introuvable" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)


@router.get("")
@router.get("/")
def list_friends(
    current_user: AuthUser = Depends(get_current_user)
):
    """Retourne la liste des amis acceptés, des demandes reçues en attente et des demandes envoyées."""
    db_inst = get_db()
    data = db_inst.get_friendships(user_id=current_user.id)
    return {
        "status": "success",
        "friends": data["accepted"],
        "incoming_requests": data["incoming_pending"],
        "outgoing_requests": data["outgoing_pending"]
    }


@router.post("/{request_id}/accept")
def accept_friend(
    request_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Accepte une demande d'ami reçue."""
    db_inst = get_db()
    try:
        res = db_inst.accept_friend_request(request_id=request_id, user_id=current_user.id)
        return {
            "status": "success",
            "message": "Demande d'ami acceptée avec succès",
            "friendship": res
        }
    except ValueError as e:
        msg = str(e)
        if "introuvable" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)


@router.post("/{request_id}/reject")
def reject_friend(
    request_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Refuse une demande d'ami reçue."""
    db_inst = get_db()
    try:
        res = db_inst.reject_friend_request(request_id=request_id, user_id=current_user.id)
        return {
            "status": "success",
            "message": "Demande d'ami refusée",
            "friendship": res
        }
    except ValueError as e:
        msg = str(e)
        if "introuvable" in msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)


@router.delete("/{friend_id}")
def delete_or_revoke_friend(
    friend_id: int,
    current_user: AuthUser = Depends(get_current_user)
):
    """Révoque une relation d'amitié existante ou annule une demande d'ami."""
    db_inst = get_db()
    deleted = db_inst.delete_friendship(target_id=friend_id, user_id=current_user.id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relation d'amitié ou demande introuvable"
        )
    return {
        "status": "success",
        "message": "Relation d'amitié révoquée avec succès",
        "deleted": True
    }
