"""Repository pour la gestion des appareils connectés (IoT, balances, bagues, traceurs)."""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone, timedelta
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
        """Génère la matrice complète des flux de données de santé (Data Map).
        
        Pour chaque métrique et source :
        - Lu côté connecteur
        - Stocké en BDD (table)
        - Rendu dans l'UI (avec localisation)
        - Dernier point reçu (date, valeur, source, horodatage)
        - Nombre de points sur les 7 derniers jours
        - Statut unifié (ingested_and_displayed, ingested_not_displayed, not_read)
        - Traçage précis des pesées récentes avec badge de provenance (Withings vs Santé Connect)
        """
        now_dt = datetime.now(timezone.utc)
        cutoff_7d = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # 1. Objets connectés de l'utilisateur
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            user_device_rows = cursor.fetchall()
            connected_devices = {}
            for r in user_device_rows:
                dev = self._format_device_row(r, reveal_secrets=False)
                if dev:
                    connected_devices[dev["device_id"]] = dev

            # 2. Derniers pushs reçus dans raw_ingest
            raw_ingest_by_source = {}
            try:
                cursor.execute(
                    "SELECT source, MAX(received_at) as last_received, COUNT(*) as cnt_7d FROM raw_ingest WHERE user_id = ? AND received_at >= ? GROUP BY source",
                    (user_id, cutoff_7d)
                )
                for row in cursor.fetchall():
                    s_name = row["source"] if isinstance(row, dict) else row[0]
                    last_rec = row["last_received"] if isinstance(row, dict) else row[1]
                    cnt = row["cnt_7d"] if isinstance(row, dict) else row[2]
                    raw_ingest_by_source[s_name] = {"last_received": last_rec, "cnt_7d": cnt}
            except Exception:
                pass

            # 3. Pesées récentes (10 dernières) pour le diagnostic de Sébastien
            recent_weights = []
            cursor.execute(
                "SELECT id, date, weight_kg, body_fat_pct, muscle_mass_kg, source, measured_at, external_id FROM weights WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 10",
                (user_id,)
            )
            for r in cursor.fetchall():
                w_id = r["id"] if isinstance(r, dict) else r[0]
                w_date = r["date"] if isinstance(r, dict) else r[1]
                w_kg = r["weight_kg"] if isinstance(r, dict) else r[2]
                w_fat = r["body_fat_pct"] if isinstance(r, dict) else r[3]
                w_muscle = r["muscle_mass_kg"] if isinstance(r, dict) else r[4]
                w_src = r["source"] if isinstance(r, dict) else r[5]
                w_meas = r["measured_at"] if isinstance(r, dict) else r[6]
                w_ext = r["external_id"] if isinstance(r, dict) else r[7]

                src_label = "Santé Connect (Android)" if "connect" in str(w_src).lower() else (
                    "Withings (Cloud)" if "withing" in str(w_src).lower() else (
                        "Manuel" if "man" in str(w_src).lower() else str(w_src)
                    )
                )

                recent_weights.append({
                    "id": w_id,
                    "date": w_date,
                    "weight_kg": w_kg,
                    "body_fat_pct": w_fat,
                    "muscle_mass_kg": w_muscle,
                    "source": w_src or "manual",
                    "source_label": src_label,
                    "measured_at": w_meas,
                    "external_id": w_ext
                })

            # Stats sur les pesées
            cursor.execute("SELECT COUNT(*) as cnt FROM weights WHERE user_id = ? AND date >= ?", (user_id, cutoff_7d))
            row_cnt = cursor.fetchone()
            weights_7d_count = (row_cnt.get("cnt") if isinstance(row_cnt, dict) else (row_cnt[0] if row_cnt else 0)) or 0

            # 4. Derniers points des métriques dans daily_metrics
            cursor.execute(
                "SELECT * FROM daily_metrics WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 1",
                (user_id,)
            )
            last_daily_metric = cursor.fetchone()
            last_dm_dict = dict(last_daily_metric) if last_daily_metric else {}

            cursor.execute(
                "SELECT COUNT(*) as cnt FROM daily_metrics WHERE user_id = ? AND date >= ?",
                (user_id, cutoff_7d)
            )
            row_dm_cnt = cursor.fetchone()
            dm_7d_cnt = (row_dm_cnt.get("cnt") if isinstance(row_dm_cnt, dict) else (row_dm_cnt[0] if row_dm_cnt else 0)) or 0

            # 5. Dernier Sommeil
            last_sleep = None
            sleep_7d_cnt = 0
            try:
                cursor.execute(
                    "SELECT date, duration_minutes, source, sleep_score FROM sleep_sessions WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 1",
                    (user_id,)
                )
                r_sl = cursor.fetchone()
                if r_sl:
                    last_sleep = {
                        "date": r_sl["date"] if isinstance(r_sl, dict) else r_sl[0],
                        "duration_minutes": r_sl["duration_minutes"] if isinstance(r_sl, dict) else r_sl[1],
                        "source": r_sl["source"] if isinstance(r_sl, dict) else r_sl[2],
                        "sleep_score": r_sl["sleep_score"] if isinstance(r_sl, dict) else r_sl[3]
                    }
                cursor.execute("SELECT COUNT(*) as cnt FROM sleep_sessions WHERE user_id = ? AND date >= ?", (user_id, cutoff_7d))
                r_sl_cnt = cursor.fetchone()
                sleep_7d_cnt = (r_sl_cnt.get("cnt") if isinstance(r_sl_cnt, dict) else (r_sl_cnt[0] if r_sl_cnt else 0)) or 0
            except Exception:
                pass

            # 6. Dernier Workout
            last_workout = None
            workout_7d_cnt = 0
            try:
                cursor.execute(
                    "SELECT start_time, workout_type, calories_kcal, source FROM workouts WHERE user_id = ? ORDER BY start_time DESC, id DESC LIMIT 1",
                    (user_id,)
                )
                r_wk = cursor.fetchone()
                if r_wk:
                    last_workout = {
                        "start_time": r_wk["start_time"] if isinstance(r_wk, dict) else r_wk[0],
                        "workout_type": r_wk["workout_type"] if isinstance(r_wk, dict) else r_wk[1],
                        "calories_kcal": r_wk["calories_kcal"] if isinstance(r_wk, dict) else r_wk[2],
                        "source": r_wk["source"] if isinstance(r_wk, dict) else r_wk[3]
                    }
                cursor.execute("SELECT COUNT(*) as cnt FROM workouts WHERE user_id = ? AND start_time >= ?", (user_id, cutoff_7d))
                r_wk_cnt = cursor.fetchone()
                workout_7d_cnt = (r_wk_cnt.get("cnt") if isinstance(r_wk_cnt, dict) else (r_wk_cnt[0] if r_wk_cnt else 0)) or 0
            except Exception:
                pass

            # 7. Dernière Hydratation
            last_hydration = None
            hydration_7d_cnt = 0
            try:
                cursor.execute(
                    "SELECT date, volume_ml, source, timestamp FROM hydration_logs WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 1",
                    (user_id,)
                )
                r_hy = cursor.fetchone()
                if r_hy:
                    last_hydration = {
                        "date": r_hy["date"] if isinstance(r_hy, dict) else r_hy[0],
                        "volume_ml": r_hy["volume_ml"] if isinstance(r_hy, dict) else r_hy[1],
                        "source": r_hy["source"] if isinstance(r_hy, dict) else r_hy[2],
                        "timestamp": r_hy["timestamp"] if isinstance(r_hy, dict) else r_hy[3]
                    }
                cursor.execute("SELECT COUNT(*) as cnt FROM hydration_logs WHERE user_id = ? AND date >= ?", (user_id, cutoff_7d))
                r_hy_cnt = cursor.fetchone()
                hydration_7d_cnt = (r_hy_cnt.get("cnt") if isinstance(r_hy_cnt, dict) else (r_hy_cnt[0] if r_hy_cnt else 0)) or 0
            except Exception:
                pass

            # 8. Fréquence cardiaque intraday
            last_hr_intra = None
            hr_intra_7d_cnt = 0
            try:
                cursor.execute(
                    "SELECT timestamp, value, source FROM intraday_samples WHERE user_id = ? AND metric_type = 'hr' ORDER BY timestamp DESC, id DESC LIMIT 1",
                    (user_id,)
                )
                r_intra = cursor.fetchone()
                if r_intra:
                    last_hr_intra = {
                        "timestamp": r_intra["timestamp"] if isinstance(r_intra, dict) else r_intra[0],
                        "value": r_intra["value"] if isinstance(r_intra, dict) else r_intra[1],
                        "source": r_intra["source"] if isinstance(r_intra, dict) else r_intra[2]
                    }
                cursor.execute("SELECT COUNT(*) as cnt FROM intraday_samples WHERE user_id = ? AND metric_type = 'hr' AND timestamp >= ?", (user_id, cutoff_7d))
                r_intra_cnt = cursor.fetchone()
                hr_intra_7d_cnt = (r_intra_cnt.get("cnt") if isinstance(r_intra_cnt, dict) else (r_intra_cnt[0] if r_intra_cnt else 0)) or 0
            except Exception:
                pass

        latest_weight = recent_weights[0] if recent_weights else None

        metrics_definitions = [
            {
                "key": "weight",
                "label": "Poids Corporel",
                "unit": "kg",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "health_connect", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Jauges Métaboliques, Tableau des pesées",
                "last_point": {
                    "date": latest_weight["date"],
                    "value": f"{latest_weight['weight_kg']} kg",
                    "source": latest_weight["source"],
                    "measured_at": latest_weight["measured_at"]
                } if latest_weight and latest_weight.get("weight_kg") else None,
                "points_7d_count": weights_7d_count
            },
            {
                "key": "body_fat",
                "label": "Masse Grasse",
                "unit": "%",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "health_connect", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Jauge Masse Grasse, Carte Impédancemétrie",
                "last_point": {
                    "date": latest_weight["date"],
                    "value": f"{latest_weight['body_fat_pct']} %",
                    "source": latest_weight["source"]
                } if latest_weight and latest_weight.get("body_fat_pct") is not None else None,
                "points_7d_count": weights_7d_count
            },
            {
                "key": "muscle_mass",
                "label": "Masse Musculaire",
                "unit": "kg",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "health_connect", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Carte Impédancemétrie",
                "last_point": {
                    "date": latest_weight["date"],
                    "value": f"{latest_weight['muscle_mass_kg']} kg",
                    "source": latest_weight["source"]
                } if latest_weight and latest_weight.get("muscle_mass_kg") is not None else None,
                "points_7d_count": weights_7d_count
            },
            {
                "key": "bone_mass",
                "label": "Masse Osseuse",
                "unit": "kg",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "health_connect"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Carte Impédancemétrie",
                "last_point": None,
                "points_7d_count": 0
            },
            {
                "key": "water_pct",
                "label": "Eau Corporelle",
                "unit": "%",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Carte Impédancemétrie",
                "last_point": None,
                "points_7d_count": 0
            },
            {
                "key": "bmi",
                "label": "Indice de Masse Corporelle (IMC)",
                "unit": "kg/m²",
                "category": "body",
                "table": "weights",
                "supported_sources": ["withings", "health_connect", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Corps, Jauges Métaboliques",
                "last_point": {
                    "date": latest_weight["date"],
                    "value": f"{round(float(latest_weight['weight_kg']) / ((1.78)**2), 1)} kg/m²",
                    "source": latest_weight["source"]
                } if latest_weight and latest_weight.get("weight_kg") else None,
                "points_7d_count": weights_7d_count
            },
            {
                "key": "steps",
                "label": "Pas Quotidiens",
                "unit": "pas",
                "category": "activity",
                "table": "daily_metrics, activities",
                "supported_sources": ["health_connect", "ringconn", "oura", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Aujourd'hui, Tab Activité & Santé",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('steps')} pas",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("steps") else None,
                "points_7d_count": dm_7d_cnt
            },
            {
                "key": "active_calories",
                "label": "Dépense Active",
                "unit": "kcal",
                "category": "activity",
                "table": "daily_metrics, activities",
                "supported_sources": ["health_connect", "ringconn", "oura", "manual"],
                "rendered_in_ui": True,
                "ui_location": "Tab Aujourd'hui, Anneau d'énergie, Tab Activité",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('active_calories_kcal')} kcal",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("active_calories_kcal") is not None else None,
                "points_7d_count": dm_7d_cnt
            },
            {
                "key": "resting_hr",
                "label": "Fréquence Cardiaque Repos",
                "unit": "bpm",
                "category": "biometrics",
                "table": "daily_metrics, activities",
                "supported_sources": ["health_connect", "ringconn", "oura", "withings"],
                "rendered_in_ui": True,
                "ui_location": "Tab Activité, Carte Biométrie Cardiaque",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('resting_hr_bpm')} bpm",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("resting_hr_bpm") is not None else None,
                "points_7d_count": dm_7d_cnt
            },
            {
                "key": "hrv_rmssd",
                "label": "Variabilité Cardiaque (HRV RMSSD)",
                "unit": "ms",
                "category": "biometrics",
                "table": "daily_metrics, activities",
                "supported_sources": ["health_connect", "ringconn", "oura"],
                "rendered_in_ui": True,
                "ui_location": "Tab Activité, Carte HRV Récupération",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('hrv_rmssd_ms')} ms",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("hrv_rmssd_ms") is not None else None,
                "points_7d_count": dm_7d_cnt
            },
            {
                "key": "hrv_sdnn",
                "label": "Variabilité Cardiaque (HRV SDNN)",
                "unit": "ms",
                "category": "biometrics",
                "table": "daily_metrics",
                "supported_sources": ["health_connect", "ringconn"],
                "rendered_in_ui": False,
                "ui_location": "Non restitué dans l'UI",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('hrv_sdnn_ms')} ms",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("hrv_sdnn_ms") is not None else None,
                "points_7d_count": dm_7d_cnt if last_dm_dict.get("hrv_sdnn_ms") is not None else 0
            },
            {
                "key": "spo2",
                "label": "Saturation Oxygène (SpO2)",
                "unit": "%",
                "category": "biometrics",
                "table": "daily_metrics",
                "supported_sources": ["health_connect", "ringconn", "oura"],
                "rendered_in_ui": False,
                "ui_location": "Non restitué dans l'UI",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('spo2_pct')} %",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("spo2_pct") is not None else None,
                "points_7d_count": dm_7d_cnt if last_dm_dict.get("spo2_pct") is not None else 0
            },
            {
                "key": "skin_temperature",
                "label": "Température Cutanée",
                "unit": "°C",
                "category": "biometrics",
                "table": "daily_metrics",
                "supported_sources": ["health_connect", "ringconn", "oura"],
                "rendered_in_ui": False,
                "ui_location": "Non restitué dans l'UI",
                "last_point": {
                    "date": last_dm_dict.get("date"),
                    "value": f"{last_dm_dict.get('skin_temperature_c')} °C",
                    "source": last_dm_dict.get("source")
                } if last_dm_dict.get("skin_temperature_c") is not None else None,
                "points_7d_count": dm_7d_cnt if last_dm_dict.get("skin_temperature_c") is not None else 0
            },
            {
                "key": "sleep_session",
                "label": "Sommeil & Cycles",
                "unit": "min",
                "category": "sleep",
                "table": "sleep_sessions, sleep_stages",
                "supported_sources": ["health_connect", "ringconn", "oura", "withings"],
                "rendered_in_ui": True,
                "ui_location": "Tab Activité, Carte Sommeil & Architecture",
                "last_point": {
                    "date": last_sleep["date"],
                    "value": f"{last_sleep['duration_minutes']} min",
                    "source": last_sleep["source"]
                } if last_sleep else None,
                "points_7d_count": sleep_7d_cnt
            },
            {
                "key": "workouts",
                "label": "Séances d'Entraînement",
                "unit": "séance",
                "category": "activity",
                "table": "workouts",
                "supported_sources": ["health_connect", "ringconn", "oura", "strava"],
                "rendered_in_ui": True,
                "ui_location": "Tab Activité, Historique des Séances",
                "last_point": {
                    "date": str(last_workout["start_time"])[:10],
                    "value": f"{last_workout['workout_type']} ({last_workout['calories_kcal']} kcal)",
                    "source": last_workout["source"]
                } if last_workout else None,
                "points_7d_count": workout_7d_cnt
            },
            {
                "key": "hydration",
                "label": "Hydratation",
                "unit": "ml",
                "category": "nutrition",
                "table": "hydration_logs",
                "supported_sources": ["health_connect", "manual"],
                "rendered_in_ui": False,
                "ui_location": "Non restitué dans l'UI",
                "last_point": {
                    "date": last_hydration["date"],
                    "value": f"{last_hydration['volume_ml']} ml",
                    "source": last_hydration["source"]
                } if last_hydration else None,
                "points_7d_count": hydration_7d_cnt
            },
            {
                "key": "hr_intraday",
                "label": "FC Intraday (Échantillons)",
                "unit": "bpm",
                "category": "biometrics",
                "table": "intraday_samples",
                "supported_sources": ["health_connect", "ringconn"],
                "rendered_in_ui": False,
                "ui_location": "Non restitué dans l'UI",
                "last_point": {
                    "date": str(last_hr_intra["timestamp"])[:10],
                    "value": f"{last_hr_intra['value']} bpm",
                    "source": last_hr_intra["source"]
                } if last_hr_intra else None,
                "points_7d_count": hr_intra_7d_cnt
            }
        ]

        metrics = []
        ingested_and_displayed = 0
        ingested_not_displayed = 0
        not_read = 0

        for m in metrics_definitions:
            is_supported_by_user = any(
                connected_devices.get(s, {}).get("connected") for s in m["supported_sources"]
            ) or (m["last_point"] is not None)

            m["read_by_connector"] = bool(is_supported_by_user)
            m["stored_in_db"] = True

            if not m["rendered_in_ui"]:
                m["status"] = "ingested_not_displayed"
                ingested_not_displayed += 1
            elif not m["read_by_connector"] and m["last_point"] is None:
                m["status"] = "not_read"
                not_read += 1
            else:
                m["status"] = "ingested_and_displayed"
                ingested_and_displayed += 1

            metrics.append(m)

        sources = [
            {
                "id": "health_connect",
                "name": "Santé Connect (Android / Xiaomi)",
                "device_type": "hub",
                "connected": bool(connected_devices.get("health_connect", {}).get("connected")),
                "last_sync_at": connected_devices.get("health_connect", {}).get("last_sync_at") or raw_ingest_by_source.get("health_connect", {}).get("last_received"),
                "push_count_7d": raw_ingest_by_source.get("health_connect", {}).get("cnt_7d", 0)
            },
            {
                "id": "withings",
                "name": "Withings Body Scan & Scales",
                "device_type": "scale",
                "connected": bool(connected_devices.get("withings", {}).get("connected")),
                "last_sync_at": connected_devices.get("withings", {}).get("last_sync_at") or raw_ingest_by_source.get("withings", {}).get("last_received"),
                "push_count_7d": raw_ingest_by_source.get("withings", {}).get("cnt_7d", 0)
            },
            {
                "id": "ringconn",
                "name": "RingConn Gen 3 Smart Ring",
                "device_type": "smart_ring",
                "connected": bool(connected_devices.get("ringconn", {}).get("connected")),
                "last_sync_at": connected_devices.get("ringconn", {}).get("last_sync_at") or raw_ingest_by_source.get("ringconn", {}).get("last_received"),
                "push_count_7d": raw_ingest_by_source.get("ringconn", {}).get("cnt_7d", 0)
            },
            {
                "id": "oura",
                "name": "Oura Ring Gen 3 / Horizon",
                "device_type": "smart_ring",
                "connected": bool(connected_devices.get("oura", {}).get("connected")),
                "last_sync_at": connected_devices.get("oura", {}).get("last_sync_at") or raw_ingest_by_source.get("oura", {}).get("last_received"),
                "push_count_7d": raw_ingest_by_source.get("oura", {}).get("cnt_7d", 0)
            },
            {
                "id": "manual",
                "name": "Saisie Manuelle (Application)",
                "device_type": "manual",
                "connected": True,
                "last_sync_at": latest_weight.get("date") if latest_weight else None,
                "push_count_7d": weights_7d_count
            }
        ]

        return {
            "status": "success",
            "sources": sources,
            "metrics": metrics,
            "recent_weights": recent_weights,
            "summary": {
                "total_metrics": len(metrics),
                "ingested_and_displayed": ingested_and_displayed,
                "ingested_not_displayed": ingested_not_displayed,
                "not_read": not_read
            }
        }

    def delete_demo_devices(self, user_id: Optional[int] = None) -> int:
        """Supprime les appareils de démonstration résiduels."""
        demo_names = ('RingConn Gen 3 Sébastien',)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id is not None:
                cursor.execute("""
                    DELETE FROM user_devices
                    WHERE user_id = ? AND name IN (?)
                """, (user_id, *demo_names))
            else:
                cursor.execute("""
                    DELETE FROM user_devices
                    WHERE name IN (?)
                """, demo_names)
            count = cursor.rowcount if cursor.rowcount != -1 else 0
            conn.commit()
            return count


