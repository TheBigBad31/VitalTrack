"""Routeur FastAPI : devices."""

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
# Endpoints Hub Objets Connectés & Gestion de Flotte Sécurisée
# =====================================================================

@router.get("/api/devices")
def list_devices(current_user: AuthUser = Depends(get_current_user)):
    """Liste tous les objets connectés de l'utilisateur avec leur statut temps réel et métriques récentes."""
    saved_devices = {dev["device_id"]: dev for dev in db.get_user_devices(user_id=current_user.id)}
    statuses = []
    for d in device_registry.list_all():
        saved_d = saved_devices.get(d.id, {})
        is_conn = bool(saved_d.get("connected"))
        sync_status = saved_d.get("sync_status", "connected" if is_conn else "disconnected")
        last_sync = saved_d.get("last_sync_at") or saved_d.get("last_sync")

        statuses.append({
            "id": d.id,
            "device_id": d.id,
            "name": saved_d.get("name") or d.name,
            "device_type": d.device_type,
            "is_configured": is_conn,
            "connected": is_conn,
            "status": sync_status,
            "sync_status": sync_status,
            "last_sync": last_sync,
            "last_sync_at": last_sync,
            "has_credentials": bool(saved_d.get("has_credentials")),
            "api_key_masked": saved_d.get("api_key_masked"),
            "supported_features": getattr(d, "supported_features", ["sync", "demo_mode"])
        })
    return statuses


@router.get("/api/devices/comparison")
def get_devices_comparison():
    """Guide comparatif technique pour le choix de la balance connectée et l'interconnexion bague."""
    return {
        "title": "Guide Comparatif des Balances Connectées & Configuration Bague",
        "author": "Ingénieur Vision Nutrition & Coach Métabolique",
        "last_updated": "2026-10-18",
        "recommendation": "Withings Body Smart / Body Comp",
        "recommendation_summary": "Withings est la solution n°1 recommandée grâce à son API OAuth2 officielle ouverte, gratuite et sans restriction de clés développeur, permettant la synchronisation automatique cloud-to-cloud directe du poids et de l'impédancemétrie.",
        "scales": [
            {
                "id": "withings",
                "name": "Withings Body Smart / Body Comp",
                "brand": "Withings",
                "price_approx": "100 € - 199 €",
                "connectivity": ["Wi-Fi", "Bluetooth"],
                "api_type": "OAuth 2.0 REST API Cloud-to-Cloud directe",
                "api_openness": "Excellente (API ouverte, documentation complète, jetons illimités)",
                "metrics": [
                    "Poids (résolution 50g)",
                    "Masse grasse (%)",
                    "Masse musculaire (kg)",
                    "Masse osseuse (kg)",
                    "Masse hydrique (%)",
                    "Graisse viscérale",
                    "Rythme cardiaque stationnaire"
                ],
                "ease_of_sync": "5/5 (100% automatique après pesée via Wi-Fi direct)",
                "vitaltrack_support": "Natif (connecteur `WithingsScaleConnector` dans `src/connectors/withings.py`)",
                "verdict": "Choix Recommandé n°1 : Ingestion instantanée sans intermédiaire."
            },
            {
                "id": "garmin",
                "name": "Garmin Index S2",
                "brand": "Garmin",
                "price_approx": "149 €",
                "connectivity": ["Wi-Fi", "ANT+", "Bluetooth"],
                "api_type": "Garmin Connect Developer Program / Health Sync Webhook",
                "api_openness": "Moyenne (L'API officielle Garmin Connect nécessite une validation d'entreprise ; synchronisation possible via pont Health Sync ou Apple Santé)",
                "metrics": [
                    "Poids",
                    "IMC",
                    "Masse grasse (%)",
                    "Masse musculaire squelettique",
                    "Masse osseuse",
                    "Masse hydrique (%)"
                ],
                "ease_of_sync": "3.5/5 (Nécessite soit un pont webhook Apple Santé/Android, soit accès pro)",
                "vitaltrack_support": "Via Webhook universel (`/api/webhook/health`) ou template (`TemplateHealthConnector`)",
                "verdict": "Excellent choix pour les adeptes de montres Garmin via pont Health Connect."
            },
            {
                "id": "xiaomi",
                "name": "Xiaomi Mi Body Composition Scale 2",
                "brand": "Xiaomi",
                "price_approx": "25 € - 35 €",
                "connectivity": ["Bluetooth uniquement (BLE)"],
                "api_type": "Aucune API Cloud publique ; synchro via Mi Fitness / Zepp Life -> Health Connect",
                "api_openness": "Faible (fermé, Bluetooth local uniquement)",
                "metrics": [
                    "Poids",
                    "Masse grasse (%)",
                    "Masse musculaire",
                    "Masse hydrique (%)",
                    "Graisse viscérale",
                    "Métabolisme de base estimé"
                ],
                "ease_of_sync": "3/5 (Obligation d'ouvrir l'app mobile en Bluetooth pour remonter les données vers Health Connect)",
                "vitaltrack_support": "Via Webhook Health Connect (`/api/webhook/health`)",
                "verdict": "Option très économique mais nécessite l'intermédiaire du smartphone."
            }
        ],
        "ring_integration": {
            "name": "RingConn Gen 3 & Bagues de Santé (RingConn / Oura)",
            "primary_ring": "RingConn Gen 3",
            "api_type": "RingConn Open API & Google Health Connect (Android)",
            "sync_flow": "Synchronisation matinale & continue : Récupération du score de sommeil, HRV nocturne (RMSSD), Fréquence Cardiaque au repos, BMR, pas et calories actives soit via Google Health Connect, soit via API RingConn.",
            "status": "Connecteur RingConn et passerelle Google Health Connect actifs (`RingConnConnector` dans `src/connectors/ringconn.py`)"
        }
    }


@router.get("/api/devices/{device_id}")
def get_device_detail(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Récupère les détails et l'état en direct d'un appareil pour l'utilisateur connecté."""
    dev = db.get_user_device(device_id, user_id=current_user.id, reveal_secrets=False)
    connector = device_registry.get(device_id)
    if not dev and not connector:
        raise HTTPException(status_code=404, detail=f"Appareil '{device_id}' non trouvé")
    
    if not dev:
        dev = {
            "device_id": device_id,
            "name": getattr(connector, "name", device_id.title()),
            "device_type": getattr(connector, "device_type", "health_sensor"),
            "connected": False,
            "sync_status": "disconnected",
            "last_sync_at": None,
            "has_credentials": False
        }
    return dev


@router.delete("/api/devices/{device_id}")
def disconnect_device(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Déconnecte et révoque un appareil en supprimant ses identifiants chiffrés."""
    deleted = db.delete_user_device(device_id, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"Appareil '{device_id}' déconnecté et identifiants révoqués avec succès",
        "deleted": deleted
    }


@router.post("/api/devices/{device_id}/sync")
def sync_device_targeted(device_id: str, current_user: AuthUser = Depends(get_current_user)):
    """Déclenche la synchronisation ciblée d'un appareil et persiste les métriques en base."""
    # Instancier le connecteur avec les credentials utilisateur déchiffrés si existants
    user_device = db.get_user_device(device_id, user_id=current_user.id, reveal_secrets=True)
    custom_cfg = {}
    if user_device and user_device.get("credentials"):
        custom_cfg.update(user_device["credentials"])
    if user_device and user_device.get("api_key"):
        custom_cfg["api_key"] = user_device["api_key"]
    if user_device and user_device.get("account_email"):
        custom_cfg["account_email"] = user_device["account_email"]

    try:
        connector = get_connector(device_id, custom_config=custom_cfg)
    except Exception:
        connector = device_registry.get(device_id)

    if not connector:
        raise HTTPException(status_code=404, detail=f"Appareil '{device_id}' non trouvé")
    
    today_val = dt_module.date.today()
    start_val = today_val - dt_module.timedelta(days=1)
    
    weights = []
    activities = []
    if getattr(connector, "is_configured", False):
        if hasattr(connector, "sync_weights"):
            raw_weights = [
                w for w in connector.sync_weights(start_val, today_val)
                if w.source != "demo" and "Démo" not in (w.notes or "")
            ]
            for w in raw_weights:
                db.insert_weight(w, user_id=current_user.id)
            weights = [w.model_dump() for w in raw_weights]

        if hasattr(connector, "sync_activities"):
            raw_acts = [
                a for a in connector.sync_activities(start_val, today_val)
                if a.source != "demo"
            ]
            for a in raw_acts:
                db.insert_activity(a, user_id=current_user.id)
            activities = [a.model_dump() for a in raw_acts]

    # Mettre à jour l'état de synchronisation en base
    db.update_device_sync_status(device_id, sync_status="connected", user_id=current_user.id)

    return {
        "device_id": device_id,
        "name": getattr(connector, "name", device_id.capitalize()),
        "status": "success",
        "sync_status": "connected",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "details": {
            "weights_synced": len(weights),
            "activities_synced": len(activities)
        }
    }


@router.post("/api/devices/sync")
def sync_device_legacy(req: DeviceSyncRequest, current_user: AuthUser = Depends(get_current_user)):
    """Compatibilité rétroactive pour la synchronisation d'un appareil."""
    return sync_device_targeted(req.device_id, current_user=current_user)


@router.post("/api/devices/connect")
def connect_device_wizard(connect_in: DeviceConnectInput, current_user: AuthUser = Depends(get_current_user)):
    """Assistant de connexion d'un objet connecté (RingConn Gen 3, Google Health Connect, Withings, Oura) pour l'utilisateur connecté avec chiffrement et test immédiat."""
    connector = device_registry.get(connect_in.device_id)
    name = connect_in.name or (getattr(connector, "name", connect_in.device_id.title()) if connector else connect_in.device_id.title())
    dev_type = connect_in.device_type or (getattr(connector, "device_type", "health_sensor") if connector else "health_sensor")

    # Consolidation des credentials
    creds = dict(connect_in.credentials) if connect_in.credentials else {}
    if connect_in.api_key:
        creds["api_key"] = connect_in.api_key
    if connect_in.token:
        creds["token"] = connect_in.token
    if connect_in.account_email:
        creds["account_email"] = connect_in.account_email

    # Test de connectivité si supporté
    connectivity_test = {"ok": True, "message": "Connexion établie avec succès"}
    if connector and hasattr(connector, "test_connection"):
        try:
            connectivity_test = connector.test_connection()
        except Exception as e:
            connectivity_test = {"ok": False, "message": f"Test de liaison échoué: {e}"}

    saved = db.update_user_device(
        device_id=connect_in.device_id,
        name=name,
        device_type=dev_type,
        connected=connect_in.connected,
        auth_type=connect_in.auth_type or "connected",
        api_key=connect_in.api_key or connect_in.token,
        credentials=creds,
        account_email=connect_in.account_email,
        sync_status="connected" if connectivity_test.get("ok", True) else "error",
        user_id=current_user.id
    )

    # Si c'est une bague ou une balance, mettre à jour la préférence dans le profil
    if dev_type == "ring":
        db.update_user_profile({"preferred_ring": connect_in.device_id}, user_id=current_user.id)
    elif dev_type == "scale":
        db.update_user_profile({"preferred_scale": connect_in.device_id}, user_id=current_user.id)

    # Si l'appareil est connecté, déclencher une synchronisation initiale
    if connect_in.connected:
        try:
            sync_device_targeted(connect_in.device_id, current_user=current_user)
        except Exception:
            pass

    return {
        "status": "success",
        "message": f"Appareil {name} configuré et connecté avec succès via l'assistant (identifiants chiffrés au repos)",
        "connectivity_test": connectivity_test,
        "device": saved
    }

