"""Repository UsersRepository : extrait de `src/db.py` (BALI-47).

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



class UsersRepository:
    """Accès aux données (users)."""

    def __init__(self, db):
        self._db = db

    def __getattr__(self, name):
        # Délégation vers la façade Database (connexion, état, autres repositories)
        return getattr(self._db, name)


    # ---------------------------------------------------------
    # Gestion des Utilisateurs (Multi-utilisateurs & Auth)
    # ---------------------------------------------------------

    def _ensure_default_user(self) -> Dict[str, Any]:
        """Crée ou retourne le compte principal par défaut (Sébastien LAMOLIATE)."""
        now_str = datetime.now(timezone.utc).isoformat()
        default_email = "sebastienlamoliate@gmail.com"
        default_name = "Sébastien LAMOLIATE"
        default_uuid = "00000000-0000-4000-8000-000000000001"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ? OR id = 1", (default_email,))
            row = cursor.fetchone()
            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO users (id, uuid, email, auth_provider, google_sub, name, picture, created_at, updated_at)
                        VALUES (1, ?, ?, 'google', 'default_google_sub', ?, 'https://lh3.googleusercontent.com/a/default-user=s96-c', ?, ?)
                        ON CONFLICT (id) DO UPDATE SET email = EXCLUDED.email
                        RETURNING *;
                    """, (default_uuid, default_email, default_name, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT INTO users (id, uuid, email, auth_provider, google_sub, name, picture, created_at, updated_at)
                        VALUES (1, ?, ?, 'google', 'default_google_sub', ?, 'https://lh3.googleusercontent.com/a/default-user=s96-c', ?, ?)
                    """, (default_uuid, default_email, default_name, now_str, now_str))
                    conn.commit()
                    cursor.execute("SELECT * FROM users WHERE id = 1")
                    row = cursor.fetchone()
            return dict(row)


    def get_or_create_user(
        self,
        email: str,
        name: Optional[str] = None,
        picture: Optional[str] = None,
        auth_provider: str = "google",
        google_sub: Optional[str] = None,
        password_hash: Optional[str] = None
    ) -> Dict[str, Any]:
        """Récupère un utilisateur par email ou le crée s'il n'existe pas."""
        now_str = datetime.now(timezone.utc).isoformat()
        email_clean = email.strip().lower()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
            user = cursor.fetchone()

            if user:
                # Mise à jour éventuelle des infos profil
                if (name and name != user.get("name")) or (picture and picture != user.get("picture")) or (google_sub and not user.get("google_sub")):
                    cursor.execute("""
                        UPDATE users
                        SET name = COALESCE(?, name), picture = COALESCE(?, picture),
                            google_sub = COALESCE(?, google_sub), updated_at = ?
                        WHERE id = ?
                    """, (name, picture, google_sub, now_str, user["id"]))
                    conn.commit()
                    cursor.execute("SELECT * FROM users WHERE id = ?", (user["id"],))
                    user = cursor.fetchone()
                return dict(user)

            # Création nouvel utilisateur
            new_uuid = str(uuid.uuid4())
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO users (uuid, email, password_hash, auth_provider, google_sub, name, picture, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING *;
                """, (new_uuid, email_clean, password_hash, auth_provider, google_sub, name or email_clean.split("@")[0], picture or "", now_str, now_str))
                created = cursor.fetchone()
            else:
                cursor.execute("""
                    INSERT INTO users (uuid, email, password_hash, auth_provider, google_sub, name, picture, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (new_uuid, email_clean, password_hash, auth_provider, google_sub, name or email_clean.split("@")[0], picture or "", now_str, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM users WHERE email = ?", (email_clean,))
                created = cursor.fetchone()

            user_dict = dict(created)

            # Créer automatiquement son profil par défaut
            cursor.execute("""
                INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, preferred_ring, preferred_scale, google_email, google_name, google_picture, google_sub, updated_at)
                VALUES (?, ?, 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 140.0, 220.0, 65.0, 2000.0, 'weight_loss', 'moderately_active', 'ringconn', 'withings', ?, ?, ?, ?, ?)
            """, (user_dict["id"], user_dict["name"] or "Utilisateur", user_dict["email"], user_dict["name"], user_dict["picture"], google_sub, now_str))
            conn.commit()

        return user_dict


    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Récupère un compte utilisateur par son identifiant numérique."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            row = cursor.fetchone()
            return dict(row) if row else None


    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Récupère un compte utilisateur par son adresse email (insensible à la casse)."""
        clean_email = email.strip().lower()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ?", (clean_email,))
            row = cursor.fetchone()
            return dict(row) if row else None


    # Profil Utilisateur & Appareils
    # ---------------------------------------------------------

    def get_user_profile(self, user_id: int) -> Dict[str, Any]:
        """Récupère le profil personnalisé de user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
            row = cursor.fetchone()

            if not row:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                    INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, birth_date, current_weight_kg, meal_distribution, preferred_ring, preferred_scale, updated_at)
                    VALUES (?, 'Sébastien', 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 140.0, 220.0, 65.0, 2000.0, 'weight_loss', 'moderately_active', NULL, 79.5, NULL, 'ringconn', 'withings', ?)
                """, (user_id, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
                row = cursor.fetchone()

        return dict(row)


    def update_user_profile(self, data: Dict[str, Any], user_id: int) -> Dict[str, Any]:
        """Met à jour le profil de l'utilisateur."""
        current = self.get_user_profile(user_id=user_id)
        now_str = datetime.now(timezone.utc).isoformat()

        def _val(key, default):
            v = data.get(key)
            if v is not None:
                return v
            return current.get(key, default)

        name = _val("name", "Sébastien")
        gender = _val("gender", "male")
        age = int(_val("age", 35))
        height_cm = float(_val("height_cm", 178.0))
        target_weight = float(_val("target_weight_kg", 77.0))
        goal_id = _val("goal_profile_id", "weight_loss")
        steps = int(_val("target_steps", 10000))
        cal_intake = float(_val("target_calories_intake", 2000.0))
        prot = float(_val("protein_target_per_kg", 1.8))
        ring = _val("preferred_ring", "ringconn")
        scale = _val("preferred_scale", "withings")
        google_email = _val("google_email", None)
        google_name = _val("google_name", None)
        google_picture = _val("google_picture", None)
        google_sub = _val("google_sub", None)

        # Nouveaux champs profil nutritionnel & métabolique
        daily_protein = _val("daily_protein_target_g", None)
        if daily_protein is not None:
            daily_protein = float(daily_protein)
        daily_carbs = _val("daily_carbs_target_g", None)
        if daily_carbs is not None:
            daily_carbs = float(daily_carbs)
        daily_fat = _val("daily_fat_target_g", None)
        if daily_fat is not None:
            daily_fat = float(daily_fat)
        daily_water = _val("daily_water_target_ml", 2000.0)
        if daily_water is not None:
            daily_water = float(daily_water)
        goal_type = _val("goal_type", "weight_loss")
        activity_level = _val("activity_level", "moderately_active")
        birth_date = _val("birth_date", None)
        current_weight = _val("current_weight_kg", None)
        if current_weight is not None:
            current_weight = float(current_weight)
        meal_distribution = _val("meal_distribution", None)
        if isinstance(meal_distribution, (dict, list)):
            meal_distribution = json.dumps(meal_distribution)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profile
                SET name = ?, gender = ?, age = ?, height_cm = ?, target_weight_kg = ?,
                    goal_profile_id = ?, target_steps = ?, target_calories_intake = ?,
                    protein_target_per_kg = ?, preferred_ring = ?, preferred_scale = ?,
                    google_email = ?, google_name = ?, google_picture = ?, google_sub = ?,
                    daily_protein_target_g = ?, daily_carbs_target_g = ?, daily_fat_target_g = ?,
                    daily_water_target_ml = ?, goal_type = ?, activity_level = ?,
                    birth_date = ?, current_weight_kg = ?, meal_distribution = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (
                name, gender, age, height_cm, target_weight, goal_id, steps, cal_intake,
                prot, ring, scale, google_email, google_name, google_picture, google_sub,
                daily_protein, daily_carbs, daily_fat, daily_water, goal_type, activity_level,
                birth_date, current_weight, meal_distribution, now_str, user_id
            ))
            conn.commit()

        return self.get_user_profile(user_id=user_id)


    # ---------------------------------------------------------
    # Google OAuth / GIS Sessions
    # ---------------------------------------------------------

    def get_google_config(self) -> Dict[str, Any]:
        """Récupère la configuration Google Client ID."""
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT google_client_id FROM google_auth_config ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row and row.get("google_client_id"):
                client_id = row["google_client_id"]

        return {
            "google_client_id": client_id,
            "is_configured": bool(client_id),
            "scopes": [
                "openid",
                "email",
                "profile",
                "https://www.googleapis.com/auth/fitness.activity.read",
                "https://www.googleapis.com/auth/fitness.body.read"
            ],
            "demo_fallback_account": "sebastienlamoliate@gmail.com"
        }


    def set_google_client_id(self, client_id: str) -> Dict[str, Any]:
        """Enregistre ou met à jour le Google Client ID."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM google_auth_config")
            cursor.execute("""
                INSERT INTO google_auth_config (google_client_id, updated_at)
                VALUES (?, ?)
            """, (client_id.strip(), now_str))
            conn.commit()
        return self.get_google_config()


    def login_google_user(self, email: str, name: str, picture: str = "", google_sub: str = "", auth_method: str = "google") -> Dict[str, Any]:
        """Enregistre la session Google, synchronise le compte et lie le profil utilisateur."""
        now_str = datetime.now(timezone.utc).isoformat()
        user = self.get_or_create_user(
            email=email,
            name=name,
            picture=picture,
            auth_provider="google",
            google_sub=google_sub
        )

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE google_sessions SET is_active = 0")
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO google_sessions (email, name, picture, google_sub, auth_method, is_active, last_login)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        name = EXCLUDED.name,
                        picture = EXCLUDED.picture,
                        google_sub = EXCLUDED.google_sub,
                        auth_method = EXCLUDED.auth_method,
                        is_active = 1,
                        last_login = EXCLUDED.last_login
                """, (email, name, picture, google_sub, auth_method, now_str))
            else:
                cursor.execute("""
                    INSERT INTO google_sessions (email, name, picture, google_sub, auth_method, is_active, last_login)
                    VALUES (?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(email) DO UPDATE SET
                        name = excluded.name,
                        picture = excluded.picture,
                        google_sub = excluded.google_sub,
                        auth_method = excluded.auth_method,
                        is_active = 1,
                        last_login = excluded.last_login
                """, (email, name, picture, google_sub, auth_method, now_str))
            conn.commit()

        self.update_user_profile({
            "google_email": email,
            "google_name": name,
            "google_picture": picture,
            "google_sub": google_sub
        }, user_id=user["id"])

        sess = self.get_google_session()
        sess["user_id"] = user["id"]
        sess["uuid"] = user["uuid"]
        return sess


    def get_google_session(self) -> Dict[str, Any]:
        """Récupère la session active Google."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM google_sessions WHERE is_active = 1 ORDER BY last_login DESC LIMIT 1")
            row = cursor.fetchone()

        if row:
            session_data = dict(row)
            # Récupérer l'ID utilisateur correspondant
            user_row = None
            with self.get_connection() as conn2:
                cur2 = conn2.cursor()
                cur2.execute("SELECT id, uuid FROM users WHERE email = ?", (session_data["email"],))
                user_row = cur2.fetchone()

            return {
                "is_authenticated": True,
                "user_id": user_row["id"] if user_row else 1,
                "uuid": user_row["uuid"] if user_row else "00000000-0000-4000-8000-000000000001",
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data["picture"],
                "google_sub": session_data["google_sub"],
                "auth_method": session_data["auth_method"],
                "last_login": session_data["last_login"]
            }

        return {
            "is_authenticated": False,
            "user_id": None,
            "uuid": None,
            "email": None,
            "name": None,
            "picture": None,
            "google_sub": None
        }


    def logout_google_user(self) -> Dict[str, Any]:
        """Déconnecte la session active Google."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE google_sessions SET is_active = 0")
            conn.commit()
        return {"status": "success", "message": "Session Google fermée avec succès"}
