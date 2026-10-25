"""Repository DevicesRepository : extrait de `src/db.py` (BALI-47).

Les méthodes sont déplacées à l'identique. La connexion et l'état partagé
(`get_connection`, `is_postgres`, `db_path`...) ainsi que les appels inter-repositories
sont résolus via la façade `Database` passée à la construction.
"""

import json
import math
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

from src.models import (
    ActivityEntry, AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, NutritionBenefitItem, SavedMeal, WeightEntry
)
from src.crypto import encrypt_data, decrypt_data, encrypt_credentials, decrypt_credentials

# Essai d'import de psycopg pour le support Neon PostgreSQL
try:
    import psycopg
    from psycopg.rows import dict_row
    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False



class DevicesRepository:
    """Accès aux données (devices)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        # Délégation vers la façade Database (connexion, état, autres repositories)
        return getattr(self._db, name)


    def _format_device_row(self, row: Optional[Dict[str, Any]], reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Formate et protège une ligne d'appareil en chiffrant/déchiffrant les identifiants au besoin."""
        if not row:
            return None
        d = dict(row)
        # S'assurer des champs standards
        d["connected"] = bool(d.get("connected"))
        d["is_active"] = bool(d.get("is_active", 1))
        d["sync_status"] = d.get("sync_status") or ("connected" if d["connected"] else "disconnected")
        d["last_sync_at"] = d.get("last_sync_at") or d.get("last_sync")

        # Déchiffrement des credentials
        enc_cred = d.get("encrypted_credentials")
        if enc_cred:
            creds = decrypt_credentials(enc_cred)
        elif d.get("api_key"):
            creds = {"api_key": d["api_key"]}
        else:
            creds = {}

        if reveal_secrets:
            d["credentials"] = creds
        else:
            # Masquer les clés pour éviter toute fuite dans les logs ou API publiques
            d.pop("encrypted_credentials", None)
            d.pop("api_key", None)
            d["has_credentials"] = bool(creds)
            if creds.get("api_key"):
                raw_k = str(creds["api_key"])
                d["api_key_masked"] = f"{raw_k[:4]}...{raw_k[-4:]}" if len(raw_k) > 8 else "***"
        return d


    def get_user_devices(self, user_id: int, reveal_secrets: bool = False) -> List[Dict[str, Any]]:
        """Récupère les objets connectés associés à user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? ORDER BY id ASC", (user_id,))
            rows = cursor.fetchall()
        return [self._format_device_row(r, reveal_secrets=reveal_secrets) for r in rows]


    def get_user_device(self, device_id: str, user_id: int, reveal_secrets: bool = False) -> Optional[Dict[str, Any]]:
        """Récupère un objet connecté spécifique pour un user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ? LIMIT 1", (user_id, device_id))
            row = cursor.fetchone()
        return self._format_device_row(row, reveal_secrets=reveal_secrets)


    def delete_user_device(self, device_id: str, user_id: int) -> bool:
        """Déconnecte et révoque un objet connecté pour un user_id en supprimant la ligne et les identifiants chiffrés."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
            deleted = cursor.rowcount > 0
            conn.commit()
        return deleted


    def update_device_sync_status(self, device_id: str, sync_status: str, user_id: int) -> Optional[Dict[str, Any]]:
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
        *, user_id: int
    ) -> Dict[str, Any]:
        """Enregistre ou met à jour un objet connecté pour user_id avec chiffrement au repos."""
        now_str = datetime.now(timezone.utc).isoformat()
        if sync_status is None:
            sync_status = "connected" if connected else "disconnected"

        # Préparation des credentials à chiffrer
        creds_to_encrypt = dict(credentials) if credentials else {}
        if api_key and "api_key" not in creds_to_encrypt:
            creds_to_encrypt["api_key"] = api_key

        encrypted_credentials = encrypt_credentials(creds_to_encrypt) if creds_to_encrypt else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = EXCLUDED.name,
                        device_type = EXCLUDED.device_type,
                        connected = EXCLUDED.connected,
                        auth_type = EXCLUDED.auth_type,
                        api_key = COALESCE(EXCLUDED.api_key, user_devices.api_key),
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
                    api_key, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                row = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO user_devices (
                        user_id, device_id, name, device_type, connected, auth_type,
                        api_key, encrypted_credentials, account_email, is_active,
                        last_sync, last_sync_at, sync_status, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, device_id) DO UPDATE SET
                        name = excluded.name,
                        device_type = excluded.device_type,
                        connected = excluded.connected,
                        auth_type = excluded.auth_type,
                        api_key = COALESCE(excluded.api_key, user_devices.api_key),
                        encrypted_credentials = COALESCE(excluded.encrypted_credentials, user_devices.encrypted_credentials),
                        account_email = COALESCE(excluded.account_email, user_devices.account_email),
                        is_active = excluded.is_active,
                        last_sync = excluded.last_sync,
                        last_sync_at = excluded.last_sync_at,
                        sync_status = excluded.sync_status,
                        updated_at = excluded.updated_at
                """, (
                    user_id, device_id, name, device_type, 1 if connected else 0, auth_type,
                    api_key, encrypted_credentials, account_email, 1 if is_active else 0,
                    now_str, now_str, sync_status, now_str
                ))
                conn.commit()
                cursor.execute("SELECT * FROM user_devices WHERE user_id = ? AND device_id = ?", (user_id, device_id))
                row = cursor.fetchone()
            conn.commit()
        return self._format_device_row(row, reveal_secrets=False)
