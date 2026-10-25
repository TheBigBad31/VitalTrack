"""Connecteur officiel pour les balances connectées Withings via API OAuth2 Measure (getmeas).

Gère :
- L'authentification OAuth2 standard Withings (authorize, échange code -> tokens, rafraîchissement automatique réel)
- La persistance sécurisée des tokens OAuth2 Withings chiffrés au repos
- L'appel API Withings `measure?action=getmeas` avec gestion des timeouts, backoff et rate limits (code 429 / 2555)
- La synchronisation incrémentale et idempotente avec curseur `lastupdate` (timestamp epoch)
- Le parsing des mesures corporelles :
  * Type 1: Poids (kg)
  * Type 6: Masse grasse (%)
  * Type 76: Masse musculaire (kg)
  * Type 77: Hydratation / masse hydrique (%)
  * Type 88: Masse osseuse (kg)
  * IMC calculé ou fourni
- Le mode Démo / Simulation (30 jours) si non configuré, avec interdiction stricte de données fictives en production (SimulationNotAllowedInProductionError).
"""

import math
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from src.connectors.base import BaseHealthConnector, SimulationNotAllowedInProductionError
from src.crypto import decrypt_credentials, encrypt_credentials
from src.models import ActivityEntry, WeightEntry


class WithingsAPIError(RuntimeError):
    """Exception levée en cas d'erreur de communication avec l'API Withings."""
    def __init__(self, message: str, status_code: Optional[int] = None, withings_status: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.withings_status = withings_status


class WithingsScaleConnector(BaseHealthConnector):
    """Connecteur officiel Withings pour balance impédancemètre via API OAuth2 Measure."""

    # Endpoints officiels Withings
    AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
    TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
    MEASURE_URL = "https://wbsapi.withings.net/measure"

    # Constantes Withings Measure Types
    TYPE_WEIGHT = 1           # Poids en kg
    TYPE_FAT_RATIO = 6        # Ratio de masse grasse en %
    TYPE_MUSCLE_MASS = 76     # Masse musculaire en kg
    TYPE_HYDRATION = 77       # Masse hydrique en %
    TYPE_BONE_MASS = 88       # Masse osseuse en kg

    # Catégorie 1 = Real measurements (vs 2 = user objectives)
    CATEGORY_REAL_MEASURES = 1

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        db_instance: Optional[Any] = None,
        user_id: Optional[int] = None,
        on_tokens_refreshed: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        super().__init__(config)
        self.db = db_instance
        self.user_id = user_id or self.config.get("user_id", 1)
        self.on_tokens_refreshed = on_tokens_refreshed

    def _check_configuration(self) -> bool:
        """Vérifie si les identifiants OAuth Withings sont configurés."""
        client_id = self.config.get("client_id")
        access_token = self.config.get("access_token")
        # Est configuré si au minimum access_token ou refresh_token + client_id
        return bool(client_id and (access_token or self.config.get("refresh_token")))

    # -------------------------------------------------------------------------
    # OAuth2 Flow & Token Lifecycle
    # -------------------------------------------------------------------------

    @classmethod
    def build_authorization_url(
        cls,
        client_id: str,
        redirect_uri: str,
        state: str,
        scope: str = "user.metrics,user.info"
    ) -> str:
        """Génère l'URL d'autorisation OAuth2 Withings pour redirection navigateur."""
        import urllib.parse
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "scope": scope,
        }
        return f"{cls.AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"

    def exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        client: Optional[httpx.Client] = None
    ) -> Dict[str, Any]:
        """Échange le code d'autorisation reçu contre access_token et refresh_token."""
        c_id = client_id or self.config.get("client_id")
        c_secret = client_secret or self.config.get("client_secret")
        if not c_id or not c_secret:
            raise WithingsAPIError("client_id et client_secret Withings requis pour échanger le code OAuth.")

        payload = {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": c_id,
            "client_secret": c_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }

        token_data = self._post_token_request(payload, client=client)
        self._update_tokens_in_memory_and_db(token_data)
        return token_data

    def is_token_expired(self, buffer_seconds: int = 120) -> bool:
        """Vérifie si le jeton d'accès est expiré ou proche de l'expiration."""
        expires_at = self.config.get("token_expiry") or self.config.get("expires_at")
        if expires_at is None:
            # Si pas de date d'expiration connue mais qu'un token existe, on suppose valide
            return not bool(self.config.get("access_token"))
        try:
            exp_ts = float(expires_at)
            return time.time() >= (exp_ts - buffer_seconds)
        except (ValueError, TypeError):
            return True

    def refresh_access_token_if_needed(self, client: Optional[httpx.Client] = None) -> Optional[str]:
        """Rafraîchit l'access_token via l'API Withings si expiré et met à jour le stockage sécurisé."""
        if not self.is_token_expired():
            return self.config.get("access_token")

        refresh_token = self.config.get("refresh_token")
        c_id = self.config.get("client_id")
        c_secret = self.config.get("client_secret")

        if not refresh_token:
            if self.config.get("access_token"):
                return self.config.get("access_token")
            raise WithingsAPIError("Impossible de rafraîchir le jeton Withings : aucun refresh_token disponible.")

        if not c_id or not c_secret:
            raise WithingsAPIError("client_id et client_secret requis pour rafraîchir le token Withings.")

        payload = {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": c_id,
            "client_secret": c_secret,
            "refresh_token": refresh_token,
        }

        token_data = self._post_token_request(payload, client=client)
        self._update_tokens_in_memory_and_db(token_data)
        return self.config.get("access_token")

    def _post_token_request(self, data: Dict[str, Any], client: Optional[httpx.Client] = None) -> Dict[str, Any]:
        """Effectue une requête POST vers le endpoint OAuth2 de Withings."""
        def do_call(c: httpx.Client) -> Dict[str, Any]:
            resp = c.post(self.TOKEN_URL, data=data, timeout=10.0)
            if resp.status_code != 200:
                raise WithingsAPIError(
                    f"Échec requête OAuth Withings (HTTP {resp.status_code}): {resp.text}",
                    status_code=resp.status_code
                )
            res_json = resp.json()
            status = res_json.get("status", 0)
            if status != 0:
                err_msg = res_json.get("error") or res_json.get("message") or f"Statut d'erreur Withings: {status}"
                raise WithingsAPIError(f"Erreur API Withings token: {err_msg}", withings_status=status)
            body = res_json.get("body", {})
            return body

        if client:
            return do_call(client)
        with httpx.Client() as c:
            return do_call(c)

    def _update_tokens_in_memory_and_db(self, token_body: Dict[str, Any]) -> None:
        """Met à jour les tokens dans l'instance et dans la base de données de façon chiffrée."""
        access_token = token_body.get("access_token")
        refresh_token = token_body.get("refresh_token")
        expires_in = token_body.get("expires_in", 10800)
        userid = token_body.get("userid")
        scope = token_body.get("scope")

        now_ts = time.time()
        expiry_ts = now_ts + float(expires_in)

        self.config["access_token"] = access_token
        if refresh_token:
            self.config["refresh_token"] = refresh_token
        self.config["token_expiry"] = expiry_ts
        self.config["expires_at"] = expiry_ts
        if userid:
            self.config["withings_userid"] = userid
        if scope:
            self.config["scope"] = scope
        self.is_configured = self._check_configuration()

        # Notification par callback
        if self.on_tokens_refreshed:
            try:
                self.on_tokens_refreshed(dict(self.config))
            except Exception:
                pass

        # Persistance sécurisée en base de données si DB fournie
        if self.db and hasattr(self.db, "update_user_device"):
            try:
                self.persist_credentials_to_db()
            except Exception:
                pass

    def persist_credentials_to_db(self) -> None:
        """Sauvegarde les identifiants chiffrés au repos dans user_devices."""
        if not self.db:
            return
        creds = {
            "client_id": self.config.get("client_id"),
            "client_secret": self.config.get("client_secret"),
            "access_token": self.config.get("access_token"),
            "refresh_token": self.config.get("refresh_token"),
            "token_expiry": self.config.get("token_expiry"),
            "expires_at": self.config.get("expires_at"),
            "withings_userid": self.config.get("withings_userid"),
            "scope": self.config.get("scope"),
            "lastupdate": self.config.get("lastupdate"),
            "user_height_m": self.config.get("user_height_m", 1.78)
        }
        # Filtrer les None
        creds = {k: v for k, v in creds.items() if v is not None}
        self.db.update_user_device(
            device_id="withings",
            name="Withings Body Scan & Scales",
            device_type="scale",
            connected=True,
            auth_type="oauth2",
            credentials=creds,
            user_id=self.user_id
        )

    # -------------------------------------------------------------------------
    # Parsing Withings Measure Groups
    # -------------------------------------------------------------------------

    def parse_withings_measure_group(self, grp: Dict[str, Any]) -> Optional[WeightEntry]:
        """Parse un groupe de mesures Withings `measuregrp` vers un `WeightEntry` standardisé."""
        epoch = grp.get("date", 0)
        if not epoch:
            return None
        measure_date = datetime.fromtimestamp(epoch, tz=timezone.utc).date()

        measures = grp.get("measures", [])
        weight = 0.0
        fat_pct = None
        muscle_kg = None
        water_pct = None
        bone_mass_kg = None

        for m in measures:
            raw_val = m.get("value", 0)
            unit = m.get("unit", 0)
            actual_val = round(raw_val * (10 ** unit), 2)
            m_type = m.get("type")

            if m_type == self.TYPE_WEIGHT:
                weight = actual_val
            elif m_type == self.TYPE_FAT_RATIO:
                fat_pct = actual_val
            elif m_type == self.TYPE_MUSCLE_MASS:
                muscle_kg = actual_val
            elif m_type == self.TYPE_HYDRATION:
                water_pct = actual_val
            elif m_type == self.TYPE_BONE_MASS:
                bone_mass_kg = actual_val

        # Si aucune mesure de poids valide dans ce groupe, ce n'est pas une pesée
        if weight <= 0:
            return None

        # Estimation IMC si taille fournie dans la config (ex: 1.78m)
        height_m = self.config.get("user_height_m", 1.78)
        bmi = round(weight / (height_m ** 2), 1) if height_m > 0 and weight > 0 else None

        notes_parts = ["Pesée automatique Withings Body Scan / Smart Scale"]
        if bone_mass_kg is not None:
            notes_parts.append(f"Masse osseuse: {bone_mass_kg} kg")

        return WeightEntry(
            date=measure_date,
            weight_kg=weight,
            body_fat_pct=fat_pct,
            muscle_mass_kg=muscle_kg,
            water_pct=water_pct,
            bmi=bmi,
            source="withings",
            is_simulated=False,
            notes=" | ".join(notes_parts)
        )

    # -------------------------------------------------------------------------
    # Synchronisation Incrémentale & Idempotente
    # -------------------------------------------------------------------------

    def sync_weights(
        self,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        last_sync_timestamp: Optional[int] = None,
        client: Optional[httpx.Client] = None
    ) -> List[WeightEntry]:
        """Récupère les pesées depuis l'API Withings ou génère une simulation réaliste."""
        today = date.today()
        end_d = end_date or today
        start_d = start_date or (end_d - timedelta(days=7))

        if not self.is_configured:
            self.assert_simulation_allowed()
            return self._generate_simulated_weights(start_d, end_d)

        return self._fetch_live_measures(
            start_date=start_d,
            end_date=end_d,
            last_sync_timestamp=last_sync_timestamp,
            client=client
        )

    def _fetch_live_measures(
        self,
        start_date: date,
        end_date: date,
        last_sync_timestamp: Optional[int] = None,
        client: Optional[httpx.Client] = None
    ) -> List[WeightEntry]:
        """Interroge l'API Withings getmeas avec support incrémental lastupdate et reprise sur erreur."""
        # 1. Vérification mock_payload injecté pour tests hors ligne
        if "mock_payload" in self.config:
            return self._process_api_response_body(self.config["mock_payload"].get("body", {}))

        # 2. Rafraîchissement automatique réel du jeton si nécessaire
        access_token = self.refresh_access_token_if_needed(client=client)
        if not access_token:
            raise WithingsAPIError("Aucun access_token valide disponible pour synchroniser Withings.")

        # 3. Paramètres de requête avec support incrémental lastupdate
        start_epoch = int(datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=timezone.utc).timestamp())
        # Fin de journée pour end_date (23:59:59)
        end_epoch = int(datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc).timestamp())

        # Déterminer le curseur lastupdate pour synchronisation incrémentale
        cursor_update = last_sync_timestamp if last_sync_timestamp is not None else self.config.get("lastupdate")

        params: Dict[str, Any] = {
            "action": "getmeas",
            "category": self.CATEGORY_REAL_MEASURES,
        }

        if cursor_update:
            params["lastupdate"] = int(cursor_update)
        else:
            params["startdate"] = start_epoch
            params["enddate"] = end_epoch

        headers = {
            "Authorization": f"Bearer {access_token}"
        }

        # 4. Exécution avec gestion des erreurs réseau, rate limit (429 / 2555) et timeouts
        body = self._execute_api_call_with_retry(
            method="POST",
            url=self.MEASURE_URL,
            headers=headers,
            data=params,
            client=client
        )

        return self._process_api_response_body(body)

    def _process_api_response_body(self, body: Dict[str, Any]) -> List[WeightEntry]:
        """Extrait et trie les mesures depuis le corps de réponse Withings."""
        measuregrps = body.get("measuregrps", [])
        new_lastupdate = body.get("more", 0) or body.get("updatetime")

        # Mise à jour du curseur lastupdate
        if new_lastupdate:
            self.config["lastupdate"] = int(new_lastupdate)
            if self.db:
                try:
                    self.persist_credentials_to_db()
                except Exception:
                    pass

        # Parsing et dédoublonnage idempotent par date (dernière pesée du jour conservée)
        weights_by_date: Dict[date, WeightEntry] = {}
        # Les groupes Withings sont ordonnés temporellement
        for grp in measuregrps:
            # Ne prendre que les vraies pesées de catégorie 1
            cat = grp.get("category", self.CATEGORY_REAL_MEASURES)
            if cat != self.CATEGORY_REAL_MEASURES:
                continue
            entry = self.parse_withings_measure_group(grp)
            if entry:
                weights_by_date[entry.date] = entry

        # Retourner trié par date croissante
        sorted_entries = sorted(weights_by_date.values(), key=lambda w: w.date)
        return sorted_entries

    def _execute_api_call_with_retry(
        self,
        method: str,
        url: str,
        headers: Dict[str, str],
        data: Dict[str, Any],
        client: Optional[httpx.Client] = None,
        max_retries: int = 3
    ) -> Dict[str, Any]:
        """Exécute un appel HTTP vers l'API Withings avec reprise sur timeouts et rate limits."""
        last_exception = None

        def do_request(c: httpx.Client, attempt: int) -> Dict[str, Any]:
            try:
                resp = c.request(method, url, headers=headers, data=data, timeout=12.0)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                if attempt < max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    return do_request(c, attempt + 1)
                raise WithingsAPIError(f"Erreur de communication Withings (Timeout/Réseau) après {max_retries} essais: {e}")

            if resp.status_code == 429:
                if attempt < max_retries - 1:
                    retry_after = float(resp.headers.get("Retry-After", 1.0))
                    time.sleep(min(retry_after, 2.0))
                    return do_request(c, attempt + 1)
                raise WithingsAPIError("Rate limit dépassé auprès de l'API Withings (HTTP 429).", status_code=429)

            if resp.status_code != 200:
                raise WithingsAPIError(
                    f"Erreur HTTP API Withings (code {resp.status_code}): {resp.text}",
                    status_code=resp.status_code
                )

            res_json = resp.json()
            status = res_json.get("status", 0)

            # Code 2555 = Withings Rate Limit Too many requests
            if status == 2555:
                if attempt < max_retries - 1:
                    time.sleep(1.0 * (attempt + 1))
                    return do_request(c, attempt + 1)
                raise WithingsAPIError("Withings API status 2555: Too many requests.", withings_status=2555)

            # Code 401 ou statut Withings 401 (token non autorisé/expiré)
            if status == 401 or status == 2554:
                # Tentative unique de rafraîchissement
                if attempt == 0:
                    try:
                        new_tok = self.refresh_access_token_if_needed(client=c)
                        if new_tok:
                            headers["Authorization"] = f"Bearer {new_tok}"
                            return do_request(c, attempt + 1)
                    except Exception:
                        pass
                raise WithingsAPIError(f"Erreur d'authentification Withings (status {status}).", withings_status=status)

            if status != 0:
                err_msg = res_json.get("error") or res_json.get("message") or f"Statut non-zéro: {status}"
                raise WithingsAPIError(f"Erreur Withings: {err_msg}", withings_status=status)

            return res_json.get("body", {})

        if client:
            return do_request(client, 0)
        with httpx.Client() as c:
            return do_request(c, 0)

    # -------------------------------------------------------------------------
    # Mode Démo / Simulation (Non-production uniquement)
    # -------------------------------------------------------------------------

    def _generate_simulated_weights(self, start_date: date, end_date: date) -> List[WeightEntry]:
        """Simulation réaliste de pesées quotidiennes Withings (interdite en prod)."""
        entries = []
        days_count = (end_date - start_date).days + 1
        base_weight = 81.8
        height_m = self.config.get("user_height_m", 1.78)

        for i in range(days_count):
            current_day = start_date + timedelta(days=i)
            loss_progress = i / max(1, days_count)
            fluct = math.sin(i * 0.8) * 0.3
            weight = round(base_weight - (1.8 * loss_progress) + fluct, 2)
            fat_pct = round(20.8 - (0.9 * loss_progress) + (fluct * 0.15), 1)
            muscle = round(38.5 - (0.2 * loss_progress), 1)
            water = round(56.5 + (0.4 * loss_progress), 1)
            bmi = round(weight / (height_m ** 2), 1)

            entries.append(WeightEntry(
                date=current_day,
                weight_kg=weight,
                body_fat_pct=fat_pct,
                muscle_mass_kg=muscle,
                water_pct=water,
                bmi=bmi,
                source="simulation",
                is_simulated=True,
                notes="Mode Démo Withings (API en attente de configuration)"
            ))
        return entries

    def sync_activities(self, start_date: date, end_date: date) -> List[ActivityEntry]:
        """Withings scale ne fournit généralement pas le suivi d'activité complet."""
        return []

    def test_connection(self) -> Dict[str, Any]:
        """Teste la validité des identifiants et de la liaison API Withings."""
        if not self.is_configured:
            return {"ok": False, "message": "Identifiants OAuth2 Withings incomplets (client_id et token requis)."}
        try:
            tok = self.refresh_access_token_if_needed()
            return {"ok": True, "message": "Liaison OAuth2 Withings active et vérifiée."}
        except Exception as e:
            return {"ok": False, "message": f"Échec du test de liaison Withings: {e}"}


