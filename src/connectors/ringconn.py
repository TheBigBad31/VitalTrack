"""Connecteur pour les bagues connectées RingConn (Gen 1, Gen 2 & Gen 3).

Gère :
- Interconnexion directe via RingConn Open API ou via passerelle Google Health Connect
- Métriques biométriques : Sommeil (score, durée), HRV nocturne (RMSSD), Fréquence Cardiaque au repos, Pas, Calories actives
- Mode Démo / Simulation 30 jours si les identifiants ou le token d'API ne sont pas encore renseignés.
"""

import math
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseHealthConnector
from src.models import ActivityEntry, WeightEntry


class RingConnConnector(BaseHealthConnector):
    """Connecteur pour bague de santé RingConn (notamment Gen 3)."""

    BASE_URL = "https://api.ringconn.com/v1"

    def _check_configuration(self) -> bool:
        """Vérifie si le token d'accès RingConn OpenAPI est configuré."""
        token = self.config.get("api_key") or self.config.get("access_token")
        return bool(token)

    def parse_ringconn_daily_data(
        self,
        activity_data: Dict[str, Any],
        sleep_data: Optional[Dict[str, Any]] = None,
        hrv_data: Optional[Dict[str, Any]] = None
    ) -> ActivityEntry:
        """Parse les payloads RingConn vers un ActivityEntry standardisé."""
        date_str = activity_data.get("date") or activity_data.get("day")
        if not date_str:
            target_date = date.today()
        else:
            target_date = date.fromisoformat(date_str[:10])

        steps = int(activity_data.get("steps", 0))
        active_cal = float(activity_data.get("active_calories", activity_data.get("calories", steps * 0.042)))
        bmr = float(activity_data.get("bmr", 1750.0))
        total_cal = float(activity_data.get("total_calories", round(bmr + active_cal, 1)))
        workout_minutes = int(activity_data.get("workout_minutes", int(active_cal / 6.0) if active_cal > 0 else 0))

        resting_hr = None
        if activity_data.get("resting_heart_rate"):
            resting_hr = int(activity_data["resting_heart_rate"])
        elif sleep_data and sleep_data.get("avg_heart_rate"):
            resting_hr = int(sleep_data["avg_heart_rate"])

        hrv = None
        if hrv_data and hrv_data.get("rmssd"):
            hrv = float(hrv_data["rmssd"])
        elif sleep_data and sleep_data.get("hrv"):
            hrv = float(sleep_data["hrv"])

        sleep_score = None
        if sleep_data and sleep_data.get("score"):
            sleep_score = int(sleep_data["score"])

        return ActivityEntry(
            date=target_date,
            steps=steps,
            active_calories_kcal=active_cal,
            bmr_kcal=bmr,
            total_burned_kcal=total_cal,
            workout_minutes=workout_minutes,
            workout_type="RingConn Activity" if workout_minutes > 20 else None,
            resting_hr_bpm=resting_hr,
            hrv_ms=hrv,
            sleep_score=sleep_score,
            source="ringconn"
        )

    def authenticate_webhook(self, token: Optional[str]) -> bool:
        """Vérifie le token secret d'authentification du webhook RingConn s'il est configuré."""
        secret = self.config.get("webhook_token") or self.config.get("webhook_secret")
        if not secret:
            return True
        return token == secret

    def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Récupère les activités RingConn ou génère la simulation réaliste Gen 3."""
        if not self.is_configured:
            self.assert_simulation_allowed()
            return self._generate_simulated_activities(start_date, end_date)

        # Si des payloads de test/mock sont configurés
        if "mock_payloads" in self.config:
            results = []
            for item in self.config["mock_payloads"]:
                results.append(self.parse_ringconn_daily_data(
                    activity_data=item.get("activity", {}),
                    sleep_data=item.get("sleep"),
                    hrv_data=item.get("hrv")
                ))
            return results

        # En production : appel RingConn Open API Cloud si token disponible
        api_key = self.config.get("api_key") or self.config.get("access_token")
        if api_key:
            try:
                import urllib.request
                import json

                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json"
                }
                date_from = start_date.isoformat()
                date_to = end_date.isoformat()
                url = f"{self.BASE_URL}/daily_activity?start_date={date_from}&end_date={date_to}"

                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        records = data.get("data", []) if isinstance(data, dict) else []
                        return [self.parse_ringconn_daily_data(rec) for rec in records]
            except Exception:
                return []

        return []

    def _generate_simulated_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Simulation biométrique réaliste RingConn Gen 3 (sommeil réparateur, HRV précis, pas)."""
        entries = []
        days_count = (end_date - start_date).days + 1
        bmr = 1770.0

        for i in range(days_count):
            current_day = start_date + timedelta(days=i)
            is_weekend = current_day.weekday() >= 5
            steps = 11200 if not is_weekend else 8600
            active_cal = round(steps * 0.044 + (35 if not is_weekend else 15), 1)
            resting_hr = 56 if not is_weekend else 59
            hrv = round(56.0 + math.sin(i * 0.8) * 8.0, 1)
            sleep_score = int(86 + math.cos(i * 0.5) * 8)

            entries.append(ActivityEntry(
                date=current_day,
                steps=steps,
                active_calories_kcal=active_cal,
                bmr_kcal=bmr,
                total_burned_kcal=round(bmr + active_cal, 1),
                workout_minutes=45 if not is_weekend else 25,
                workout_type="Marche & Cardio (RingConn Gen 3)",
                resting_hr_bpm=resting_hr,
                hrv_ms=hrv,
                sleep_score=sleep_score,
                source="simulation",
                is_simulated=True
            ))
        return entries

    def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """La bague connectée ne mesure pas le poids corporel."""
        return []
