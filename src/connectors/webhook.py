"""Connecteur universel pour Webhooks mobiles (Apple Santé via Raccourcis iOS, Health Connect / Tasker Android).

Permet d'ingérer instantanément les données en provenance de :
- Raccourcis iOS (Apple HealthKit : Poids, Masse Grasse, Pas, Dépense Active, FC, Sommeil)
- Android Health Connect (Google Fit, Samsung Health, Ultrahuman Ring, RingConn, balances Mi Body)
- Strava (via export ou webhook)

Valide et convertit le payload JSON universel vers WeightEntry et ActivityEntry.
"""

import hmac
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from src.connectors.base import BaseHealthConnector
from src.models import ActivityEntry, WeightEntry


class MobileHealthWebhookConnector(BaseHealthConnector):
    """Adaptateur universel pour Webhooks de santé mobile."""

    device_id: str = "mobile_webhook"
    name: str = "Mobile Health Webhook"
    device_type: str = "mobile_aggregator"

    def _check_configuration(self) -> bool:
        """Vérifie si un token secret de webhook est configuré (optionnel mais recommandé)."""
        return True

    def authenticate_request(self, token: Optional[str]) -> bool:
        """Vérifie strictement le token secret d'authentification en temps constant."""
        if not token or not str(token).strip():
            return False
        secret = self.config.get("webhook_secret")
        if not secret:
            return False
        return hmac.compare_digest(str(token).strip(), str(secret).strip())

    def process_webhook_payload(
        self, payload: Dict[str, Any]
    ) -> Tuple[Optional[WeightEntry], Optional[ActivityEntry]]:
        """Traite un payload webhook universel et extrait une pesée et/ou une activité."""
        date_raw = payload.get("date")
        if not date_raw:
            target_date = date.today()
        elif isinstance(date_raw, str):
            # Accepte ISO YYYY-MM-DD ou date-heure complète
            target_date = date.fromisoformat(date_raw[:10])
        elif isinstance(date_raw, (date, datetime)):
            target_date = date_raw if isinstance(date_raw, date) else date_raw.date()
        else:
            target_date = date.today()

        source_name = payload.get("source", "apple_health")

        # Extraction Pesée
        weight_entry = None
        has_weight = any(k in payload for k in ("weight_kg", "weight", "weight_lb", "weight_st", "weight_stone"))
        if has_weight:
            # Détecter l'unité : weight_lb / lb = livres, weight_st / stone = stones, weight_kg / weight = kg
            unit_val = str(payload.get("unit") or payload.get("weight_unit") or "").lower().strip()
            if "weight_lb" in payload or "lb" in unit_val or "pound" in unit_val:
                raw_w = float(payload.get("weight_lb", payload.get("weight_kg", payload.get("weight", 0.0))))
                w_kg = raw_w * 0.45359237  # lb → kg
            elif "weight_st" in payload or "weight_stone" in payload or "stone" in unit_val or unit_val == "st":
                raw_w = float(payload.get("weight_st", payload.get("weight_stone", payload.get("weight_kg", payload.get("weight", 0.0)))))
                w_kg = raw_w * 6.35029318  # stone → kg
            else:
                w_kg = float(payload.get("weight_kg", payload.get("weight", 0.0)))
            
            if w_kg > 0:
                fat_pct = payload.get("body_fat_pct", payload.get("body_fat"))
                muscle_kg = payload.get("muscle_mass_kg", payload.get("muscle_mass"))
                water_pct = payload.get("water_pct", payload.get("water"))
                bmi = payload.get("bmi")
                if not bmi and self.config.get("user_height_m"):
                    h = self.config["user_height_m"]
                    bmi = round(w_kg / (h ** 2), 1)

                weight_source = "health_connect" if ("connect" in source_name or "android" in source_name) else (
                    "apple_health" if "apple" in source_name else (
                        "withings" if "withings" in source_name else (
                            "garmin" if "garmin" in source_name else "manual"
                        )
                    )
                )

                # Date réelle de la mesure (weight_date prioritaire, ou déduit de measured_at/timestamp)
                target_weight_date = target_date
                weight_date_raw = payload.get("weight_date")
                measured_at_val = payload.get("measured_at") or payload.get("weight_measured_at") or payload.get("timestamp")
                measured_at_iso = None

                if measured_at_val is not None:
                    if isinstance(measured_at_val, (int, float)):
                        epoch_sec = float(measured_at_val) / 1000.0 if float(measured_at_val) > 1e11 else float(measured_at_val)
                        dt = datetime.fromtimestamp(epoch_sec, timezone.utc)
                        measured_at_iso = dt.isoformat()
                        if not weight_date_raw:
                            target_weight_date = dt.date()
                    elif isinstance(measured_at_val, str) and measured_at_val.strip():
                        measured_at_iso = measured_at_val.strip()
                        if not weight_date_raw:
                            try:
                                target_weight_date = date.fromisoformat(measured_at_iso[:10])
                            except Exception:
                                pass

                if weight_date_raw:
                    if isinstance(weight_date_raw, str):
                        target_weight_date = date.fromisoformat(weight_date_raw[:10])
                    elif isinstance(weight_date_raw, (date, datetime)):
                        target_weight_date = weight_date_raw if isinstance(weight_date_raw, date) else weight_date_raw.date()

                weight_ext_id = payload.get("weight_external_id") or payload.get("external_id") or payload.get("id")

                weight_entry = WeightEntry(
                    date=target_weight_date,
                    weight_kg=round(w_kg, 2),
                    body_fat_pct=float(fat_pct) if fat_pct is not None else None,
                    muscle_mass_kg=float(muscle_kg) if muscle_kg is not None else None,
                    water_pct=float(water_pct) if water_pct is not None else None,
                    bmi=float(bmi) if bmi is not None else None,
                    source=weight_source,
                    notes=payload.get("notes", f"Ingéré via Mobile Webhook ({source_name})"),
                    external_id=str(weight_ext_id) if weight_ext_id else None,
                    measured_at=measured_at_iso
                )

        # Extraction Activité
        activity_entry = None
        has_activity_fields = any(k in payload for k in [
            "steps", "active_calories_kcal", "active_calories",
            "active_energy_kj", "resting_hr_bpm", "resting_heart_rate", "hrv_ms", "sleep_score"
        ])

        if has_activity_fields:
            steps = int(payload.get("steps", 0))
            
            # Détecter l'unité des calories : kJ ou kcal
            if "active_energy_kj" in payload:
                active_cal = float(payload.get("active_energy_kj", 0.0)) / 4.184  # kJ → kcal
            else:
                active_cal = float(payload.get("active_calories_kcal", payload.get("active_calories", 0.0)))
            
            # BMR peut aussi être en kJ
            if "bmr_kj" in payload:
                bmr = float(payload.get("bmr_kj", 0.0)) / 4.184  # kJ → kcal
            else:
                bmr = float(payload.get("bmr_kcal", payload.get("bmr", 1750.0)))
            
            # Total calories peut être en kJ
            if "total_energy_kj" in payload:
                total_cal = float(payload.get("total_energy_kj", 0.0)) / 4.184  # kJ → kcal
            else:
                total_cal = float(payload.get("total_burned_kcal", payload.get("total_calories", payload.get("total_calories_kcal", bmr + active_cal))))
            
            workout_min = int(payload.get("workout_minutes", 0))
            workout_type = payload.get("workout_type")
            resting_hr = payload.get("resting_hr_bpm", payload.get("resting_heart_rate"))
            hrv = payload.get("hrv_ms", payload.get("hrv"))
            sleep_sc = payload.get("sleep_score")

            act_source = "ringconn" if "ring" in source_name.lower() else (
                "health_connect" if "connect" in source_name or "android" in source_name else (
                    "apple_health" if "apple" in source_name else (
                        "oura" if "oura" in source_name.lower() else (
                            "strava" if "strava" in source_name else "demo"
                        )
                    )
                )
            )

            activity_entry = ActivityEntry(
                date=target_date,
                steps=steps,
                active_calories_kcal=round(active_cal, 1),
                bmr_kcal=round(bmr, 1),
                total_burned_kcal=round(total_cal, 1),
                workout_minutes=workout_min,
                workout_type=workout_type,
                resting_hr_bpm=int(resting_hr) if resting_hr is not None else None,
                hrv_ms=float(hrv) if hrv is not None else None,
                sleep_score=int(sleep_sc) if sleep_sc is not None else None,
                source=act_source
            )

        return weight_entry, activity_entry

    def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """Le webhook fonctionne principalement en push/réception événementielle."""
        return []

    def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Le webhook fonctionne principalement en push/réception événementielle."""
        return []
