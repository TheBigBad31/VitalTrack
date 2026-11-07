"""Router FastAPI pour les endpoints de sauvegarde, restauration, RGPD, configuration et système (VitalTrack).

Endpoints :
- GET    /api/backup/export     : export RGPD complet (JSON)
- GET    /api/export/json       : alias export JSON
- GET    /api/export/csv        : export CSV des données biométriques
- POST   /api/backup/import     : restauration depuis un export JSON
- DELETE /api/user/data         : purge des données de santé (compte conservé)
- DELETE /api/user/account      : suppression définitive du compte (RGPD)
- GET    /api/user/consents     : préférences de consentement RGPD
- POST   /api/user/consents     : mise à jour d'un consentement
- GET    /api/goals/presets     : profils métaboliques prédéfinis 1-clic
- GET    /api/config            : source de vérité backend (constantes, cibles)
- GET    /api/downloads/android-bridge : téléchargement direct APK Android Health Bridge
"""

import csv
import io
import logging
import os
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

import src.app as app_module
from src.auth import AuthUser
from src.db import Database


logger = logging.getLogger("vitaltrack.observability")

router = APIRouter(tags=["system"])

GOALS_CONFIG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "config", "goals_presets.yaml")

# Constante de conversion poids <-> énergie (source de vérité backend).
# 1 kg de masse grasse correspond approximativement à 7700 kcal.
KCAL_PER_KG = 7700.0

DEFAULT_GOALS_PRESETS = {
    "default_profile": "weight_loss",
    "profiles": {
        "weight_loss": {
            "id": "weight_loss",
            "title": "🔥 Perte de Poids Durable (-0,5 kg/sem)",
            "short_title": "Perte de Poids",
            "badge": "-0,5 kg/sem",
            "calorie_target_delta": -500,
            "target_steps": 10000,
            "protein_per_kg": 1.8,
            "carb_ratio": 0.40,
            "fat_ratio": 0.30,
            "protein_ratio": 0.30,
            "description": "Déficit calorique régulier de 500 kcal/j pour cibler -0,5 kg/semaine avec apport protéiné élevé (1,8 g/kg) afin de préserver la masse musculaire et 10 000 pas quotidiens.",
            "focus": "Masse grasse & conservation musculaire",
            "recommended_cardio_min_week": 150,
        },
        "maintenance": {
            "id": "maintenance",
            "title": "⚖️ Maintien & Équilibre Vitalité",
            "short_title": "Maintien Vitalité",
            "badge": "Équilibre 0 kcal",
            "calorie_target_delta": 0,
            "target_steps": 8500,
            "protein_per_kg": 1.4,
            "carb_ratio": 0.45,
            "fat_ratio": 0.30,
            "protein_ratio": 0.25,
            "description": "Équilibre calorique total (Déficit 0 kcal), répartition optimale P/G/L pour maximiser l'énergie au quotidien et 8 500 pas/j.",
            "focus": "Stabilité métabolique, niveau d'énergie & longévité",
            "recommended_cardio_min_week": 120,
        },
        "recomposition": {
            "id": "recomposition",
            "title": "💪 Recomposition Corporelle & Sport",
            "short_title": "Recomposition & Sport",
            "badge": "-200 kcal & P+ 2.2g/kg",
            "calorie_target_delta": -200,
            "target_steps": 10000,
            "protein_per_kg": 2.2,
            "carb_ratio": 0.35,
            "fat_ratio": 0.25,
            "protein_ratio": 0.40,
            "description": "Léger déficit de 200 kcal/j combiné à un apport protéiné très élevé (2,2 g/kg) pour stimuler la synthèse musculaire tout en réduisant l'adiposité viscérale.",
            "focus": "Masse musculaire, force & calories actives d'entraînement",
            "recommended_cardio_min_week": 180,
        },
    },
}

GITHUB_LATEST_RELEASE_APK_URL = "https://github.com/TheBigBad31/VitalTrack/releases/latest/download/vitaltrack-health-bridge.apk"


def get_db() -> Database:
    """Retourne l'instance Database courante depuis src.app (supporte le monkeypatch des tests)."""
    return app_module.db


class BackupRestoreInput(BaseModel):
    data: Dict[str, Any]
    overwrite: bool = False


class ConfirmDeletionPayload(BaseModel):
    confirm: bool = Field(True, description="Confirmation explicite de la suppression")
    password: Optional[str] = Field(None, description="Mot de passe optionnel pour confirmation")


class ConsentUpdatePayload(BaseModel):
    category: str = Field(..., description="biometrics, nutrition, analytics, devices")
    consented: bool = Field(..., description="true ou false")


@router.get("/api/backup/export")
@router.get("/api/export/json")
def export_backup(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Exporte l'intégralité du profil utilisateur, des appareils configurés et de l'historique en JSON (RGPD)."""
    db = get_db()
    backup_data = db.export_full_backup(user_id=current_user.id)
    return backup_data


@router.get("/api/export/csv")
def export_data_csv(
    limit: Optional[int] = Query(None, description="Limite optionnelle pour pagination ou export complet"),
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Exporte l'intégralité des données biométriques (pesées et activités) au format CSV standard sans troncature (RGPD)."""
    db = get_db()
    fetch_limit = limit if limit and limit > 0 else 1000000
    weights = db.get_weights(limit=fetch_limit, user_id=current_user.id)
    activities = db.get_activities(limit=fetch_limit, user_id=current_user.id)

    output = io.StringIO()
    writer = csv.writer(output)

    # 1. Section Pesées
    writer.writerow(["### SECTION: WEIGHTS ###"])
    writer.writerow(["date", "weight_kg", "body_fat_pct", "muscle_mass_kg", "water_pct", "bmi", "trend_7d_kg", "source", "external_id", "notes"])
    for w in weights:
        writer.writerow([
            w.date.isoformat(),
            w.weight_kg,
            w.body_fat_pct if w.body_fat_pct is not None else "",
            w.muscle_mass_kg if w.muscle_mass_kg is not None else "",
            w.water_pct if w.water_pct is not None else "",
            w.bmi if w.bmi is not None else "",
            w.trend_7d_kg if w.trend_7d_kg is not None else "",
            w.source,
            w.external_id or "",
            w.notes or "",
        ])

    writer.writerow([])
    # 2. Section Activités
    writer.writerow(["### SECTION: ACTIVITIES ###"])
    writer.writerow(["date", "steps", "active_calories_kcal", "bmr_kcal", "total_burned_kcal", "workout_minutes", "workout_type", "resting_hr_bpm", "hrv_ms", "sleep_score", "source", "external_id"])
    for a in activities:
        writer.writerow([
            a.date.isoformat(),
            a.steps,
            a.active_calories_kcal,
            a.bmr_kcal,
            a.total_burned_kcal,
            a.workout_minutes,
            a.workout_type or "",
            a.resting_hr_bpm if a.resting_hr_bpm is not None else "",
            a.hrv_ms if a.hrv_ms is not None else "",
            a.sleep_score if a.sleep_score is not None else "",
            a.source,
            a.external_id or "",
        ])

    csv_content = output.getvalue()
    filename = f"vitaltrack_export_{current_user.id}_{date.today().isoformat()}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.delete("/api/user/data")
def delete_user_data_only_endpoint(
    confirm: bool = Query(True, description="Confirmation de purge des données"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Efface l'intégralité des données et de l'historique biométrique tout en conservant le compte et les accès de l'utilisateur."""
    db = get_db()
    is_confirmed = confirm and (payload.confirm if payload else True)
    if not is_confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise pour la suppression des données (confirm=true)")
    success = db.delete_user_data_only(user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {
        "status": "success",
        "message": f"Toutes les données de santé pour {current_user.email} ont été purgées avec succès. Le compte utilisateur reste actif.",
    }


@router.delete("/api/user/account")
def delete_user_account_endpoint(
    confirm: bool = Query(True, description="Confirmation de suppression du compte"),
    payload: Optional[ConfirmDeletionPayload] = None,
    current_user: AuthUser = Depends(app_module.get_current_user),
):
    """Supprime définitivement le compte utilisateur et l'ensemble de ses données associées (Droit à l'oubli RGPD)."""
    db = get_db()
    is_confirmed = confirm and (payload.confirm if payload else True)
    if not is_confirmed:
        raise HTTPException(status_code=400, detail="Confirmation requise pour la suppression définitive du compte (confirm=true)")
    success = db.delete_user_account_and_data(user_id=current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable ou déjà supprimé")
    return {
        "status": "success",
        "message": f"Compte et toutes les données associées pour {current_user.email} ont été définitivement supprimés.",
    }


@router.get("/api/user/consents")
def get_user_consents_endpoint(current_user: AuthUser = Depends(app_module.get_current_user)):
    """Retourne les préférences de consentement RGPD par catégorie pour l'utilisateur."""
    db = get_db()
    consents = db.get_user_consents(user_id=current_user.id)
    return {
        "user_id": current_user.id,
        "consents": consents,
    }


@router.post("/api/user/consents")
def update_user_consent_endpoint(payload: ConsentUpdatePayload, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Met à jour le consentement pour une catégorie spécifique."""
    db = get_db()
    allowed_categories = {"biometrics", "nutrition", "analytics", "devices"}
    if payload.category not in allowed_categories:
        raise HTTPException(status_code=400, detail=f"Catégorie invalide. Choix possibles: {allowed_categories}")
    res = db.set_user_consent(category=payload.category, consented=payload.consented, user_id=current_user.id)
    return {
        "status": "success",
        "consent": res.model_dump(),
    }


@router.post("/api/backup/import")
def import_backup(payload: BackupRestoreInput, current_user: AuthUser = Depends(app_module.get_current_user)):
    """Restaure ou synchronise les données depuis un export JSON ou le localStorage/IndexedDB."""
    db = get_db()
    result = db.import_full_backup(payload.data, overwrite=payload.overwrite, user_id=current_user.id)
    app_module.invalidate_dashboard_cache(current_user.id)
    return result


@router.get("/api/goals/presets")
def get_goals_presets():
    """Retourne la configuration des profils métaboliques prédéfinis 1-clic."""
    if os.path.isfile(GOALS_CONFIG_FILE):
        try:
            with open(GOALS_CONFIG_FILE, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "profiles" in data:
                    return data
        except (OSError, yaml.YAMLError):
            logger.exception("Erreur lors du chargement de la configuration des profils d'objectifs (%s)", GOALS_CONFIG_FILE)
    return DEFAULT_GOALS_PRESETS


@router.get("/api/config")
def get_config():
    """Expose les constantes de configuration (source de vérité backend) pour le client."""
    return {
        "kcal_per_kg": KCAL_PER_KG,
        "goal_profiles": get_goals_presets(),
        "defaults": {
            "target_calories_intake": 2000.0,
            "bmr_kcal": 1780.0,
            "steps_target": 10000,
        },
    }


@router.get("/api/downloads/android-bridge")
def download_android_bridge():
    """Téléchargement direct de l'APK VitalTrack Android Health Bridge."""
    static_dir = getattr(app_module, "STATIC_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "static"))
    local_apk = os.path.join(static_dir, "downloads", "vitaltrack-health-bridge.apk")
    if os.path.isfile(local_apk):
        return FileResponse(
            local_apk,
            media_type="application/vnd.android.package-archive",
            filename="vitaltrack-health-bridge.apk",
        )
    return RedirectResponse(url=GITHUB_LATEST_RELEASE_APK_URL, status_code=307)
