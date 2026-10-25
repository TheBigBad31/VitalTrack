"""FastAPI Backend pour VitalTrack (Local \u0026 Vercel Serverless).

Endpoints :
- GET  /api/health            : statut de l'API
- GET  /api/dashboard         : données globales agrégées (30 jours, 5 vues)
- GET  /api/weights           : liste des pesées (historique + tendance 7j)
- POST /api/weights           : saisie rapide de pesée (kg, composition corporelle)
- GET  /api/activities        : liste des résumés d'activité
- POST /api/activities        : ajout / synchronisation d'exercice ou pas
- GET  /api/meals             : historique des repas
- POST /api/meals             : enregistrement d'un repas dans le journal
- POST /api/meals/estimate    : estimation calorique par photo ou description avec curseur portion
- GET  /api/devices           : statut et synchronisation des objets connectés (Withings, Garmin, Oura, etc.)
- POST /api/devices/sync      : déclenchement d'une synchronisation d'un appareil
- GET  /api/fallback-data     : jeu de données complet 30 jours embarqué
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional, Union
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.db import Database, get_db_path
from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, MealType, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.nutrition_engine import NutritionEngine
from src.nutrition_rules import evaluate_dish_benefits
import yaml
from src.vision_nutrition import PhotoCalorieEstimator
from src.connectors.registry import DeviceConnectorRegistry
from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.connectors.ringconn import RingConnConnector
from src.connectors.webhook import MobileHealthWebhookConnector
from src.deps import get_current_user, get_strict_user  # noqa: F401  (ré-exports de compatibilité)

# Initialisation de FastAPI
app = FastAPI(
    title="VitalTrack API",
    description="API REST pour VitalTrack : PWA Mobile-First, Nutrition Photo IA et Objets Connectés",
    version="1.1.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json"
)

# CORS permissif pour le support PWA et requêtes locales / Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def vercel_path_resolver_middleware(request: Request, call_next):
    """Résout et normalise les chemins Serverless sous Vercel (rewrites ?__path=...)."""
    path_param = request.query_params.get("__path")
    if path_param is not None:
        subpath = path_param.lstrip("/")
        request.scope["path"] = f"/api/{subpath}" if subpath else "/api"
    elif request.scope.get("path") in ("/api/index.py", "/api/index", "/api"):
        matched = request.headers.get("x-matched-path", "")
        if matched and matched not in ("/api/index.py", "/api/index", "/api"):
            request.scope["path"] = matched
        else:
            request.scope["path"] = "/api/health"
    elif not request.scope.get("path", "").startswith("/api") and not request.scope.get("path", "").startswith("/static") and request.scope.get("path") not in ("/", "/docs", "/openapi.json"):
        request.scope["path"] = f"/api{request.scope.get('path')}"

    return await call_next(request)


# Instances partagées
db = Database()
nutrition_engine = NutritionEngine(db=db)
calorie_estimator = PhotoCalorieEstimator()

# Initialisation du registre IoT
device_registry = DeviceConnectorRegistry()
device_registry.register(RingConnConnector(), device_id="ringconn", name="RingConn Smart Ring (Gen 1 / Gen 2 / Gen 3)", device_type="ring")
device_registry.register(MobileHealthWebhookConnector(), device_id="health_connect", name="Google Health Connect (Google Health / Android)", device_type="mobile_aggregator")
device_registry.register(WithingsScaleConnector(), device_id="withings", name="Withings Body Scan & Scales", device_type="scale")
device_registry.register(OuraRingConnector(), device_id="oura", name="Oura Ring Gen3", device_type="ring")
device_registry.register(MobileHealthWebhookConnector(), device_id="apple_health", name="Apple Santé (HealthKit)", device_type="mobile_aggregator")



# =====================================================================
# Routeurs FastAPI (voir src/routers/)
# =====================================================================

from src.routers import auth as auth_router, catalog, dashboard, devices, meals, webhooks, weights  # noqa: E402

for _router_module in (dashboard, weights, meals, catalog, devices, auth_router, webhooks):
    app.include_router(_router_module.router)

# =====================================================================

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_index():
    """Sert l'application PWA index.html."""
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_file):
        return FileResponse(index_file, media_type="text/html")
    root_index = os.path.join(os.path.dirname(__file__), "..", "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index, media_type="text/html")
    return {"message": "VitalTrack PWA - interface en cours d'initialisation"}
