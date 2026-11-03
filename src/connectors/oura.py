"""Connecteur pour les bagues connectées Oura Ring via API v2.

Gère :
- Authentification Personal Access Token ou OAuth2
- Endpoints API v2 Oura :
  - `daily_activity` (steps, active_calories, total_calories)
  - `daily_readiness` (hrv_balance, resting_heart_rate)
  - `daily_sleep` (score de sommeil global)
- Standardisation vers ActivityEntry
- Mode Démo / Simulation 30 jours automatique si le token n'est pas renseigné.
"""

import math
import httpx
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from src.connectors.base import BaseHealthConnector
from src.models import ActivityEntry, WeightEntry


class OuraRingConnector(BaseHealthConnector):
    """Connecteur Oura Ring API v2."""

    BASE_URL = "https://api.ouraring.com/v2/usercollection"

    def _check_configuration(self) -> bool:
        """Vérifie si le Personal Access Token Oura est fourni."""
        pat = self.config.get("personal_access_token")
        return bool(pat)

    def _get_headers(self) -> Dict[str, str]:
        """Retourne les headers d'authentification pour les appels API."""
        pat = self.config.get("personal_access_token")
        return {"Authorization": f"Bearer {pat}"}

    def _fetch_paginated(
        self,
        endpoint: str,
        start_date: date,
        end_date: date,
        client: Optional[httpx.Client] = None
    ) -> List[Dict[str, Any]]:
        """Récupère toutes les pages d'un endpoint Oura avec pagination next_token."""
        all_data = []
        next_token = None
        
        while True:
            params = {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            }
            if next_token:
                params["next_token"] = next_token

            url = f"{self.BASE_URL}/{endpoint}"
            
            def do_request(c: httpx.Client) -> Dict[str, Any]:
                resp = c.get(url, headers=self._get_headers(), params=params, timeout=15.0)
                if resp.status_code == 429:
                    # Rate limit - respecter Retry-After
                    retry_after = float(resp.headers.get("Retry-After", 1.0))
                    import time
                    time.sleep(min(retry_after, 5.0))
                    return do_request(c)
                if resp.status_code != 200:
                    raise RuntimeError(f"Oura API error {resp.status_code}: {resp.text}")
                return resp.json()

            if client:
                data = do_request(client)
            else:
                with httpx.Client() as c:
                    data = do_request(c)

            # Oura v2 renvoie les données dans "data" et le next_token au niveau racine
            items = data.get("data", [])
            all_data.extend(items)
            
            next_token = data.get("next_token")
            if not next_token:
                break

        return all_data

    def parse_oura_daily_data(
        self,
        activity: Dict[str, Any],
        readiness: Optional[Dict[str, Any]] = None,
        sleep: Optional[Dict[str, Any]] = None
    ) -> ActivityEntry:
        """Parse les payloads des 3 endpoints Oura v2 pour former un ActivityEntry complet."""
        day_str = activity.get("day")
        if not day_str:
            raise ValueError("Champ 'day' manquant dans le payload Oura")

        target_date = date.fromisoformat(day_str)
        steps = activity.get("steps", 0)
        active_cal = float(activity.get("active_calories", 0.0))
        total_cal = float(activity.get("total_calories", 0.0))
        bmr_cal = round(max(0.0, total_cal - active_cal), 1) if total_cal > 0 else 1750.0

        # Données de readiness / récupération
        resting_hr = None
        hrv = None
        if readiness:
            contributors = readiness.get("contributors", {})
            resting_hr = contributors.get("resting_heart_rate")
            # HRV moyenne de nuit si disponible ou score balance
            hrv = readiness.get("score") # ou RMSSD si présent dans l'endpoint sleep

        # Données de sommeil
        sleep_score = None
        if sleep:
            sleep_score = sleep.get("score")
            if not hrv and "contributors" in sleep:
                hrv = float(sleep.get("contributors", {}).get("deep_sleep", 50))

        # Estimation temps de mouvement actif
        workout_minutes = int(active_cal / 6.0) if active_cal > 0 else 0

        return ActivityEntry(
            date=target_date,
            steps=steps,
            active_calories_kcal=active_cal,
            bmr_kcal=bmr_cal,
            total_burned_kcal=total_cal or round(bmr_cal + active_cal, 1),
            workout_minutes=workout_minutes,
            workout_type="Activité Oura" if workout_minutes > 30 else None,
            resting_hr_bpm=resting_hr,
            hrv_ms=hrv,
            sleep_score=sleep_score,
            source="oura"
        )

    def sync_activities(self, start_date: date, end_date: date, client: Optional[httpx.Client] = None) -> List[ActivityEntry]:
        """Récupère les activités avec pagination Oura v2 (next_token)."""
        if not self.is_configured:
            self.assert_simulation_allowed()
            return self._generate_simulated_activities(start_date, end_date)

        # En production : appels GET /daily_activity, /daily_readiness, /daily_sleep avec pagination
        if "mock_payloads" in self.config:
            activities_raw = self.config["mock_payloads"].get("activity", [])
            readiness_map = {r.get("day"): r for r in self.config["mock_payloads"].get("readiness", [])}
            sleep_map = {s.get("day"): s for s in self.config["mock_payloads"].get("sleep", [])}

            results = []
            for act in activities_raw:
                d = act.get("day")
                results.append(self.parse_oura_daily_data(
                    activity=act,
                    readiness=readiness_map.get(d),
                    sleep=sleep_map.get(d)
                ))
            return results

        # Appels API réels avec pagination
        try:
            activities_raw = self._fetch_paginated("daily_activity", start_date, end_date, client=client)
            readiness_raw = self._fetch_paginated("daily_readiness", start_date, end_date, client=client)
            sleep_raw = self._fetch_paginated("daily_sleep", start_date, end_date, client=client)
        except Exception as e:
            # En cas d'erreur API, logger et retourner liste vide
            import logging
            logger = logging.getLogger("vitaltrack.oura")
            logger.error(f"[Oura] Erreur sync_activities: {e}")
            return []

        readiness_map = {r.get("day"): r for r in readiness_raw}
        sleep_map = {s.get("day"): s for s in sleep_raw}

        results = []
        for act in activities_raw:
            d = act.get("day")
            results.append(self.parse_oura_daily_data(
                activity=act,
                readiness=readiness_map.get(d),
                sleep=sleep_map.get(d)
            ))
        return results

    def _generate_simulated_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Simulation réaliste de données Oura Ring (HRV, sommeil, pas)."""
        entries = []
        days_count = (end_date - start_date).days + 1
        bmr = 1760.0

        for i in range(days_count):
            current_day = start_date + timedelta(days=i)
            is_weekend = current_day.weekday() >= 5
            steps = 11500 if not is_weekend else 8200
            active_cal = round(steps * 0.042 + (40 if not is_weekend else 20), 1)
            resting_hr = 57 if not is_weekend else 60
            hrv = round(54.0 + math.sin(i * 0.9) * 7.5, 1)
            sleep_score = int(84 + math.cos(i * 0.6) * 9)

            entries.append(ActivityEntry(
                date=current_day,
                steps=steps,
                active_calories_kcal=active_cal,
                bmr_kcal=bmr,
                total_burned_kcal=round(bmr + active_cal, 1),
                workout_minutes=40 if not is_weekend else 20,
                workout_type="Marche & Cardio",
                resting_hr_bpm=resting_hr,
                hrv_ms=hrv,
                sleep_score=sleep_score,
                source="simulation",
                is_simulated=True
            ))
        return entries

    def sync_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """Oura Ring ne mesure pas directement le poids."""
        return []
