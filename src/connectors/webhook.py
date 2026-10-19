"""Connecteur universel pour Webhooks mobiles (Apple Santé via Raccourcis iOS, Health Connect / Tasker Android).

Permet d'ingérer instantanément les données en provenance de :
- Raccourcis iOS (Apple HealthKit : Poids, Masse Grasse, Pas, Dépense Active, FC, Sommeil)
- Android Health Connect (Google Fit, Samsung Health, Ultrahuman Ring, RingConn, balances Mi Body)
- Strava (via export ou webhook)

Valide et convertit le payload JSON universel vers WeightEntry et ActivityEntry.
"""

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from src.connectors.base import BaseHealthConnector
from src.models import ActivityEntry, WeightEntry


class MobileHealthWebhookConnector(BaseHealthConnector):
    """Adaptateur universel pour Webhooks de santé mobile."""

    def _check_configuration(self) -> bool:
        """Vérifie si un token secret de webhook est configuré (optionnel mais recommandé)."""
        return True

    def authenticate_request(self, token: Optional[str]) -> bool:
        """Vérifie le token secret d'authentification s'il est configuré."""
        secret = self.config.get("webhook_secret")
        if not secret:
            return True
        return token == secret

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
        if "weight_kg" in payload or "weight" in payload:
            w_kg = float(payload.get("weight_kg", payload.get("weight", 0.0)))
            if w_kg > 0:
                fat_pct = payload.get("body_fat_pct", payload.get("body_fat"))
                muscle_kg = payload.get("muscle_mass_kg", payload.get("muscle_mass"))
                water_pct = payload.get("water_pct", payload.get("water"))
                bmi = payload.get("bmi")
                if not bmi and self.config.get("user_height_m"):
                    h = self.config["user_height_m"]
                    bmi = round(w_kg / (h ** 2), 1)

                weight_source = "apple_health" if "apple" in source_name else (
                    "garmin" if "garmin" in source_name else "manual"
                )

                weight_entry = WeightEntry(
                    date=target_date,
                    weight_kg=w_kg,
                    body_fat_pct=float(fat_pct) if fat_pct is not None else None,
                    muscle_mass_kg=float(muscle_kg) if muscle_kg is not None else None,
                    water_pct=float(water_pct) if water_pct is not None else None,
                    bmi=float(bmi) if bmi is not None else None,
                    source=weight_source,
                    notes=payload.get("notes", f"Ingéré via Mobile Webhook ({source_name})")
                )

        # Extraction Activité
        activity_entry = None
        has_activity_fields = any(k in payload for k in [
            "steps", "active_calories_kcal", "active_calories",
            "resting_hr_bpm", "resting_heart_rate", "hrv_ms", "sleep_score"
        ])

        if has_activity_fields:
            steps = int(payload.get("steps", 0))
            active_cal = float(payload.get("active_calories_kcal", payload.get("active_calories", 0.0)))
            bmr = float(payload.get("bmr_kcal", payload.get("bmr", 1750.0)))
            total_cal = float(payload.get("total_burned_kcal", payload.get("total_calories", bmr + active_cal)))
            workout_min = int(payload.get("workout_minutes", 0))
            workout_type = payload.get("workout_type")
            resting_hr = payload.get("resting_hr_bpm", payload.get("resting_heart_rate"))
            hrv = payload.get("hrv_ms", payload.get("hrv"))
            sleep_sc = payload.get("sleep_score")

            act_source = "ringconn" if "ringconn" in source_name.lower() or "ring" in source_name.lower() else (
                "oura" if "oura" in source_name.lower() else (
                    "health_connect" if "connect" in source_name or "android" in source_name else (
                        "apple_health" if "apple" in source_name else (
                            "strava" if "strava" in source_name else "demo"
                        )
                    )
                )
            )

            activity_entry = ActivityEntry(
                date=target_date,
                steps=steps,
                active_calories_kcal=active_cal,
                bmr_kcal=bmr,
                total_burned_kcal=total_cal,
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
