"""Routeur FastAPI : webhooks."""

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
# Endpoints Webhooks Universels (Health Connect, RingConn, Apple Santé)
# =====================================================================

@router.post("/api/webhook/health")
@router.post("/api/webhooks/health-connect")
@router.post("/api/webhooks/ringconn")
def handle_health_webhook(payload: Dict[str, Any], token: Optional[str] = Query(None)):
    """Point d'entrée universel pour les webhooks mobiles ou automatisations (Tasker, Raccourcis, RingConn)."""
    connector = MobileHealthWebhookConnector()
    if token and not connector.authenticate_request(token):
        raise HTTPException(status_code=401, detail="Token webhook invalide")

    weight_entry, act_entry = connector.process_webhook_payload(payload)
    saved_weight = None
    saved_act = None
    # Webhook sans contexte utilisateur : cible explicitement le compte principal (user_id obligatoire)
    user_id = db._ensure_default_user()["id"]

    if weight_entry:
        saved_weight = db.insert_weight(weight_entry, user_id=user_id).model_dump()
    if act_entry:
        saved_act = db.insert_activity(act_entry, user_id=user_id).model_dump()

    # Mettre à jour l'état de l'appareil associé
    source_name = payload.get("source", "health_connect")
    dev_id = "ringconn" if "ring" in source_name.lower() else ("withings" if "withings" in source_name.lower() else "health_connect")
    db.update_user_device(
        user_id=user_id,
        device_id=dev_id,
        name=dev_id.replace("_", " ").title(),
        device_type="ring" if dev_id == "ringconn" else ("scale" if dev_id == "withings" else "mobile_aggregator"),
        connected=True,
        auth_type="webhook"
    )

    return {
        "status": "success",
        "message": "Données de santé webhook ingérées avec succès",
        "ingested": {
            "weight": saved_weight,
            "activity": saved_act
        }
    }

