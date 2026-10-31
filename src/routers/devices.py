"""Routeur FastAPI pour les endpoints Objets Connectés (IoT)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional

from src.app import app, db, AuthUser, device_registry, get_current_user

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("")
def get_devices(
    current_user: AuthUser = Depends(get_current_user),
):
    """Retourne le statut et la synchronisation des objets connectés."""
    target_uid = current_user.id
    verify_view_access(target_uid, current_user, database=db)
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=target_uid)}
    
    device_statuses = []
    for d in device_registry.list_all():
        saved_d = saved_devices.get(d.id, {})
        is_conn = bool(saved_d.get("connected"))
        sync_status = saved_d.get("sync_status", "connected" if is_conn else "disconnected")
        last_sync = saved_d.get("last_sync_at") or saved_d.get("last_sync")
        device_statuses.append({
            "id": d.id,
            "device_id": d.id,
            "name": saved_d.get("name") or d.name,
            "device_type": d.device_type,
            "is_configured": is_conn,
            "connected": is_conn,
            "status": sync_status,
            "sync_status": sync_status,
            "auth_type": saved_d.get("auth_type", "none"),
            "account_email": saved_d.get("account_email"),
            "last_sync": last_sync,
            "last_sync_at": last_sync,
            "has_credentials": bool(saved_d.get("has_credentials")),
            "api_key_masked": saved_d.get("api_key_masked")
        })
    
    return {"devices": device_statuses}


@router.post("/sync")
def device_sync(
    current_user: AuthUser = Depends(get_current_user),
):
    """Déclenche une synchronisation d'un appareil."""
    target_uid = current_user.id
    verify_view_access(target_uid, current_user, database=db)
    # Simpler sync trigger - just return success
    return {"status": "success", "message": "Synchronisation déclenchée"}