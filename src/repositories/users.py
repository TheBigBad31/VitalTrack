"""Repository pour la gestion des utilisateurs, profils, authentification Google et relations d'amitié."""

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.auth import (
    REFRESH_TOKEN_EXPIRE_SECONDS,
    _is_production,
    generate_refresh_token,
    hash_refresh_token,
)
from src.models import UserConsentItem
from src.repositories.base import BaseRepository


class UsersRepository(BaseRepository):
    """Gestion des comptes utilisateurs, profils personnalisés, sessions Google, RGPD et amitiés."""

    def _ensure_default_user(self) -> Dict[str, Any]:
        """Crée ou retourne le compte local par défaut (configurable via DEFAULT_USER_EMAIL / DEFAULT_USER_NAME)."""
        now_str = datetime.now(timezone.utc).isoformat()
        default_email = os.getenv("DEFAULT_USER_EMAIL", "demo@vitaltrack.local").strip().lower()
        default_name = os.getenv("DEFAULT_USER_NAME", "Utilisateur VitalTrack").strip()
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

            cursor.execute("""
                INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, preferred_ring, preferred_scale, is_demo_profile, google_email, google_name, google_picture, google_sub, updated_at)
                VALUES (?, ?, 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, NULL, NULL, NULL, 2000.0, 'weight_loss', 'moderately_active', 'ringconn', 'withings', 0, ?, ?, ?, ?, ?)
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

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Récupère la liste de tous les utilisateurs enregistrés."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY id ASC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def get_user_profile(self, user_id: int = 1) -> Dict[str, Any]:
        """Récupère le profil personnalisé de user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
            row = cursor.fetchone()

            if not row:
                now_str = datetime.now(timezone.utc).isoformat()
                default_profile_name = os.getenv("DEFAULT_USER_NAME", "Utilisateur").strip() or "Utilisateur"
                cursor.execute("""
                    INSERT INTO user_profile (user_id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, daily_protein_target_g, daily_carbs_target_g, daily_fat_target_g, daily_water_target_ml, goal_type, activity_level, birth_date, current_weight_kg, meal_distribution, preferred_ring, preferred_scale, is_demo_profile, updated_at)
                    VALUES (?, ?, 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, NULL, NULL, NULL, 2000.0, 'weight_loss', 'moderately_active', NULL, 79.5, NULL, 'ringconn', 'withings', 0, ?)
                """, (user_id, default_profile_name, now_str))
                conn.commit()
                cursor.execute("SELECT * FROM user_profile WHERE user_id = ? ORDER BY id ASC LIMIT 1", (user_id,))
                row = cursor.fetchone()

        prof = dict(row)
        raw_cfg = prof.get("nutrition_goals_config")
        if isinstance(raw_cfg, str) and raw_cfg.strip():
            try:
                prof["nutrition_goals_config"] = json.loads(raw_cfg)
            except Exception:
                prof["nutrition_goals_config"] = None
        elif raw_cfg == "":
            prof["nutrition_goals_config"] = None
        return prof

    def update_user_profile(self, data: Dict[str, Any], user_id: int = 1) -> Dict[str, Any]:
        """Met à jour le profil de l'utilisateur."""
        current = self.get_user_profile(user_id=user_id)
        now_str = datetime.now(timezone.utc).isoformat()

        def _val(key, default):
            v = data.get(key)
            if v is not None:
                return v
            return current.get(key, default)

        def _nullable_val(key, default=None):
            if key in data:
                return data[key]
            return current.get(key, default)

        name = _val("name", os.getenv("DEFAULT_USER_NAME", "Utilisateur").strip() or "Utilisateur")
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

        daily_protein = _nullable_val("daily_protein_target_g", None)
        if daily_protein is not None:
            daily_protein = float(daily_protein)
        daily_carbs = _nullable_val("daily_carbs_target_g", None)
        if daily_carbs is not None:
            daily_carbs = float(daily_carbs)
        daily_fat = _nullable_val("daily_fat_target_g", None)
        if daily_fat is not None:
            daily_fat = float(daily_fat)
        daily_water = _val("daily_water_target_ml", 2000.0)
        if daily_water is not None:
            daily_water = float(daily_water)
        goal_type = _val("goal_type", "weight_loss")
        activity_level = _val("activity_level", "moderately_active")
        birth_date = _nullable_val("birth_date", None)
        current_weight = _nullable_val("current_weight_kg", None)
        if current_weight is not None:
            current_weight = float(current_weight)
        meal_distribution = _nullable_val("meal_distribution", None)
        if isinstance(meal_distribution, (dict, list)):
            meal_distribution = json.dumps(meal_distribution)
        nutrition_goals_config = _nullable_val("nutrition_goals_config", None)
        if isinstance(nutrition_goals_config, (dict, list)):
            nutrition_goals_config = json.dumps(nutrition_goals_config)
        is_demo_profile = 1 if _val("is_demo_profile", 0) else 0

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
                    nutrition_goals_config = ?,
                    is_demo_profile = ?,
                    updated_at = ?
                WHERE user_id = ?
            """, (
                name, gender, age, height_cm, target_weight, goal_id, steps, cal_intake,
                prot, ring, scale, google_email, google_name, google_picture, google_sub,
                daily_protein, daily_carbs, daily_fat, daily_water, goal_type, activity_level,
                birth_date, current_weight, meal_distribution, nutrition_goals_config,
                is_demo_profile, now_str, user_id
            ))
            conn.commit()

        return self.get_user_profile(user_id=user_id)

    def get_google_config(self) -> Dict[str, Any]:
        """Récupère la configuration Google Client ID (env seule en production)."""
        client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
        if not _is_production():
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
            ]
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

    def login_google_user(
        self,
        email: str,
        name: str,
        picture: str = "",
        google_sub: str = "",
        auth_method: str = "google"
    ) -> Dict[str, Any]:
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

        sess = self.get_google_session(email=email)
        sess["user_id"] = user["id"]
        sess["uuid"] = user["uuid"]
        return sess

    def get_google_session(self, email: Optional[str] = None) -> Dict[str, Any]:
        """Récupère la session active Google (scopée à un email si fourni)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if email:
                cursor.execute(
                    "SELECT * FROM google_sessions WHERE is_active = 1 AND LOWER(email) = ? ORDER BY last_login DESC LIMIT 1",
                    (email.strip().lower(),),
                )
            else:
                cursor.execute("SELECT * FROM google_sessions WHERE is_active = 1 ORDER BY last_login DESC LIMIT 1")
            row = cursor.fetchone()

        if row:
            session_data = dict(row)
            user_row = None
            with self.get_connection() as conn2:
                cur2 = conn2.cursor()
                cur2.execute("SELECT id, uuid FROM users WHERE LOWER(email) = ?", (session_data["email"].strip().lower(),))
                user_row = cur2.fetchone()

            if user_row:
                return {
                    "is_authenticated": True,
                    "user_id": user_row["id"],
                    "uuid": user_row["uuid"],
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

    def logout_google_user(self, email: Optional[str] = None) -> Dict[str, Any]:
        """Déconnecte la session active Google (scopée à l'email de l'utilisateur courant si fourni)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if email:
                cursor.execute("UPDATE google_sessions SET is_active = 0 WHERE LOWER(email) = ?", (email.strip().lower(),))
            else:
                cursor.execute("UPDATE google_sessions SET is_active = 0")
            conn.commit()
        return {"status": "success", "message": "Session Google fermée avec succès"}

    def set_user_consent(self, category: str, consented: bool, user_id: int = 1) -> UserConsentItem:
        """Enregistre le consentement de l'utilisateur pour une catégorie RGPD (biometrics, nutrition, analytics, devices)."""
        now_str = datetime.now(timezone.utc).isoformat()
        val = 1 if consented else 0

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO user_consents (user_id, category, consented, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET
                        consented = EXCLUDED.consented,
                        updated_at = EXCLUDED.updated_at;
                """, (user_id, category, val, now_str))
            else:
                cursor.execute("""
                    INSERT INTO user_consents (user_id, category, consented, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(user_id, category) DO UPDATE SET
                        consented = excluded.consented,
                        updated_at = excluded.updated_at;
                """, (user_id, category, val, now_str))
            conn.commit()

        return UserConsentItem(category=category, consented=consented, updated_at=now_str)

    def get_user_consents(self, user_id: int = 1) -> Dict[str, bool]:
        """Récupère l'ensemble des consentements RGPD pour l'utilisateur."""
        categories = ["biometrics", "nutrition", "analytics", "devices"]
        consents = {cat: True for cat in categories}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category, consented FROM user_consents WHERE user_id = ?", (user_id,))
            for r in cursor.fetchall():
                consents[r["category"]] = bool(r["consented"])
        return consents

    def delete_user_data_only(self, user_id: int) -> bool:
        """Supprime l'intégralité des données biométriques et historiques tout en conservant le compte utilisateur et son profil."""
        user = self.get_user_by_id(user_id)
        if not user:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM daily_metrics WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM sleep_sessions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM intraday_samples WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM hydration_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM raw_ingest WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM food_items WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (user_id,))
            conn.commit()
        return True

    def delete_user_account_and_data(self, user_id: int) -> bool:
        """Supprime définitivement un compte utilisateur et l'intégralité de ses données (Droit à l'oubli RGPD)."""
        user = self.get_user_by_id(user_id)
        if not user:
            return False

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM weights WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM activities WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM daily_metrics WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM workouts WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE user_id = ?)", (user_id,))
            cursor.execute("DELETE FROM sleep_sessions WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM intraday_samples WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM hydration_logs WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM raw_ingest WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_consents WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM friendships WHERE user_id = ? OR friend_user_id = ?", (user_id, user_id))
            cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM food_items WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
        return True

    def create_friend_request(
        self,
        user_id: int,
        target_identifier: str,
        permission: str = "read_only"
    ) -> Dict[str, Any]:
        """Crée ou réactive une demande d'ami par email ou pseudonyme/nom."""
        target_clean = target_identifier.strip().lower()
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ? OR LOWER(name) = ? LIMIT 1", (target_clean, target_clean))
            target_user = cursor.fetchone()
            if not target_user:
                raise ValueError("Utilisateur cible introuvable")

            target_id = target_user["id"] if isinstance(target_user, dict) else target_user[0]
            if target_id == user_id:
                raise ValueError("Vous ne pouvez pas vous ajouter vous-même comme ami")

            cursor.execute(
                "SELECT * FROM friendships WHERE (user_id = ? AND friend_user_id = ?) OR (user_id = ? AND friend_user_id = ?)",
                (user_id, target_id, target_id, user_id)
            )
            existing = cursor.fetchone()
            if existing:
                ex_dict = dict(existing)
                if ex_dict["status"] == "accepted":
                    raise ValueError("Vous êtes déjà amis avec cet utilisateur")
                if ex_dict["status"] == "pending":
                    if ex_dict["user_id"] == user_id:
                        raise ValueError("Une demande d'ami est déjà en attente")
                    else:
                        cursor.execute(
                            "UPDATE friendships SET status = 'accepted', permission = ?, updated_at = ? WHERE id = ?",
                            (permission, now_str, ex_dict["id"])
                        )
                        conn.commit()
                        cursor.execute("SELECT * FROM friendships WHERE id = ?", (ex_dict["id"],))
                        return dict(cursor.fetchone())
                cursor.execute(
                    "UPDATE friendships SET user_id = ?, friend_user_id = ?, status = 'pending', permission = ?, updated_at = ? WHERE id = ?",
                    (user_id, target_id, permission, now_str, ex_dict["id"])
                )
                conn.commit()
                cursor.execute("SELECT * FROM friendships WHERE id = ?", (ex_dict["id"],))
                return dict(cursor.fetchone())

            cursor.execute("""
                INSERT INTO friendships (user_id, friend_user_id, status, permission, created_at, updated_at)
                VALUES (?, ?, 'pending', ?, ?, ?)
            """, (user_id, target_id, permission, now_str, now_str))
            conn.commit()

            cursor.execute(
                "SELECT * FROM friendships WHERE user_id = ? AND friend_user_id = ?",
                (user_id, target_id)
            )
            row = cursor.fetchone()
            return dict(row)

    def get_friendships(self, user_id: int) -> Dict[str, List[Dict[str, Any]]]:
        """Récupère les amis acceptés, les demandes reçues en attente et les demandes envoyées en attente."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT f.id as request_id, f.status, f.permission, f.created_at, f.updated_at,
                       u.id as friend_id, u.email as friend_email, u.name as friend_name, u.picture as friend_picture
                FROM friendships f
                JOIN users u ON (CASE WHEN f.user_id = ? THEN f.friend_user_id ELSE f.user_id END = u.id)
                WHERE (f.user_id = ? OR f.friend_user_id = ?) AND f.status = 'accepted'
                ORDER BY f.updated_at DESC
            """, (user_id, user_id, user_id))
            accepted_rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT f.id as request_id, f.status, f.permission, f.created_at, f.updated_at,
                       u.id as sender_id, u.email as sender_email, u.name as sender_name, u.picture as sender_picture
                FROM friendships f
                JOIN users u ON f.user_id = u.id
                WHERE f.friend_user_id = ? AND f.status = 'pending'
                ORDER BY f.created_at DESC
            """, (user_id,))
            incoming_rows = [dict(r) for r in cursor.fetchall()]

            cursor.execute("""
                SELECT f.id as request_id, f.status, f.permission, f.created_at, f.updated_at,
                       u.id as recipient_id, u.email as recipient_email, u.name as recipient_name, u.picture as recipient_picture
                FROM friendships f
                JOIN users u ON f.friend_user_id = u.id
                WHERE f.user_id = ? AND f.status = 'pending'
                ORDER BY f.created_at DESC
            """, (user_id,))
            outgoing_rows = [dict(r) for r in cursor.fetchall()]

        return {
            "accepted": accepted_rows,
            "incoming_pending": incoming_rows,
            "outgoing_pending": outgoing_rows
        }

    def accept_friend_request(self, request_id: int, user_id: int) -> Dict[str, Any]:
        """Accepte une demande d'ami reçue."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM friendships WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Demande d'ami introuvable")

            f_dict = dict(row)
            if f_dict["friend_user_id"] != user_id:
                raise ValueError("Vous n'êtes pas le destinataire de cette demande")

            if f_dict["status"] == "accepted":
                return f_dict

            cursor.execute(
                "UPDATE friendships SET status = 'accepted', updated_at = ? WHERE id = ?",
                (now_str, request_id)
            )
            conn.commit()
            cursor.execute("SELECT * FROM friendships WHERE id = ?", (request_id,))
            return dict(cursor.fetchone())

    def reject_friend_request(self, request_id: int, user_id: int) -> Dict[str, Any]:
        """Refuse une demande d'ami reçue."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM friendships WHERE id = ?", (request_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Demande d'ami introuvable")

            f_dict = dict(row)
            if f_dict["friend_user_id"] != user_id:
                raise ValueError("Vous n'êtes pas le destinataire de cette demande")

            cursor.execute(
                "UPDATE friendships SET status = 'rejected', updated_at = ? WHERE id = ?",
                (now_str, request_id)
            )
            conn.commit()
            cursor.execute("SELECT * FROM friendships WHERE id = ?", (request_id,))
            return dict(cursor.fetchone())

    def delete_friendship(self, target_id: int, user_id: int) -> bool:
        """Supprime ou révoque une relation d'ami ou annule une demande par id de friendship ou target_user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM friendships WHERE id = ? AND (user_id = ? OR friend_user_id = ?)",
                (target_id, user_id, user_id)
            )
            deleted = cursor.rowcount > 0
            if not deleted:
                cursor.execute(
                    "DELETE FROM friendships WHERE ((user_id = ? AND friend_user_id = ?) OR (user_id = ? AND friend_user_id = ?))",
                    (user_id, target_id, target_id, user_id)
                )
                deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def check_friendship_access(self, observer_id: int, target_user_id: int) -> Optional[Dict[str, Any]]:
        """Vérifie si observer_id a accès aux données de target_user_id via une amitié accepted."""
        if observer_id == target_user_id:
            return {"status": "self", "permission": "owner"}

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM friendships
                WHERE ((user_id = ? AND friend_user_id = ?) OR (user_id = ? AND friend_user_id = ?))
                  AND status = 'accepted'
                LIMIT 1
            """, (observer_id, target_user_id, target_user_id, observer_id))
            row = cursor.fetchone()
            return dict(row) if row else None

    def delete_demo_users(self) -> int:
        """Supprime les comptes utilisateurs de démonstration/test résiduels."""
        demo_emails = ('sebastien.test@vitaltrack.io', 'test_err_diag@vitaltrack.io')
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE email IN (?, ?)", demo_emails)
            users_to_delete = [r["id"] for r in cursor.fetchall()]
            if not users_to_delete:
                return 0

            for uid in users_to_delete:
                cursor.execute("DELETE FROM weights WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM activities WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM meals WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM meal_log_items WHERE meal_log_id IN (SELECT id FROM meal_logs WHERE user_id = ?)", (uid,))
                cursor.execute("DELETE FROM meal_logs WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM daily_metrics WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM workouts WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM sleep_stages WHERE sleep_session_id IN (SELECT id FROM sleep_sessions WHERE user_id = ?)", (uid,))
                cursor.execute("DELETE FROM sleep_sessions WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM intraday_samples WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM hydration_logs WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM raw_ingest WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM user_consents WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM friendships WHERE user_id = ? OR friend_user_id = ?", (uid, uid))
                cursor.execute("DELETE FROM user_devices WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM user_profile WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM food_items WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM saved_meals WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (uid,))
                cursor.execute("DELETE FROM users WHERE id = ?", (uid,))
            conn.commit()
            return len(users_to_delete)

    # =========================================================================
    # Refresh Tokens révocables (hashés SHA-256 + rotation + détection reuse)
    # =========================================================================

    def create_refresh_token(
        self,
        user_id: int,
        expires_in_seconds: Optional[int] = None,
        family_id: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crée et persiste un refresh token opaque (stocké uniquement sous forme de hash SHA-256)."""
        raw_token = generate_refresh_token()
        token_hash = hash_refresh_token(raw_token)
        ttl = int(expires_in_seconds) if expires_in_seconds is not None else REFRESH_TOKEN_EXPIRE_SECONDS
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        expires_at = (now + timedelta(seconds=ttl)).isoformat()
        fam_id = family_id or str(uuid.uuid4())
        ua = (user_agent or "")[:255] or None

        with self.get_connection(user_id=user_id) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at, created_at, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, token_hash, fam_id, expires_at, now_str, ua),
            )
            conn.commit()

        return {
            "refresh_token": raw_token,
            "token_hash": token_hash,
            "family_id": fam_id,
            "expires_at": expires_at,
        }

    def rotate_refresh_token(
        self,
        raw_token: str,
        expires_in_seconds: Optional[int] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Valide un refresh token actif et effectue une rotation atomique (ancien révoqué, nouveau émis).

        Détection de réutilisation : si un token déjà remplacé est rejoué, toute la famille
        de tokens est immédiatement révoquée.
        """
        if not raw_token or not raw_token.strip():
            return None

        token_hash = hash_refresh_token(raw_token)
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
            row = cursor.fetchone()
            if not row:
                return None

            token_row = dict(row)
            if token_row.get("revoked_at"):
                # Détection de replay d'un token déjà tourné -> révoquer toute la famille
                if token_row.get("replaced_by_hash"):
                    cursor.execute(
                        "UPDATE refresh_tokens SET revoked_at = ? WHERE family_id = ? AND revoked_at IS NULL",
                        (now_str, token_row["family_id"]),
                    )
                    conn.commit()
                return None

            try:
                expires_dt = datetime.fromisoformat(str(token_row["expires_at"]))
                if expires_dt.tzinfo is None:
                    expires_dt = expires_dt.replace(tzinfo=timezone.utc)
            except Exception:
                expires_dt = now - timedelta(seconds=1)

            if expires_dt <= now:
                cursor.execute(
                    "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (now_str, token_row["id"]),
                )
                conn.commit()
                return None

            user_id = int(token_row["user_id"])
            cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
            user_row = cursor.fetchone()
            if not user_row:
                cursor.execute(
                    "UPDATE refresh_tokens SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                    (now_str, token_row["id"]),
                )
                conn.commit()
                return None

            new_raw = generate_refresh_token()
            new_hash = hash_refresh_token(new_raw)
            ttl = int(expires_in_seconds) if expires_in_seconds is not None else REFRESH_TOKEN_EXPIRE_SECONDS
            new_expires_at = (now + timedelta(seconds=ttl)).isoformat()
            ua = (user_agent or token_row.get("user_agent") or "")[:255] or None

            cursor.execute(
                """
                UPDATE refresh_tokens
                SET revoked_at = ?, replaced_by_hash = ?
                WHERE id = ? AND revoked_at IS NULL
                """,
                (now_str, new_hash, token_row["id"]),
            )
            if cursor.rowcount != 1:
                conn.rollback()
                return None

            cursor.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, family_id, expires_at, created_at, user_agent)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, new_hash, token_row["family_id"], new_expires_at, now_str, ua),
            )
            conn.commit()

            return {
                "user": dict(user_row),
                "refresh_token": new_raw,
                "token_hash": new_hash,
                "family_id": token_row["family_id"],
                "expires_at": new_expires_at,
            }

    def revoke_refresh_token(self, raw_token: str, user_id: Optional[int] = None) -> bool:
        """Révoque un refresh token spécifique (par son hash SHA-256)."""
        if not raw_token or not raw_token.strip():
            return False

        token_hash = hash_refresh_token(raw_token)
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection(user_id=user_id) as conn:
            cursor = conn.cursor()
            if user_id is not None:
                cursor.execute(
                    "UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ? AND user_id = ? AND revoked_at IS NULL",
                    (now_str, token_hash, user_id),
                )
            else:
                cursor.execute(
                    "UPDATE refresh_tokens SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                    (now_str, token_hash),
                )
            revoked = cursor.rowcount > 0
            conn.commit()
            return revoked

    def revoke_all_user_refresh_tokens(self, user_id: int) -> int:
        """Révoque tous les refresh tokens actifs d'un utilisateur (ex: logout global)."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection(user_id=user_id) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                (now_str, user_id),
            )
            count = cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
            conn.commit()
            return count

