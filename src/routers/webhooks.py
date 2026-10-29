"""Routeur d'ingestion des webhooks de santé pour VitalTrack.

Prend en charge :
- Ingestion unifiée multi-métriques : Sommeil & phases (sleep_sessions, sleep_stages),
  Fréquence cardiaque & échantillons intraday (intraday_samples), HRV (RMSSD/SDNN),
  SpO2, température cutanée, pas quotidiens et horaires, calories actives/totales,
  séances d'entraînement (workouts), poids et composition corporelle.
- Authentification stricte par token d'appareil individuel (prioritaire) avec fallback
  sécurisé via WEBHOOK_SECRET.
- Idempotence garantie via clé composite (source, external_id) et enregistrement audit raw_ingest.
- Support des lots incrémentaux (batch JSON sous forme de liste ou payload avec clé 'items'/'batch').
- Respect des consentements RGPD utilisateur par catégorie.
"""

from datetime import date, datetime, timezone
import hmac
import os
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.connectors.webhook import MobileHealthWebhookConnector
from src.db import Database
from src.models import (
    ActivityEntry, DailyMetricsEntry, HydrationLogEntry, IntradaySampleEntry,
    SleepSessionEntry, SleepStageEntry, WeightEntry, WorkoutEntry
)

router = APIRouter(tags=["Webhooks"])


def get_db() -> Database:
    """Retourne l'instance courante de la base de données (supporte le monkeypatch dans app.db)."""
    import sys
    app_module = sys.modules.get("src.app")
    if app_module and hasattr(app_module, "db") and app_module.db is not None:
        return app_module.db
    return Database()


def extract_auth_token(
    payload: Any,
    token: Optional[str] = None,
    x_webhook_token: Optional[str] = None,
    authorization: Optional[str] = None
) -> Optional[str]:
    """Extrait le jeton d'authentification selon l'ordre de priorité strict :
    1. Header 'X-Webhook-Token'
    2. Header 'Authorization' (Bearer ou token direct)
    3. Query parameter '?token=...'
    4. Payload JSON champ 'token', 'webhook_token' ou 'api_key'
    """
    if x_webhook_token and str(x_webhook_token).strip():
        return str(x_webhook_token).strip()

    if authorization and str(authorization).strip():
        auth_str = str(authorization).strip()
        if auth_str.lower().startswith("bearer "):
            return auth_str[7:].strip()
        return auth_str

    if token and str(token).strip():
        return str(token).strip()

    if isinstance(payload, dict):
        for candidate_key in ("token", "webhook_token", "api_key"):
            cand = payload.get(candidate_key)
            if cand and str(cand).strip():
                return str(cand).strip()

    return None


def resolve_webhook_user_and_device(
    auth_token: str,
    payload: Any,
    database: Optional[Database] = None
) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Résout l'utilisateur et le terminal associé à un token webhook.
    
    Vérifie en premier lieu le token d'appareil individuel (user_devices chiffré au repos),
    puis utilise le fallback fail-closed WEBHOOK_SECRET si configuré.
    """
    db_inst = database or get_db()
    user_match = db_inst.find_user_by_device_token(auth_token)
    if user_match:
        return int(user_match["user_id"]), user_match.get("device")

    # Fallback de validation via WEBHOOK_SECRET global si configuré
    is_production = os.getenv("VERCEL") == "1" or os.getenv("ENV") == "production"
    global_secret = os.getenv("WEBHOOK_SECRET")

    if not global_secret:
        if is_production:
            raise HTTPException(
                status_code=503,
                detail="Service Webhook non configuré en production (secret absent)"
            )
    else:
        if hmac.compare_digest(str(auth_token).strip(), str(global_secret).strip()):
            target_user_id = payload.get("user_id") if isinstance(payload, dict) else None
            if target_user_id:
                user_obj = db_inst.get_user_by_id(int(target_user_id))
                if user_obj:
                    return int(target_user_id), None
            default_user = db_inst.get_user_by_id(1)
            if default_user:
                return 1, None

    raise HTTPException(
        status_code=401,
        detail="Token webhook invalide ou non autorisé : aucun compte utilisateur ou appareil associé"
    )


def process_single_item(
    item: Dict[str, Any],
    resolved_user_id: int,
    matched_device: Optional[Dict[str, Any]],
    user_consents: Dict[str, bool],
    endpoint_path: str = "/api/webhook/health",
    database: Optional[Database] = None
) -> Dict[str, Any]:
    """Traite et persiste une unité élémentaire de données de santé de façon idempotente."""
    db_inst = database or get_db()
    connector = MobileHealthWebhookConnector()
    source_name = item.get("source", (matched_device.get("device_id") if matched_device else "health_connect"))
    can_ingest_biometrics = user_consents.get("biometrics", True)
    can_ingest_devices = user_consents.get("devices", True)

    ext_id = item.get("external_id") or item.get("id")
    idemp_key = f"{source_name}:{ext_id}" if ext_id else None

    # 1. Audit raw_ingest avec clé d'idempotence
    db_inst.insert_raw_ingest(
        source=source_name,
        payload=item,
        user_id=resolved_user_id,
        endpoint=endpoint_path,
        idempotency_key=idemp_key
    )

    saved_weight = None
    saved_act = None
    saved_daily_metric = None
    saved_sleep_session = None
    saved_workouts = []
    saved_intraday_count = 0
    saved_hydration = None

    # 2. Poids et composition corporelle
    weight_entry, act_entry = connector.process_webhook_payload(item)
    if weight_entry and can_ingest_biometrics:
        if ext_id and not weight_entry.external_id:
            weight_entry.external_id = str(ext_id)
        saved_weight = db_inst.insert_weight(weight_entry, user_id=resolved_user_id).model_dump()

    # 3. Activité quotidienne standard
    if act_entry and can_ingest_biometrics:
        if ext_id and not act_entry.external_id:
            act_entry.external_id = str(ext_id)
        saved_act = db_inst.insert_activity(act_entry, user_id=resolved_user_id).model_dump()

    # 4. Métriques quotidiennes enrichies (HRV, SpO2, Température, FC repos, Sommeil)
    has_daily_metric = any(k in item for k in [
        "resting_hr_bpm", "resting_heart_rate", "hrv_rmssd_ms", "hrv_sdnn_ms", "hrv_ms", "hrv",
        "spo2_pct", "spo2", "skin_temperature_c", "skin_temperature", "sleep_score", "recovery_score"
    ])
    if has_daily_metric and can_ingest_biometrics:
        raw_d = item.get("date")
        target_d = date.fromisoformat(str(raw_d)[:10]) if raw_d else date.today()
        d_metric = DailyMetricsEntry(
            user_id=resolved_user_id,
            date=target_d,
            source=source_name,
            steps=int(item.get("steps", (act_entry.steps if act_entry else 0))),
            active_calories_kcal=float(item.get("active_calories_kcal", item.get("active_calories", (act_entry.active_calories_kcal if act_entry else 0.0)))),
            total_calories_kcal=float(item.get("total_burned_kcal", item.get("total_calories", (act_entry.total_burned_kcal if act_entry else 0.0)))),
            resting_hr_bpm=int(item["resting_hr_bpm"]) if item.get("resting_hr_bpm") is not None else (
                int(item["resting_heart_rate"]) if item.get("resting_heart_rate") is not None else (
                    int(item["resting_hr"]) if item.get("resting_hr") is not None else (
                        act_entry.resting_hr_bpm if act_entry and act_entry.resting_hr_bpm else None
                    )
                )
            ),
            hrv_rmssd_ms=float(item["hrv_rmssd_ms"]) if item.get("hrv_rmssd_ms") is not None else (
                float(item["hrv_ms"]) if item.get("hrv_ms") is not None else (
                    float(item["hrv"]) if item.get("hrv") is not None else (
                        act_entry.hrv_ms if act_entry and act_entry.hrv_ms else None
                    )
                )
            ),
            hrv_sdnn_ms=float(item["hrv_sdnn_ms"]) if item.get("hrv_sdnn_ms") is not None else None,
            spo2_pct=float(item["spo2_pct"]) if item.get("spo2_pct") is not None else (
                float(item["spo2"]) if item.get("spo2") is not None else None
            ),
            skin_temperature_c=float(item["skin_temperature_c"]) if item.get("skin_temperature_c") is not None else (
                float(item["skin_temperature"]) if item.get("skin_temperature") is not None else None
            ),
            sleep_score=int(item["sleep_score"]) if item.get("sleep_score") is not None else (
                act_entry.sleep_score if act_entry and act_entry.sleep_score else None
            ),
            recovery_score=int(item["recovery_score"]) if item.get("recovery_score") is not None else None,
            external_id=str(ext_id) if ext_id else None
        )
        saved_daily_metric = db_inst.insert_daily_metric(d_metric, user_id=resolved_user_id).model_dump()

    # 5. Sessions de sommeil & phases détaillées (sleep_sessions / sleep_stages)
    sleep_data = item.get("sleep_session") or item.get("sleep")
    raw_sleep_sessions = item.get("sleep_sessions")
    sessions_to_process = []
    if isinstance(raw_sleep_sessions, list):
        sessions_to_process.extend(raw_sleep_sessions)
    elif isinstance(sleep_data, dict):
        sessions_to_process.append(sleep_data)

    for s_dict in sessions_to_process:
        if not can_ingest_biometrics or not isinstance(s_dict, dict):
            continue
        s_date_raw = s_dict.get("date") or item.get("date")
        s_date = date.fromisoformat(str(s_date_raw)[:10]) if s_date_raw else date.today()
        s_ext_id = s_dict.get("external_id") or s_dict.get("id") or (f"{ext_id}_sleep" if ext_id else None)
        
        stages_list = []
        raw_stages = s_dict.get("stages") or s_dict.get("sleep_stages") or []
        for st in raw_stages:
            if isinstance(st, dict):
                stages_list.append(SleepStageEntry(
                    stage=st.get("stage", "light"),
                    start_time=str(st.get("start_time", "")),
                    end_time=str(st.get("end_time", "")),
                    duration_seconds=int(st.get("duration_seconds", 0))
                ))

        session_obj = SleepSessionEntry(
            user_id=resolved_user_id,
            source=s_dict.get("source", source_name),
            external_id=str(s_ext_id) if s_ext_id else None,
            date=s_date,
            start_time=str(s_dict.get("start_time", "")),
            end_time=str(s_dict.get("end_time", "")),
            duration_minutes=int(s_dict.get("duration_minutes", 0)),
            efficiency_pct=float(s_dict["efficiency_pct"]) if s_dict.get("efficiency_pct") is not None else None,
            sleep_debt_minutes=int(s_dict["sleep_debt_minutes"]) if s_dict.get("sleep_debt_minutes") is not None else None,
            sleep_score=int(s_dict["sleep_score"]) if s_dict.get("sleep_score") is not None else None,
            deep_minutes=int(s_dict.get("deep_minutes", 0)),
            light_minutes=int(s_dict.get("light_minutes", 0)),
            rem_minutes=int(s_dict.get("rem_minutes", 0)),
            awake_minutes=int(s_dict.get("awake_minutes", 0)),
            stages=stages_list
        )
        saved_session = db_inst.insert_sleep_session(session_obj, user_id=resolved_user_id)
        saved_sleep_session = saved_session.model_dump()

    # 6. Séances d'entraînement (workouts)
    workouts_raw = item.get("workouts") or (item.get("workout") and [item.get("workout")]) or []
    if isinstance(workouts_raw, list) and can_ingest_biometrics:
        for w in workouts_raw:
            if not isinstance(w, dict):
                continue
            w_ext_id = w.get("external_id") or w.get("id") or (f"{ext_id}_wo" if ext_id else None)
            w_entry = WorkoutEntry(
                user_id=resolved_user_id,
                source=w.get("source", source_name),
                external_id=str(w_ext_id) if w_ext_id else None,
                workout_type=w.get("workout_type", "workout"),
                start_time=str(w.get("start_time", "")),
                end_time=str(w.get("end_time", "")),
                duration_minutes=int(w.get("duration_minutes", 0)),
                calories_kcal=float(w.get("calories_kcal", w.get("calories", 0.0))),
                avg_hr_bpm=int(w["avg_hr_bpm"]) if w.get("avg_hr_bpm") is not None else None,
                max_hr_bpm=int(w["max_hr_bpm"]) if w.get("max_hr_bpm") is not None else None,
                distance_meters=float(w["distance_meters"]) if w.get("distance_meters") is not None else None,
                notes=w.get("notes")
            )
            saved_w = db_inst.insert_workout(w_entry, user_id=resolved_user_id)
            saved_workouts.append(saved_w.model_dump())

    # 7. Échantillons haute fréquence intraday (FC, pas horaires, SpO2)
    intraday_raw = item.get("intraday_samples") or item.get("samples") or []
    samples_list = []
    if isinstance(intraday_raw, list) and can_ingest_biometrics:
        for s in intraday_raw:
            if isinstance(s, dict):
                samples_list.append(IntradaySampleEntry(
                    user_id=resolved_user_id,
                    source=s.get("source", source_name),
                    metric_type=s.get("metric_type", "hr"),
                    timestamp=str(s.get("timestamp", datetime.now(timezone.utc).isoformat())),
                    value=float(s.get("value", 0.0)),
                    unit=s.get("unit")
                ))
        if samples_list:
            saved_intraday_count = db_inst.insert_intraday_samples(samples_list, user_id=resolved_user_id)

    # 8. Hydratation (hydration_logs)
    if "hydration_ml" in item or "volume_ml" in item:
        if can_ingest_biometrics:
            vol = float(item.get("hydration_ml", item.get("volume_ml", 0.0)))
            if vol > 0:
                raw_d = item.get("date")
                target_d = date.fromisoformat(str(raw_d)[:10]) if raw_d else date.today()
                h_entry = HydrationLogEntry(
                    user_id=resolved_user_id,
                    date=target_d,
                    timestamp=item.get("timestamp", datetime.now(timezone.utc).isoformat()),
                    volume_ml=vol,
                    source=source_name,
                    external_id=str(ext_id) if ext_id else None
                )
                saved_hydration = db_inst.insert_hydration_log(h_entry, user_id=resolved_user_id).model_dump()

    # 9. Mise à jour de l'état de l'appareil
    dev_id = matched_device.get("device_id") if matched_device else (
        "ringconn" if "ring" in source_name.lower() else (
            "withings" if "withings" in source_name.lower() else "health_connect"
        )
    )
    dev_name = matched_device.get("name") if matched_device else dev_id.replace("_", " ").title()
    dev_type = matched_device.get("device_type") if matched_device else (
        "ring" if dev_id == "ringconn" else ("scale" if dev_id == "withings" else "mobile_aggregator")
    )

    if can_ingest_devices:
        db_inst.update_user_device(
            device_id=dev_id,
            name=dev_name,
            device_type=dev_type,
            connected=True,
            auth_type="webhook",
            user_id=resolved_user_id
        )

    return {
        "device_id": dev_id,
        "source": source_name,
        "ingested": {
            "weight": saved_weight,
            "activity": saved_act,
            "daily_metric": saved_daily_metric,
            "sleep_session": saved_sleep_session,
            "workouts": saved_workouts,
            "intraday_samples_count": saved_intraday_count,
            "hydration": saved_hydration
        }
    }


@router.post("/api/webhook/health")
@router.post("/api/webhook/health/")
@router.post("/api/webhooks/health")
@router.post("/api/webhooks/health/")
@router.post("/api/webhooks/health-connect")
@router.post("/api/webhooks/health-connect/")
@router.post("/api/webhook/health-connect")
@router.post("/api/webhook/health-connect/")
@router.post("/api/webhooks/health_connect")
@router.post("/api/webhooks/health_connect/")
@router.post("/api/webhook/health_connect")
@router.post("/api/webhook/health_connect/")
@router.post("/api/webhooks/ringconn")
@router.post("/api/webhooks/ringconn/")
@router.get("/api/webhooks/health-connect")
@router.get("/api/webhooks/health-connect/")
@router.get("/api/webhook/health")
@router.get("/api/webhook/health/")
def ingest_health_webhook(
    payload: Optional[Union[Dict[str, Any], List[Dict[str, Any]]]] = Body(None),
    token: Optional[str] = Query(None),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
    authorization: Optional[str] = Header(None)
):
    """Point d'entrée universel et sécurisé pour les webhooks mobiles ou passerelles (Health Connect, RingConn, Xiaomi).
    
    Prend en charge :
    - Éléments individuels ou lots incrémentaux JSON (batch)
    - Authentification stricte par token d'appareil individuel (X-Webhook-Token, Authorization, query param, ou body)
    - Idempotence garantie et conformité RGPD
    - GET de diagnostic ou ping de connectivité
    """
    if payload is None:
        # Requête GET ou ping sans body
        return {
            "status": "ready",
            "endpoint": "/api/webhooks/health-connect",
            "message": "Passerelle Webhook VitalTrack opérationnelle. Envoyez les métriques via POST en JSON avec X-Webhook-Token."
        }
    auth_token = extract_auth_token(
        payload=payload,
        token=token,
        x_webhook_token=x_webhook_token,
        authorization=authorization
    )

    if not auth_token:
        raise HTTPException(
            status_code=401,
            detail="Jeton d'authentification manquant. Fournissez un token via header 'X-Webhook-Token', 'Authorization' ou query param 'token'."
        )

    resolved_user_id, matched_device = resolve_webhook_user_and_device(
        auth_token=auth_token,
        payload=payload,
        database=get_db()
    )

    user_consents = get_db().get_user_consents(user_id=resolved_user_id)

    # Détection si payload est un lot (liste directe ou dict avec 'items'/'batch'/'records')
    items_to_process = []
    if isinstance(payload, list):
        items_to_process = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            items_to_process = payload["items"]
        elif isinstance(payload.get("batch"), list):
            items_to_process = payload["batch"]
        elif isinstance(payload.get("records"), list):
            items_to_process = payload["records"]
        else:
            items_to_process = [payload]

    results = []
    for single_item in items_to_process:
        if isinstance(single_item, dict):
            res = process_single_item(
                item=single_item,
                resolved_user_id=resolved_user_id,
                matched_device=matched_device,
                user_consents=user_consents,
                endpoint_path="/api/webhook/health",
                database=get_db()
            )
            results.append(res)

    is_batch = len(items_to_process) > 1 or isinstance(payload, list) or (isinstance(payload, dict) and any(k in payload for k in ("items", "batch", "records")))

    primary_device_id = results[0]["device_id"] if results else (matched_device.get("device_id") if matched_device else "health_connect")
    single_ingested = results[0]["ingested"] if results else {}

    return {
        "status": "success",
        "message": f"{len(results)} enregistrement(s) de santé ingéré(s) avec succès pour l'utilisateur {resolved_user_id}",
        "user_id": resolved_user_id,
        "device_id": primary_device_id,
        "is_batch": is_batch,
        "count": len(results),
        "ingested": single_ingested,
        "results": results if is_batch else single_ingested
    }
