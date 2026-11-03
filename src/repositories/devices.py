"""Repository pour la gestion des appareils connectés (IoT, balances, bagues, traceurs)."""

import hashlib
import hmac
import secrets
from datetime import datetime, timezone
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
