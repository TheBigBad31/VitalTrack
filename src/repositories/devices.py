"""Repository pour la gestion des appareils connectés (IoT, balances, bagues, traceurs)."""

import hashlib
import hmac
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.crypto import decrypt_credentials, decrypt_data, encrypt_credentials, encrypt_data
from src.repositories.base import BaseRepository


class DevicesRepository(BaseRepository):
    """Gestion des appareils connectés, tokens de synchronisation et identifiants chiffrés."""

    def _format_device_row(self, row: Optional[Dict[str, Any]], reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Formate et protège une ligne d'appareil en chiffrant/déchiffrant les identifiants au besoin."""
        if not row:
            return None
        d = dict(row)
        d["connected"] = bool(d.get("connected"))
        d["is_active"] = bool(d.get("is_active", 1))
        d["sync_status"] = d.get("sync_status") or ("connected" if d["connected"] else "disconnected")
        d["last_sync_at"] = d.get("last_sync_at") or d.get("last_sync")

        enc_cred = d.get("encrypted_credentials")
        if enc_cred:
            creds = decrypt_credentials(enc_cred)
        elif d.get("api_key"):
            raw_k = decrypt_data(d["api_key"])
            creds = {"api_key": raw_k} if raw_k else {}
        else:
            creds = {}

        if reveal_secrets:
            d["credentials"] = creds
        else:
            d.pop("encrypted_credentials", None)
            d.pop("api_key", None)
            d["has_credentials"] = bool(creds)
            if creds.get("api_key"):
                raw_k = str(creds["api_key"])
                d["api_key_masked"] = f"{raw_k[:4]}...{raw_k[-4:]}" if len(raw_k) > 8 else "***"
        return d

    @staticmethod
    def decrypt_device_credentials(encrypted_str: Optional[str]) -> Dict[str, Any]:
        """Déchiffre les identifiants d'appareil (wrapper vers src.crypto)."""
        return decrypt_credentials(encrypted_str)

    def get_user_devices(self, user_id: int = 1, reveal_secrets: bool = False) -> List[Dict[str, Any]]:
        """Récupère les objets connectés associés à user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            rows = cursor.fetchall()
        return [self._format_device_row(r, reveal_secrets=reveal_secrets) for r in rows]

    def get_user_device(self, device_id: str, user_id: int = 1, reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Récupère un objet connecté spécifique pour un user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ? LIMIT 1", (user_id, device_id))
            row = cursor.fetchone()
        return self._format_device_row(row, reveal_secrets=reveal_secrets)

    def find_user_by_device_token(self, token: str, device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Identifie l'utilisateur et l'appareil associés à un token ou webhook secret dans user_devices.
        
        Effectue une recherche prioritaire indexée par api_key_hash (SHA-256), puis fallback direct / credentials.
        """
        if not token or not str(token).strip():
            return None
        token_clean = str(token).strip()
        token_hash = hashlib.sha256(token_clean.encode("utf-8")).hexdigest()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if device_id:
                cursor.execute(
                    "SELECT * FROM user_devices WHERE is_active = 1 AND device_id = ? AND api_key_hash = ? LIMIT 1",
                    (device_id, token_hash)
                )
            else:
                cursor.execute(
                    "SELECT * FROM user_devices WHERE is_active = 1 AND api_key_hash = ? LIMIT 1",
                    (token_hash,)
                )
            row = cursor.fetchone()
            if row:
                formatted = self._format_device_row(row, reveal_secrets=True)
                user_id = row["user_id"] if isinstance(row, dict) else row[1]
                user = self.db.get_user_by_id(int(user_id))
                return {
                    "user_id": int(user_id),
                    "user": user,
                    "device": formatted
                }

            if device_id:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND device_id = ? AND encrypted_credentials IS NOT NULL", (device_id,))
            else:
                cursor.execute("SELECT * FROM user_devices WHERE is_active = 1 AND encrypted_credentials IS NOT NULL")
            rows = cursor.fetchall()

        for r in rows:
            formatted = self._format_device_row(r, reveal_secrets=True)
            if not formatted:
                continue
            creds = formatted.get("credentials") or {}
            matched = False
            for key in ["api_key", "webhook_secret", "token", "bearer_token", "webhook_token"]:
                val = creds.get(key)
                if val and hmac.compare_digest(str(val).strip(), token_clean):
                    matched = True
                    break

            if matched:
                user_id = r["user_id"] if isinstance(r, dict) else r[1]
                try:
                    dev_id = r["device_id"] if isinstance(r, dict) else r[2]
                    with self.get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE user_devices SET api_key_hash = ? WHERE user_id = ? AND device_id = ?",
                            (token_hash, user_id, dev_id)
                        )
                        conn.commit()
                except Exception:
                    pass

                user = self.db.get_user_by_id(int(user_id))
                return {
                    "user_id": int(user_id),
                    "user": user,
                    "device": formatted
                }

        return None

    def find_user_device_by_token(self, token: str) -> Optional[Dict[str, Any]]:
        """Compatibilité Lot 1.1 : renvoie le dict de l'appareil (avec user_id inclus)."""
        res = self.find_user_by_device_token(token)
        if res and res.get("device"):
            dev = dict(res["device"])
            dev["user_id"] = res["user_id"]
            return dev
        return None

    def generate_device_token(
        self,
        device_id: str,
        name: Optional[str] = None,
        device_type: Optional[str] = None,
        user_id: int = 1
    ) -> Dict[str, Any]:
        """Génère un token secret individuel sécurisé pour un appareil/pont mobile et l'enregistre chiffré."""
        raw_token = f"vt_{device_id}_{secrets.token_urlsafe(24)}"
        dev_name = name or device_id.replace("_", " ").title()
        dev_type = device_type or ("ring" if "ring" in device_id else ("scale" if "scale" in device_id or "withings" in device_id else "mobile_aggregator"))

        existing = self.get_user_device(device_id, user_id=user_id, reveal_secrets=True)
        creds = dict(existing.get("credentials", {})) if existing and existing.get("credentials") else {}
        creds["api_key"] = raw_token
        creds["webhook_token"] = raw_token

        updated = self.update_user_device(
            device_id=device_id,
            name=dev_name,
            device_type=dev_type,
            connected=True,
            auth_type="webhook",
            api_key=raw_token,
            credentials=creds,
            user_id=user_id
        )

        res = dict(updated)
        res["token"] = raw_token
        res["device_token"] = raw_token
        return res

    def delete_user_device(self, device_id: str, user_id: int = 1) -> bool:
        """Déconnecte et révoque un objet connecté pour un user_id en supprimant la ligne et les identifiants chiffrés."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
            deleted = cursor.rowcount > 0
            conn.commit()
        return deleted

    def update_device_sync_status(self, device_id: str, sync_status: str, user_id: int = 1) -> Optional[Dict[str, Any]]:
        """Met à jour le statut temps réel et l'horodatage de dernière synchronisation."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_devices
                SET sync_status = ?, last_sync = ?, last_sync_at = ?, updated_at = ?
                WHERE user_id = ? AND device_id = ?
            """, (sync_status, now_str, now_str, now_str, user_id, device_id))
            conn.commit()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
            row = cursor.fetchone()
        return self._format_device_row(row, reveal_secrets=False)

    def update_user_device(
        self,
        device_id: str,
        name: str,
        device_type: str,
        connected: bool,
        auth_type: str = "connected",
        api_key: Optional[str] = None,
        credentials: Optional[Dict[str, Any]] = None,
        account_email: Optional[str] = None,
        is_active: bool = True,
        sync_status: Optional[str] = None,
        user_id: int = 1
    ) -> Dict[str, Any]:
        """Enregistre ou met à jour un objet connecté pour user_id avec chiffrement au repos."""
        now_str = datetime.now(timezone.utc).isoformat()
        if sync_status is None:
            sync_status = "connected" if connected else "disconnected"

        creds_to_encrypt = dict(credentials) if credentials else {}
        if api_key and "api_key" not in creds_to_encrypt:
            creds_to_encrypt["api_key"] = api_key

        encrypted_credentials = encrypt_credentials(creds_to_encrypt) if creds_to_encrypt else None
        enc_api_key = encrypt_data(api_key) if api_key else None
        
        api_key_hash = None
        key_to_hash = api_key or creds_to_encrypt.get("api_key") or creds_to_encrypt.get("webhook_token") or creds_to_encrypt.get("token")
        if key_to_hash and str(key_to_hash).strip():
            api_key_hash = hashlib.sha256(str(key_to_hash).strip().encode("utf-8")).hexdigest()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, api_key_hash, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        device_type = EXCLUDED.device_type,
                        connected = EXCLUDED.connected,
                        auth_type = EXCLUDED.auth_type,
                        api_key = COALESCE(EXCLUDED.api_key, user_devices.api_key),
                        api_key_hash = COALESCE(EXCLUDED.api_key_hash, user_devices.api_key_hash),
                        encrypted_credentials = COALESCE(EXCLUDED.encrypted_credentials, user_devices.encrypted_credentials),
                        account_email = COALESCE(EXCLUDED.account_email, user_devices.account_email),
                        is_active = EXCLUDED.is_active,
                        last_sync = EXCLUDED.last_sync,
                        last_sync_at = EXCLUDED.last_sync_at,
                        sync_status = EXCLUDED.sync_status,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *;
                """, (
                    user_id, device_id, name, device_type, 1 if connected else 0, auth_type,
                    enc_api_key, api_key_hash, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                row = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, api_key_hash, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = excluded.name,
                        device_type = excluded.device_type,
                        connected = excluded.connected,
                        auth_type = excluded.auth_type,
                        api_key = COALESCE(excluded.api_key, user_devices.api_key),
                        api_key_hash = COALESCE(excluded.api_key_hash, user_devices.api_key_hash),
                        encrypted_credentials = COALESCE(excluded.encrypted_credentials, user_devices.encrypted_credentials),
                        account_email = COALESCE(excluded.account_email, user_devices.account_email),
                        is_active = excluded.is_active,
                        last_sync = excluded.last_sync,
                        last_sync_at = excluded.last_sync_at,
                        sync_status = excluded.sync_status,
                        updated_at = excluded.updated_at
                """, (
                    user_id, device_id, name, device_type, 1 if connected else 0, auth_type,
                    enc_api_key, api_key_hash, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                conn.commit()
                cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
                row = cursor.fetchone()
            conn.commit()
        return self._format_device_row(row, reveal_secrets=False)

    def get_devices_data_map(self, user_id: int = 1) -> Dict[str, Any]:
        """Retourne la cartographie complète des données connectées pour l'utilisateur :
        - Pour chaque source (health_connect, withings, ringconn, oura, manual) et chaque type de métrique :
          lu côté connecteur (oui/non), stocké en BDD (table), rendu dans l'UI (oui/non + où),
          dernier point reçu (date + valeur), nb points sur 7j.
        - Dernier sync/push par device (user_devices.last_sync_at si existe, sinon depuis raw_ingest).
        - Diagnostic détaillé et liste centralisée de la source des pesées récentes (Withings vs Health Connect).
        """
        now = datetime.now(timezone.utc)
        seven_days_ago_date = (now - timedelta(days=7)).date().isoformat()
        seven_days_ago_iso = (now - timedelta(days=7)).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Objets connectés de l'utilisateur
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ?", (user_id,))
            user_devices_rows = cursor.fetchall()
            devices_by_id: Dict[str, Dict[str, Any]] = {}
            for r in user_devices_rows:
                fmt = self._format_device_row(r)
                if fmt:
                    devices_by_id[fmt["device_id"]] = fmt

            # 2. Raw ingest (pour dernier push et métriques brutes comme masse osseuse)
            cursor.execute(
                "SELECT source, received_at, payload_json FROM raw_ingest WHERE user_id = ? ORDER BY received_at DESC LIMIT 500",
                (user_id,)
            )
            raw_ingest_rows = cursor.fetchall()
            latest_raw_ingest: Dict[str, str] = {}
            has_raw_bone_mass = False
            latest_raw_bone_mass: Optional[Dict[str, Any]] = None
            raw_bone_mass_7d = 0

            for r in raw_ingest_rows:
                src_norm = normalize_source_name(r.get("source"))
                rec_at = r.get("received_at")
                if src_norm not in latest_raw_ingest and rec_at:
                    latest_raw_ingest[src_norm] = rec_at

                p_str = str(r.get("payload_json", "")).lower()
                if "bone" in p_str:
                    has_raw_bone_mass = True
                    if not latest_raw_bone_mass and rec_at:
                        latest_raw_bone_mass = {
                            "date": rec_at[:10],
                            "value": "Ingéré (payload JSON)",
                            "measured_at": rec_at,
                            "unit": "kg"
                        }
                    if rec_at and rec_at >= seven_days_ago_iso:
                        raw_bone_mass_7d += 1

            # 3. Pesées et composition corporelle
            cursor.execute(
                "SELECT id, date, measured_at, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, bmi, source, external_id, created_at "
                "FROM weights WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,)
            )
            weights_rows = cursor.fetchall()

            # 4. Métriques quotidiennes unifiées
            cursor.execute(
                "SELECT id, date, source, steps, active_calories_kcal, total_calories_kcal, resting_hr_bpm, hrv_rmssd_ms, hrv_sdnn_ms, spo2_pct, skin_temperature_c, sleep_score, recovery_score "
                "FROM daily_metrics WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,)
            )
            daily_metrics_rows = cursor.fetchall()

            # 5. Activités (support enrichi legacy / syncs)
            cursor.execute(
                "SELECT id, date, source, steps, active_calories_kcal, resting_hr_bpm, hrv_ms, sleep_score, workout_minutes "
                "FROM activities WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,)
            )
            activities_rows = cursor.fetchall()

            # 6. Sessions de sommeil
            cursor.execute(
                "SELECT id, source, date, start_time, duration_minutes, sleep_score FROM sleep_sessions WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,)
            )
            sleep_rows = cursor.fetchall()

            # 7. Workouts
            cursor.execute(
                "SELECT id, source, workout_type, start_time, duration_minutes, calories_kcal FROM workouts WHERE user_id = ? ORDER BY start_time DESC, id DESC",
                (user_id,)
            )
            workouts_rows = cursor.fetchall()

            # 8. Logs d'hydratation
            cursor.execute(
                "SELECT id, source, date, timestamp, volume_ml FROM hydration_logs WHERE user_id = ? ORDER BY date DESC, id DESC",
                (user_id,)
            )
            hydration_rows = cursor.fetchall()

            # 9. Échantillons intraday
            cursor.execute(
                "SELECT id, source, metric_type, timestamp, value FROM intraday_samples WHERE user_id = ? ORDER BY timestamp DESC LIMIT 500",
                (user_id,)
            )
            intraday_rows = cursor.fetchall()

        # Dictionnaires pour stocker les derniers points et compteurs 7j par (metric_key, source)
        latest_points: Dict[str, Dict[str, Dict[str, Any]]] = {m["key"]: {} for m in METRIC_DEFINITIONS}
        counts_7d: Dict[str, Dict[str, int]] = {m["key"]: {} for m in METRIC_DEFINITIONS}
        latest_activity_date_by_source: Dict[str, str] = {}

        # Traitement des pesées
        weights_count_by_source: Dict[str, int] = {src: 0 for src in CANONICAL_SOURCES}
        formatted_recent_weights: List[Dict[str, Any]] = []

        for w in weights_rows:
            raw_src = str(w.get("source") or "manual")
            src_norm = normalize_source_name(raw_src)
            d_str = str(w.get("date") or "")[:10]
            meas_at = w.get("measured_at")
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            weights_count_by_source[src_norm] = weights_count_by_source.get(src_norm, 0) + 1
            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if len(formatted_recent_weights) < 25:
                formatted_recent_weights.append({
                    "id": w.get("id"),
                    "date": d_str,
                    "measured_at": meas_at,
                    "weight_kg": float(w["weight_kg"]) if w.get("weight_kg") is not None else None,
                    "body_fat_pct": float(w["body_fat_pct"]) if w.get("body_fat_pct") is not None else None,
                    "muscle_mass_kg": float(w["muscle_mass_kg"]) if w.get("muscle_mass_kg") is not None else None,
                    "water_pct": float(w["water_pct"]) if w.get("water_pct") is not None else None,
                    "bmi": float(w["bmi"]) if w.get("bmi") is not None else None,
                    "source": raw_src,
                    "source_normalized": src_norm,
                    "external_id": w.get("external_id")
                })

            # Poids
            if w.get("weight_kg") is not None and float(w["weight_kg"]) > 0:
                if src_norm not in latest_points["weight"]:
                    latest_points["weight"][src_norm] = {
                        "date": d_str,
                        "value": round(float(w["weight_kg"]), 2),
                        "measured_at": meas_at,
                        "unit": "kg"
                    }
                if is_7d:
                    counts_7d["weight"][src_norm] = counts_7d["weight"].get(src_norm, 0) + 1

            # Masse grasse %
            if w.get("body_fat_pct") is not None and float(w["body_fat_pct"]) > 0:
                if src_norm not in latest_points["body_fat_pct"]:
                    latest_points["body_fat_pct"][src_norm] = {
                        "date": d_str,
                        "value": round(float(w["body_fat_pct"]), 1),
                        "measured_at": meas_at,
                        "unit": "%"
                    }
                if is_7d:
                    counts_7d["body_fat_pct"][src_norm] = counts_7d["body_fat_pct"].get(src_norm, 0) + 1

            # Masse musculaire kg
            if w.get("muscle_mass_kg") is not None and float(w["muscle_mass_kg"]) > 0:
                if src_norm not in latest_points["muscle_mass_kg"]:
                    latest_points["muscle_mass_kg"][src_norm] = {
                        "date": d_str,
                        "value": round(float(w["muscle_mass_kg"]), 2),
                        "measured_at": meas_at,
                        "unit": "kg"
                    }
                if is_7d:
                    counts_7d["muscle_mass_kg"][src_norm] = counts_7d["muscle_mass_kg"].get(src_norm, 0) + 1

            # Eau %
            if w.get("water_pct") is not None and float(w["water_pct"]) > 0:
                if src_norm not in latest_points["water_pct"]:
                    latest_points["water_pct"][src_norm] = {
                        "date": d_str,
                        "value": round(float(w["water_pct"]), 1),
                        "measured_at": meas_at,
                        "unit": "%"
                    }
                if is_7d:
                    counts_7d["water_pct"][src_norm] = counts_7d["water_pct"].get(src_norm, 0) + 1

            # IMC
            if w.get("bmi") is not None and float(w["bmi"]) > 0:
                if src_norm not in latest_points["bmi"]:
                    latest_points["bmi"][src_norm] = {
                        "date": d_str,
                        "value": round(float(w["bmi"]), 1),
                        "measured_at": meas_at,
                        "unit": "kg/m²"
                    }
                if is_7d:
                    counts_7d["bmi"][src_norm] = counts_7d["bmi"].get(src_norm, 0) + 1

        # Masse osseuse (si présente dans raw_ingest)
        if has_raw_bone_mass and latest_raw_bone_mass:
            latest_points["bone_mass_kg"]["health_connect"] = latest_raw_bone_mass
            counts_7d["bone_mass_kg"]["health_connect"] = raw_bone_mass_7d

        # Traitement de daily_metrics
        for dm in daily_metrics_rows:
            raw_src = str(dm.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            d_str = str(dm.get("date") or "")[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            # Pas
            if dm.get("steps") is not None and int(dm["steps"]) > 0:
                if src_norm not in latest_points["steps"]:
                    latest_points["steps"][src_norm] = {"date": d_str, "value": int(dm["steps"]), "unit": "pas"}
                if is_7d:
                    counts_7d["steps"][src_norm] = counts_7d["steps"].get(src_norm, 0) + 1

            # Calories actives
            if dm.get("active_calories_kcal") is not None and float(dm["active_calories_kcal"]) > 0:
                if src_norm not in latest_points["active_calories_kcal"]:
                    latest_points["active_calories_kcal"][src_norm] = {"date": d_str, "value": round(float(dm["active_calories_kcal"]), 1), "unit": "kcal"}
                if is_7d:
                    counts_7d["active_calories_kcal"][src_norm] = counts_7d["active_calories_kcal"].get(src_norm, 0) + 1

            # FC repos
            if dm.get("resting_hr_bpm") is not None and int(dm["resting_hr_bpm"]) > 0:
                if src_norm not in latest_points["resting_hr_bpm"]:
                    latest_points["resting_hr_bpm"][src_norm] = {"date": d_str, "value": int(dm["resting_hr_bpm"]), "unit": "bpm"}
                if is_7d:
                    counts_7d["resting_hr_bpm"][src_norm] = counts_7d["resting_hr_bpm"].get(src_norm, 0) + 1

            # HRV RMSSD
            if dm.get("hrv_rmssd_ms") is not None and float(dm["hrv_rmssd_ms"]) > 0:
                if src_norm not in latest_points["hrv_rmssd_ms"]:
                    latest_points["hrv_rmssd_ms"][src_norm] = {"date": d_str, "value": round(float(dm["hrv_rmssd_ms"]), 1), "unit": "ms"}
                if is_7d:
                    counts_7d["hrv_rmssd_ms"][src_norm] = counts_7d["hrv_rmssd_ms"].get(src_norm, 0) + 1

            # SpO2
            if dm.get("spo2_pct") is not None and float(dm["spo2_pct"]) > 0:
                if src_norm not in latest_points["spo2_pct"]:
                    latest_points["spo2_pct"][src_norm] = {"date": d_str, "value": round(float(dm["spo2_pct"]), 1), "unit": "%"}
                if is_7d:
                    counts_7d["spo2_pct"][src_norm] = counts_7d["spo2_pct"].get(src_norm, 0) + 1

            # Température peau
            if dm.get("skin_temperature_c") is not None and float(dm["skin_temperature_c"]) > 0:
                if src_norm not in latest_points["skin_temperature_c"]:
                    latest_points["skin_temperature_c"][src_norm] = {"date": d_str, "value": round(float(dm["skin_temperature_c"]), 1), "unit": "°C"}
                if is_7d:
                    counts_7d["skin_temperature_c"][src_norm] = counts_7d["skin_temperature_c"].get(src_norm, 0) + 1

            # HRV SDNN
            if dm.get("hrv_sdnn_ms") is not None and float(dm["hrv_sdnn_ms"]) > 0:
                if src_norm not in latest_points["hrv_sdnn_ms"]:
                    latest_points["hrv_sdnn_ms"][src_norm] = {"date": d_str, "value": round(float(dm["hrv_sdnn_ms"]), 1), "unit": "ms"}
                if is_7d:
                    counts_7d["hrv_sdnn_ms"][src_norm] = counts_7d["hrv_sdnn_ms"].get(src_norm, 0) + 1

            # Sommeil (score)
            if dm.get("sleep_score") is not None and int(dm["sleep_score"]) > 0:
                if src_norm not in latest_points["sleep"]:
                    latest_points["sleep"][src_norm] = {"date": d_str, "value": f"{int(dm['sleep_score'])}/100", "unit": "score"}
                if is_7d:
                    counts_7d["sleep"][src_norm] = counts_7d["sleep"].get(src_norm, 0) + 1

        # Traitement de fallback via activities
        for act in activities_rows:
            raw_src = str(act.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            d_str = str(act.get("date") or "")[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if act.get("steps") is not None and int(act["steps"]) > 0:
                if src_norm not in latest_points["steps"]:
                    latest_points["steps"][src_norm] = {"date": d_str, "value": int(act["steps"]), "unit": "pas"}
                if is_7d and src_norm not in counts_7d["steps"]:
                    counts_7d["steps"][src_norm] = counts_7d["steps"].get(src_norm, 0) + 1

            if act.get("active_calories_kcal") is not None and float(act["active_calories_kcal"]) > 0:
                if src_norm not in latest_points["active_calories_kcal"]:
                    latest_points["active_calories_kcal"][src_norm] = {"date": d_str, "value": round(float(act["active_calories_kcal"]), 1), "unit": "kcal"}
                if is_7d and src_norm not in counts_7d["active_calories_kcal"]:
                    counts_7d["active_calories_kcal"][src_norm] = counts_7d["active_calories_kcal"].get(src_norm, 0) + 1

            if act.get("resting_hr_bpm") is not None and int(act["resting_hr_bpm"]) > 0:
                if src_norm not in latest_points["resting_hr_bpm"]:
                    latest_points["resting_hr_bpm"][src_norm] = {"date": d_str, "value": int(act["resting_hr_bpm"]), "unit": "bpm"}
                if is_7d and src_norm not in counts_7d["resting_hr_bpm"]:
                    counts_7d["resting_hr_bpm"][src_norm] = counts_7d["resting_hr_bpm"].get(src_norm, 0) + 1

            if act.get("hrv_ms") is not None and float(act["hrv_ms"]) > 0:
                if src_norm not in latest_points["hrv_rmssd_ms"]:
                    latest_points["hrv_rmssd_ms"][src_norm] = {"date": d_str, "value": round(float(act["hrv_ms"]), 1), "unit": "ms"}
                if is_7d and src_norm not in counts_7d["hrv_rmssd_ms"]:
                    counts_7d["hrv_rmssd_ms"][src_norm] = counts_7d["hrv_rmssd_ms"].get(src_norm, 0) + 1

            if act.get("sleep_score") is not None and int(act["sleep_score"]) > 0:
                if src_norm not in latest_points["sleep"]:
                    latest_points["sleep"][src_norm] = {"date": d_str, "value": f"{int(act['sleep_score'])}/100", "unit": "score"}
                if is_7d and src_norm not in counts_7d["sleep"]:
                    counts_7d["sleep"][src_norm] = counts_7d["sleep"].get(src_norm, 0) + 1

            if act.get("workout_minutes") is not None and int(act["workout_minutes"]) > 0:
                if src_norm not in latest_points["workouts"]:
                    latest_points["workouts"][src_norm] = {"date": d_str, "value": f"{int(act['workout_minutes'])} min", "unit": "session"}
                if is_7d:
                    counts_7d["workouts"][src_norm] = counts_7d["workouts"].get(src_norm, 0) + 1

        # Sessions de sommeil
        for sl in sleep_rows:
            raw_src = str(sl.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            d_str = str(sl.get("date") or sl.get("start_time", ""))[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)
            dur = sl.get("duration_minutes", 0)
            score = sl.get("sleep_score")

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if src_norm not in latest_points["sleep"]:
                val_txt = f"{dur} min (score {score}/100)" if score else f"{dur} min"
                latest_points["sleep"][src_norm] = {"date": d_str, "value": val_txt, "unit": "session"}
            if is_7d:
                counts_7d["sleep"][src_norm] = counts_7d["sleep"].get(src_norm, 0) + 1

        # Workouts
        for wo in workouts_rows:
            raw_src = str(wo.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            d_str = str(wo.get("start_time", ""))[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if src_norm not in latest_points["workouts"]:
                val_txt = f"{wo.get('workout_type', 'Entraînement')} ({wo.get('duration_minutes', 0)} min)"
                latest_points["workouts"][src_norm] = {"date": d_str, "value": val_txt, "unit": "session"}
            if is_7d:
                counts_7d["workouts"][src_norm] = counts_7d["workouts"].get(src_norm, 0) + 1

        # Hydratation
        for hy in hydration_rows:
            raw_src = str(hy.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            d_str = str(hy.get("date") or hy.get("timestamp", ""))[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if src_norm not in latest_points["hydration"]:
                vol = hy.get("volume_ml", 0)
                latest_points["hydration"][src_norm] = {"date": d_str, "value": f"{round(float(vol), 0)} ml", "unit": "ml"}
            if is_7d:
                counts_7d["hydration"][src_norm] = counts_7d["hydration"].get(src_norm, 0) + 1

        # FC Intraday
        for sa in intraday_rows:
            raw_src = str(sa.get("source") or "health_connect")
            src_norm = normalize_source_name(raw_src)
            m_type = str(sa.get("metric_type", "hr")).lower()
            d_str = str(sa.get("timestamp", ""))[:10]
            is_7d = bool(d_str and d_str >= seven_days_ago_date)

            if d_str and (src_norm not in latest_activity_date_by_source or d_str > latest_activity_date_by_source[src_norm]):
                latest_activity_date_by_source[src_norm] = d_str

            if m_type in ("hr", "heart_rate"):
                if src_norm not in latest_points["intraday_hr"]:
                    latest_points["intraday_hr"][src_norm] = {
                        "date": d_str,
                        "value": f"{round(float(sa.get('value', 0)), 1)} bpm",
                        "unit": "bpm"
                    }
                if is_7d:
                    counts_7d["intraday_hr"][src_norm] = counts_7d["intraday_hr"].get(src_norm, 0) + 1

        # Synthèse des appareils et de leur dernier sync
        devices_summary: Dict[str, Dict[str, Any]] = {}
        for src in CANONICAL_SOURCES:
            dev_info = devices_by_id.get(src)
            last_sync = None
            last_sync_origin = None

            if dev_info and (dev_info.get("last_sync_at") or dev_info.get("last_sync")):
                last_sync = dev_info.get("last_sync_at") or dev_info.get("last_sync")
                last_sync_origin = "user_devices.last_sync_at"
            elif src in latest_raw_ingest:
                last_sync = latest_raw_ingest[src]
                last_sync_origin = "raw_ingest.received_at"
            elif src in latest_activity_date_by_source:
                last_sync = latest_activity_date_by_source[src]
                last_sync_origin = "data_records.date"

            default_meta = DEFAULT_DEVICE_METADATA.get(src, {"name": src.title(), "device_type": "sensor"})
            is_connected = bool(dev_info.get("connected", False)) if dev_info else (src in ("manual",) or last_sync is not None)

            devices_summary[src] = {
                "device_id": src,
                "name": dev_info.get("name") if (dev_info and dev_info.get("name")) else default_meta["name"],
                "device_type": dev_info.get("device_type") if dev_info else default_meta["device_type"],
                "connected": is_connected,
                "sync_status": dev_info.get("sync_status", "connected" if is_connected else "disconnected") if dev_info else ("connected" if is_connected else "disconnected"),
                "last_sync_at": last_sync,
                "last_sync_origin": last_sync_origin
            }

        # Matrice complète des métriques
        metrics_list: List[Dict[str, Any]] = []
        for m in METRIC_DEFINITIONS:
            m_key = m["key"]
            sources_map: Dict[str, Dict[str, Any]] = {}
            metric_latest_point: Optional[Dict[str, Any]] = None
            points_7d_total = 0
            active_sources: List[str] = []

            for src in CANONICAL_SOURCES:
                is_supported = bool(m["connectors"].get(src, False))
                pt = latest_points.get(m_key, {}).get(src)
                pts_7d = counts_7d.get(m_key, {}).get(src, 0)
                points_7d_total += pts_7d

                if pt:
                    active_sources.append(src)
                    if not metric_latest_point or (pt.get("date") and str(pt["date"]) > str(metric_latest_point.get("date", ""))):
                        metric_latest_point = dict(pt)
                        metric_latest_point["source"] = src

                # Statut fin par source
                if not is_supported:
                    source_status = "unsupported"  # Gris : non lu par le connecteur
                elif pt is not None or pts_7d > 0:
                    if m["rendered_in_ui"]:
                        source_status = "rendered"  # Vert : ingéré et affiché
                    else:
                        source_status = "unrendered"  # Rouge : ingéré mais jamais affiché
                else:
                    source_status = "no_data"  # Bleu/ambre : lu mais en attente de données

                sources_map[src] = {
                    "source": src,
                    "supported_by_connector": is_supported,
                    "db_table": m["db_table"],
                    "rendered_in_ui": m["rendered_in_ui"],
                    "ui_location": m["ui_location"],
                    "last_point": pt,
                    "points_7d": pts_7d,
                    "status": source_status
                }

            is_ingested_overall = (metric_latest_point is not None) or (points_7d_total > 0)
            is_supported_by_any = any(m["connectors"].get(src, False) for src in CANONICAL_SOURCES)

            if is_ingested_overall:
                global_status = "rendered" if m["rendered_in_ui"] else "unrendered"
            else:
                global_status = "no_data" if is_supported_by_any else "unsupported"

            metrics_list.append({
                "metric_key": m_key,
                "label": m["label"],
                "unit": m["unit"],
                "category": m["category"],
                "db_table": m["db_table"],
                "rendered_in_ui": m["rendered_in_ui"],
                "ui_location": m["ui_location"],
                "is_ingested": is_ingested_overall,
                "is_supported_by_any": is_supported_by_any,
                "global_status": global_status,
                "latest_point": metric_latest_point,
                "points_7d_total": points_7d_total,
                "active_sources": active_sources,
                "by_source": sources_map
            })

        # Diagnostic des pesées de Sébastien
        count_hc = weights_count_by_source.get("health_connect", 0)
        count_withings = weights_count_by_source.get("withings", 0)
        count_manual = weights_count_by_source.get("manual", 0)
        total_weights = len(weights_rows)

        if count_hc > 0 and count_withings > 0:
            diag_summary = (
                f"Vos pesées proviennent de 2 sources actives : Santé Connect ({count_hc} pesée(s)) "
                f"et votre balance Withings ({count_withings} pesée(s))."
            )
            primary_source = "hybrid (Health Connect + Withings)"
        elif count_hc > 0:
            diag_summary = (
                f"Toutes vos pesées récentes proviennent de Santé Connect ({count_hc} pesée(s) reçue(s) via la passerelle mobile Android)."
            )
            primary_source = "health_connect"
        elif count_withings > 0:
            diag_summary = (
                f"Toutes vos pesées récentes proviennent de votre balance connectée Withings ({count_withings} pesée(s) synchronisée(s))."
            )
            primary_source = "withings"
        elif count_manual > 0:
            diag_summary = f"Vos pesées proviennent uniquement de saisies manuelles ({count_manual} pesée(s))."
            primary_source = "manual"
        else:
            diag_summary = "Aucune pesée enregistrée pour le moment dans votre profil."
            primary_source = "none"

        return {
            "generated_at": now.isoformat(),
            "user_id": user_id,
            "summary": {
                "total_metric_types": len(METRIC_DEFINITIONS),
                "ingested_count": sum(1 for m in metrics_list if m["is_ingested"]),
                "rendered_count": sum(1 for m in metrics_list if m["is_ingested"] and m["rendered_in_ui"]),
                "unrendered_ingested_count": sum(1 for m in metrics_list if m["is_ingested"] and not m["rendered_in_ui"]),
                "unsupported_count": sum(1 for m in metrics_list if not m["is_supported_by_any"])
            },
            "devices": devices_summary,
            "weights_diagnostic": {
                "total_weights": total_weights,
                "by_source": weights_count_by_source,
                "primary_source": primary_source,
                "diagnosis_summary": diag_summary,
                "last_point_health_connect": latest_points["weight"].get("health_connect"),
                "last_point_withings": latest_points["weight"].get("withings"),
                "recent_weights": formatted_recent_weights[:20]
            },
            "metrics": metrics_list
        }


CANONICAL_SOURCES = ["health_connect", "withings", "ringconn", "oura", "manual"]

DEFAULT_DEVICE_METADATA = {
    "health_connect": {
        "name": "Google Santé Connect",
        "device_type": "mobile_aggregator"
    },
    "withings": {
        "name": "Withings Scale & Health",
        "device_type": "scale"
    },
    "ringconn": {
        "name": "RingConn Smart Ring",
        "device_type": "ring"
    },
    "oura": {
        "name": "Oura Ring Gen3",
        "device_type": "ring"
    },
    "manual": {
        "name": "Saisie Manuelle",
        "device_type": "manual_input"
    }
}

METRIC_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "key": "weight",
        "label": "Poids",
        "unit": "kg",
        "category": "body",
        "db_table": "weights",
        "rendered_in_ui": True,
        "ui_location": "Graphique & Historique Corps, Synthèse",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": False, "manual": True}
    },
    {
        "key": "body_fat_pct",
        "label": "Masse grasse %",
        "unit": "%",
        "category": "body",
        "db_table": "weights",
        "rendered_in_ui": True,
        "ui_location": "Historique des pesées, Cartes métaboliques",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": False, "manual": True}
    },
    {
        "key": "muscle_mass_kg",
        "label": "Masse musculaire",
        "unit": "kg",
        "category": "body",
        "db_table": "weights",
        "rendered_in_ui": True,
        "ui_location": "Historique des pesées, Cartes métaboliques",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": False, "manual": True}
    },
    {
        "key": "bone_mass_kg",
        "label": "Masse osseuse",
        "unit": "kg",
        "category": "body",
        "db_table": "raw_ingest",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (brut)",
        "connectors": {"health_connect": True, "withings": True, "ringconn": False, "oura": False, "manual": False}
    },
    {
        "key": "water_pct",
        "label": "Eau %",
        "unit": "%",
        "category": "body",
        "db_table": "weights",
        "rendered_in_ui": True,
        "ui_location": "Historique des pesées, Cartes métaboliques",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": False, "manual": True}
    },
    {
        "key": "bmi",
        "label": "IMC",
        "unit": "kg/m²",
        "category": "body",
        "db_table": "weights",
        "rendered_in_ui": True,
        "ui_location": "Carte IMC, Historique des pesées",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": False, "manual": True}
    },
    {
        "key": "steps",
        "label": "Pas",
        "unit": "pas",
        "category": "activity",
        "db_table": "daily_metrics, activities",
        "rendered_in_ui": True,
        "ui_location": "Synthèse (Jauge de pas), Activité & Santé",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": True, "manual": True}
    },
    {
        "key": "active_calories_kcal",
        "label": "Calories actives",
        "unit": "kcal",
        "category": "activity",
        "db_table": "daily_metrics, activities",
        "rendered_in_ui": True,
        "ui_location": "Synthèse (Anneaux d'énergie), Activité & Santé",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": True, "manual": True}
    },
    {
        "key": "resting_hr_bpm",
        "label": "FC repos",
        "unit": "bpm",
        "category": "cardio",
        "db_table": "daily_metrics, activities",
        "rendered_in_ui": True,
        "ui_location": "Activité & Santé (Carte FC Repos)",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": True, "manual": True}
    },
    {
        "key": "hrv_rmssd_ms",
        "label": "HRV RMSSD",
        "unit": "ms",
        "category": "cardio",
        "db_table": "daily_metrics, activities",
        "rendered_in_ui": True,
        "ui_location": "Activité & Santé (Graphique HRV)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": True, "oura": True, "manual": False}
    },
    {
        "key": "spo2_pct",
        "label": "SpO2",
        "unit": "%",
        "category": "cardio",
        "db_table": "daily_metrics",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (stocké en BDD)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": True, "oura": True, "manual": False}
    },
    {
        "key": "skin_temperature_c",
        "label": "Température peau",
        "unit": "°C",
        "category": "recovery",
        "db_table": "daily_metrics",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (stocké en BDD)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": True, "oura": True, "manual": False}
    },
    {
        "key": "hrv_sdnn_ms",
        "label": "HRV SDNN",
        "unit": "ms",
        "category": "cardio",
        "db_table": "daily_metrics",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (stocké en BDD)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": True, "oura": False, "manual": False}
    },
    {
        "key": "sleep",
        "label": "Sommeil",
        "unit": "score / phases",
        "category": "sleep",
        "db_table": "sleep_sessions, daily_metrics",
        "rendered_in_ui": True,
        "ui_location": "Activité & Santé (Cartes Sommeil & Phases)",
        "connectors": {"health_connect": True, "withings": True, "ringconn": True, "oura": True, "manual": False}
    },
    {
        "key": "workouts",
        "label": "Workouts",
        "unit": "sessions",
        "category": "activity",
        "db_table": "workouts",
        "rendered_in_ui": True,
        "ui_location": "Activité & Santé (Historique entraînements)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": False, "oura": True, "manual": True}
    },
    {
        "key": "hydration",
        "label": "Hydratation",
        "unit": "ml",
        "category": "nutrition",
        "db_table": "hydration_logs",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (aucun endpoint de lecture)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": False, "oura": False, "manual": False}
    },
    {
        "key": "intraday_hr",
        "label": "FC intraday",
        "unit": "bpm",
        "category": "cardio",
        "db_table": "intraday_samples",
        "rendered_in_ui": False,
        "ui_location": "Non affiché dans l'UI (échantillons haute fréquence)",
        "connectors": {"health_connect": True, "withings": False, "ringconn": True, "oura": False, "manual": False}
    }
]


def normalize_source_name(src: Optional[str]) -> str:
    """Normalise une chaîne source vers une clé canonique."""
    if not src:
        return "manual"
    s = str(src).lower().strip()
    if any(k in s for k in ("health_connect", "health", "google_fit", "fit", "bridge", "android")):
        return "health_connect"
    if "withings" in s:
        return "withings"
    if "ringconn" in s or ("ring" in s and "oura" not in s):
        return "ringconn"
    if "oura" in s:
        return "oura"
    if "manual" in s or "manuel" in s:
        return "manual"
    return s

