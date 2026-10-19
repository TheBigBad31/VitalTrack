"""Gestion de la base de données SQLite locale et Vercel Serverless.

Supporte :
- Persistance dans data/vitaltrack.db
- Bascule automatique sur /tmp/vitaltrack.db si VERCEL=1 ou si le dossier n'est pas inscriptible
- Calcul automatique de la tendance glissante sur 7 jours (EMA ou SMA)
- Pré-chargement automatique d'un jeu de données réaliste sur 30 jours si la base est vide
"""

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import ActivityEntry, FoodItem, MealEntry, WeightEntry


def get_db_path() -> str:
    """Détermine le chemin optimal pour la base SQLite selon l'environnement."""
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        tmp_path = Path("/tmp") / "vitaltrack.db"
        return str(tmp_path)
    
    # Chemin local par défaut
    local_dir = Path(__file__).resolve().parent.parent / "data"
    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        return str(local_dir / "vitaltrack.db")
    except (OSError, PermissionError):
        tmp_path = Path("/tmp") / "vitaltrack.db"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        return str(tmp_path)


class Database:
    """Gestionnaire SQLite pour VitalTrack."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or get_db_path()
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Initialise le schéma de la base de données et effectue le seed si vide."""
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Table des pesées
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS weights (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    weight_kg REAL NOT NULL,
                    body_fat_pct REAL,
                    muscle_mass_kg REAL,
                    water_pct REAL,
                    bmi REAL,
                    trend_7d_kg REAL,
                    source TEXT NOT NULL,
                    notes TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Table des activités quotidiennes
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS activities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    steps INTEGER NOT NULL,
                    active_calories_kcal REAL NOT NULL,
                    bmr_kcal REAL NOT NULL,
                    total_burned_kcal REAL NOT NULL,
                    workout_minutes INTEGER NOT NULL,
                    workout_type TEXT,
                    resting_hr_bpm INTEGER,
                    hrv_ms REAL,
                    sleep_score INTEGER,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)

            # Table des repas (pour Stage 2)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS meals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    meal_type TEXT NOT NULL,
                    total_calories_kcal REAL NOT NULL,
                    protein_g REAL NOT NULL,
                    carbs_g REAL NOT NULL,
                    fat_g REAL NOT NULL,
                    fiber_g REAL,
                    photo_data_url TEXT,
                    items_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            # Table du profil utilisateur (Création profil & personnalisation)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_profile (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL DEFAULT 'Sébastien',
                    gender TEXT NOT NULL DEFAULT 'male',
                    age INTEGER NOT NULL DEFAULT 35,
                    height_cm REAL NOT NULL DEFAULT 178.0,
                    target_weight_kg REAL NOT NULL DEFAULT 77.0,
                    goal_profile_id TEXT NOT NULL DEFAULT 'weight_loss',
                    target_steps INTEGER NOT NULL DEFAULT 10000,
                    target_calories_intake REAL NOT NULL DEFAULT 2000.0,
                    protein_target_per_kg REAL NOT NULL DEFAULT 1.8,
                    preferred_ring TEXT DEFAULT 'ringconn',
                    preferred_scale TEXT DEFAULT 'withings',
                    google_email TEXT,
                    google_name TEXT,
                    google_picture TEXT,
                    google_sub TEXT,
                    updated_at TEXT NOT NULL
                )
            """)

            # Migration douce si la table user_profile existait déjà sans les colonnes google
            for col in ["google_email", "google_name", "google_picture", "google_sub"]:
                try:
                    cursor.execute(f"ALTER TABLE user_profile ADD COLUMN {col} TEXT")
                except sqlite3.OperationalError:
                    pass

            # Table de configuration de l'authentification Google
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS google_auth_config (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    google_client_id TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
            """)

            # Table des sessions actives Google
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS google_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    picture TEXT,
                    google_sub TEXT,
                    auth_method TEXT NOT NULL DEFAULT 'google',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    last_login TEXT NOT NULL
                )
            """)

            # Table des connexions d'objets connectés par l'assistant
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_devices (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    device_type TEXT NOT NULL,
                    connected INTEGER NOT NULL DEFAULT 0,
                    auth_type TEXT NOT NULL DEFAULT 'demo',
                    api_key TEXT,
                    account_email TEXT,
                    last_sync TEXT,
                    updated_at TEXT NOT NULL
                )
            """)
            conn.commit()

        # Vérifier si la base a besoin du jeu de données de démo 30 jours
        self._seed_demo_data_if_empty()

    def calculate_7d_trend(self, target_date: date, new_weight_kg: float) -> float:
        """Calcule la moyenne mobile sur 7 jours incluant la pesée actuelle."""
        start_date = (target_date - timedelta(days=6)).isoformat()
        end_date = target_date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT weight_kg FROM weights
                WHERE date >= ? AND date < ?
                ORDER BY date ASC
            """, (start_date, end_date))
            rows = cursor.fetchall()

        previous_weights = [r["weight_kg"] for r in rows]
        all_weights = previous_weights + [new_weight_kg]
        return round(sum(all_weights) / len(all_weights), 2)

    def insert_weight(self, entry: WeightEntry) -> WeightEntry:
        """Insère ou met à jour une pesée en recalculant la tendance 7j."""
        trend = entry.trend_7d_kg
        if trend is None:
            trend = self.calculate_7d_trend(entry.date, entry.weight_kg)

        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO weights (date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, bmi, trend_7d_kg, source, notes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    weight_kg = excluded.weight_kg,
                    body_fat_pct = excluded.body_fat_pct,
                    muscle_mass_kg = excluded.muscle_mass_kg,
                    water_pct = excluded.water_pct,
                    bmi = excluded.bmi,
                    trend_7d_kg = excluded.trend_7d_kg,
                    source = excluded.source,
                    notes = excluded.notes
            """, (
                date_str,
                entry.weight_kg,
                entry.body_fat_pct,
                entry.muscle_mass_kg,
                entry.water_pct,
                entry.bmi,
                trend,
                entry.source,
                entry.notes,
                now_str
            ))
            entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["trend_7d_kg"] = trend
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return WeightEntry(**entry_dict)

    def get_weights(self, limit: int = 30) -> List[WeightEntry]:
        """Récupère l'historique des pesées ordonné par date croissante."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM weights ORDER BY date DESC LIMIT ?
                ) ORDER BY date ASC
            """, (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(WeightEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                weight_kg=r["weight_kg"],
                body_fat_pct=r["body_fat_pct"],
                muscle_mass_kg=r["muscle_mass_kg"],
                water_pct=r["water_pct"],
                bmi=r["bmi"],
                trend_7d_kg=r["trend_7d_kg"],
                source=r["source"],
                notes=r["notes"],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def insert_activity(self, entry: ActivityEntry) -> ActivityEntry:
        """Insère ou met à jour une entrée d'activité quotidienne."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()

        # Recalcule total_burned_kcal si 0 et BMR + active fournis
        total_burned = entry.total_burned_kcal
        if total_burned <= 0 and (entry.bmr_kcal > 0 or entry.active_calories_kcal > 0):
            total_burned = round(entry.bmr_kcal + entry.active_calories_kcal, 1)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO activities (date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal, workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    steps = excluded.steps,
                    active_calories_kcal = excluded.active_calories_kcal,
                    bmr_kcal = excluded.bmr_kcal,
                    total_burned_kcal = excluded.total_burned_kcal,
                    workout_minutes = excluded.workout_minutes,
                    workout_type = excluded.workout_type,
                    resting_hr_bpm = excluded.resting_hr_bpm,
                    hrv_ms = excluded.hrv_ms,
                    sleep_score = excluded.sleep_score,
                    source = excluded.source
            """, (
                date_str,
                entry.steps,
                entry.active_calories_kcal,
                entry.bmr_kcal,
                total_burned,
                entry.workout_minutes,
                entry.workout_type,
                entry.resting_hr_bpm,
                entry.hrv_ms,
                entry.sleep_score,
                entry.source,
                now_str
            ))
            entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["total_burned_kcal"] = total_burned
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return ActivityEntry(**entry_dict)

    def get_activities(self, limit: int = 30) -> List[ActivityEntry]:
        """Récupère l'historique d'activité ordonné par date croissante."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM activities ORDER BY date DESC LIMIT ?
                ) ORDER BY date ASC
            """, (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(ActivityEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                steps=r["steps"],
                active_calories_kcal=r["active_calories_kcal"],
                bmr_kcal=r["bmr_kcal"],
                total_burned_kcal=r["total_burned_kcal"],
                workout_minutes=r["workout_minutes"],
                workout_type=r["workout_type"],
                resting_hr_bpm=r["resting_hr_bpm"],
                hrv_ms=r["hrv_ms"],
                sleep_score=r["sleep_score"],
                source=r["source"],
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def insert_meal(self, entry: MealEntry) -> MealEntry:
        """Insère un repas avec sa décomposition d'aliments."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        items_json = json.dumps([item.model_dump() for item in entry.items])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO meals (date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                date_str,
                entry.meal_type,
                entry.total_calories_kcal,
                entry.protein_g,
                entry.carbs_g,
                entry.fat_g,
                entry.fiber_g,
                entry.photo_data_url,
                items_json,
                now_str
            ))
            entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return MealEntry(**entry_dict)

    def get_meals_for_date(self, target_date: date) -> List[MealEntry]:
        """Récupère tous les repas d'une date spécifique."""
        date_str = target_date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meals
                WHERE date = ?
                ORDER BY id ASC
            """, (date_str,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r["items_json"] else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                meal_type=r["meal_type"],
                total_calories_kcal=r["total_calories_kcal"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                photo_data_url=r["photo_data_url"],
                items=items,
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def get_meals(self, limit: int = 50) -> List[MealEntry]:
        """Récupère l'historique récent des repas."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM meals ORDER BY date DESC, id DESC LIMIT ?
                ) ORDER BY date ASC, id ASC
            """, (limit,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r["items_json"] else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"]),
                meal_type=r["meal_type"],
                total_calories_kcal=r["total_calories_kcal"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                photo_data_url=r["photo_data_url"],
                items=items,
                created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
            ))
        return results

    def get_user_profile(self) -> Dict[str, Any]:
        """Récupère le profil utilisateur actuel ou en initialise un par défaut."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_profile ORDER BY id ASC LIMIT 1")
            row = cursor.fetchone()

            if not row:
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                    INSERT INTO user_profile (name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, preferred_ring, preferred_scale, updated_at)
                    VALUES ('Sébastien', 'male', 35, 178.0, 77.0, 'weight_loss', 10000, 2000.0, 1.8, 'ringconn', 'withings', ?)
                """, (now_str,))
                conn.commit()
                cursor.execute("SELECT * FROM user_profile ORDER BY id ASC LIMIT 1")
                row = cursor.fetchone()

        return dict(row)

    def update_user_profile(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Met à jour ou crée le profil utilisateur avec les métriques personnalisées."""
        current = self.get_user_profile()
        now_str = datetime.now(timezone.utc).isoformat()

        name = data.get("name", current.get("name", "Sébastien"))
        gender = data.get("gender", current.get("gender", "male"))
        age = int(data.get("age", current.get("age", 35)))
        height_cm = float(data.get("height_cm", current.get("height_cm", 178.0)))
        target_weight = float(data.get("target_weight_kg", current.get("target_weight_kg", 77.0)))
        goal_id = data.get("goal_profile_id", current.get("goal_profile_id", "weight_loss"))
        steps = int(data.get("target_steps", current.get("target_steps", 10000)))
        cal_intake = float(data.get("target_calories_intake", current.get("target_calories_intake", 2000.0)))
        prot = float(data.get("protein_target_per_kg", current.get("protein_target_per_kg", 1.8)))
        ring = data.get("preferred_ring", current.get("preferred_ring", "ringconn"))
        scale = data.get("preferred_scale", current.get("preferred_scale", "withings"))
        google_email = data.get("google_email", current.get("google_email"))
        google_name = data.get("google_name", current.get("google_name"))
        google_picture = data.get("google_picture", current.get("google_picture"))
        google_sub = data.get("google_sub", current.get("google_sub"))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_profile
                SET name = ?, gender = ?, age = ?, height_cm = ?, target_weight_kg = ?,
                    goal_profile_id = ?, target_steps = ?, target_calories_intake = ?,
                    protein_target_per_kg = ?, preferred_ring = ?, preferred_scale = ?,
                    google_email = ?, google_name = ?, google_picture = ?, google_sub = ?,
                    updated_at = ?
                WHERE id = ?
            """, (name, gender, age, height_cm, target_weight, goal_id, steps, cal_intake, prot, ring, scale, google_email, google_name, google_picture, google_sub, now_str, current["id"]))
            conn.commit()

        return self.get_user_profile()

    def get_google_config(self) -> Dict[str, Any]:
        """Récupère la configuration Google Client ID depuis la base ou les variables d'environnement."""
        client_id = os.getenv("GOOGLE_CLIENT_ID", "")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT google_client_id FROM google_auth_config ORDER BY id DESC LIMIT 1")
            row = cursor.fetchone()
            if row and row["google_client_id"]:
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
        """Enregistre ou met à jour le Google Client ID dans la base de données."""
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
        """Enregistre ou active la session Google et lie automatiquement le profil utilisateur."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            # Mettre à jour toutes les autres sessions comme inactives
            cursor.execute("UPDATE google_sessions SET is_active = 0")
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

        # Lier au profil utilisateur principal
        self.update_user_profile({
            "google_email": email,
            "google_name": name,
            "google_picture": picture,
            "google_sub": google_sub
        })

        return self.get_google_session()

    def get_google_session(self) -> Dict[str, Any]:
        """Récupère la session Google active s'il y en a une."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM google_sessions WHERE is_active = 1 ORDER BY last_login DESC LIMIT 1")
            row = cursor.fetchone()

        if row:
            session_data = dict(row)
            return {
                "is_authenticated": True,
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data["picture"],
                "google_sub": session_data["google_sub"],
                "auth_method": session_data["auth_method"],
                "last_login": session_data["last_login"]
            }

        return {
            "is_authenticated": False,
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

    def get_user_devices(self) -> List[Dict[str, Any]]:
        """Récupère l'état des appareils configurés dans user_devices."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM user_devices ORDER BY id ASC")
            rows = cursor.fetchall()
        return [dict(r) for r in rows]

    def update_user_device(self, device_id: str, name: str, device_type: str, connected: bool, auth_type: str = "connected", api_key: Optional[str] = None, account_email: Optional[str] = None) -> Dict[str, Any]:
        """Enregistre ou met à jour un appareil connecté par l'assistant."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO user_devices (device_id, name, device_type, connected, auth_type, api_key, account_email, last_sync, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    name = excluded.name,
                    device_type = excluded.device_type,
                    connected = excluded.connected,
                    auth_type = excluded.auth_type,
                    api_key = COALESCE(excluded.api_key, user_devices.api_key),
                    account_email = COALESCE(excluded.account_email, user_devices.account_email),
                    last_sync = excluded.last_sync,
                    updated_at = excluded.updated_at
            """, (device_id, name, device_type, 1 if connected else 0, auth_type, api_key, account_email, now_str, now_str))
            conn.commit()
            cursor.execute("SELECT * FROM user_devices WHERE device_id = ?", (device_id,))
            row = cursor.fetchone()
        return dict(row)

    def _seed_demo_data_if_empty(self):
        """Pré-charge 30 jours d'historique réaliste si la table weights est vide."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM weights")
            count = cursor.fetchone()["count"]

        if count > 0:
            return

        today = date.today()
        # Profil type : départ à 82.5 kg, objectif perte modérée vers 79.8 kg sur 30 jours
        base_weight = 82.5
        target_loss = 2.7
        bmr = 1780.0

        for i in range(29, -1, -1):
            day = today - timedelta(days=i)
            day_progress = (29 - i) / 29.0
            
            # Fluctuation cyclique réaliste (rétention d'eau, glycogène, etc.)
            import math
            fluctuation = math.sin(i * 0.7) * 0.35 + (0.1 if i % 4 == 0 else -0.1)
            weight = round(base_weight - (target_loss * day_progress) + fluctuation, 2)
            
            # Métriques de composition corporelle
            fat_pct = round(21.5 - (1.2 * day_progress) + (fluctuation * 0.2), 1)
            muscle_kg = round(38.2 - (0.3 * day_progress), 1)
            water_pct = round(56.0 + (0.5 * day_progress), 1)
            bmi = round(weight / (1.78 ** 2), 1) # basé sur 1m78

            weight_entry = WeightEntry(
                date=day,
                weight_kg=weight,
                body_fat_pct=fat_pct,
                muscle_mass_kg=muscle_kg,
                water_pct=water_pct,
                bmi=bmi,
                source="demo",
                notes="Pesée automatique matinale (Balance Démo)"
            )
            self.insert_weight(weight_entry)

            # Activité quotidienne
            is_weekend = day.weekday() >= 5
            steps = 11200 if not is_weekend else 7800
            workout_min = 45 if not is_weekend and i % 2 == 0 else (60 if is_weekend and i % 3 == 0 else 0)
            workout_type = "Course à pied" if workout_min == 45 else ("Randonnée" if workout_min == 60 else None)
            active_cal = round(steps * 0.045 + (workout_min * 7.5), 1)
            resting_hr = 58 if workout_min > 0 else 61
            hrv = round(52.0 + math.cos(i) * 6, 1)
            sleep_score = int(82 + math.sin(i * 0.5) * 8)

            activity_entry = ActivityEntry(
                date=day,
                steps=steps,
                active_calories_kcal=active_cal,
                bmr_kcal=bmr,
                total_burned_kcal=round(bmr + active_cal, 1),
                workout_minutes=workout_min,
                workout_type=workout_type,
                resting_hr_bpm=resting_hr,
                hrv_ms=hrv,
                sleep_score=sleep_score,
                source="demo"
            )
            self.insert_activity(activity_entry)

            # Repas de démonstration pour les 7 derniers jours (i <= 6)
            if i <= 6:
                # 1. Petit-déjeuner
                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="breakfast",
                    total_calories_kcal=430.0,
                    protein_g=24.0,
                    carbs_g=52.0,
                    fat_g=14.0,
                    fiber_g=7.5,
                    items=[
                        FoodItem(name="Flocons d'avoine", portion_g=60.0, calories_kcal=219.0, protein_g=8.1, carbs_g=34.8, fat_g=4.2, fiber_g=6.0, confidence_score=0.9),
                        FoodItem(name="Oeufs brouillés (x2)", portion_g=110.0, calories_kcal=157.0, protein_g=13.8, carbs_g=0.8, fat_g=10.4, fiber_g=0.0, confidence_score=0.95),
                        FoodItem(name="Myrtilles fraîches", portion_g=80.0, calories_kcal=45.0, protein_g=0.6, carbs_g=11.2, fat_g=0.3, fiber_g=2.0, confidence_score=0.85),
                    ]
                ))

                # 2. Déjeuner
                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="lunch",
                    total_calories_kcal=685.0,
                    protein_g=46.0,
                    carbs_g=68.0,
                    fat_g=22.0,
                    fiber_g=8.0,
                    items=[
                        FoodItem(name="Blanc de poulet rôti", portion_g=160.0, calories_kcal=224.0, protein_g=41.6, carbs_g=0.0, fat_g=4.5, fiber_g=0.0, confidence_score=0.92),
                        FoodItem(name="Riz basmati", portion_g=200.0, calories_kcal=260.0, protein_g=5.4, carbs_g=56.0, fat_g=0.6, fiber_g=0.8, confidence_score=0.90),
                        FoodItem(name="Brocolis vapeur", portion_g=180.0, calories_kcal=63.0, protein_g=5.0, carbs_g=12.6, fat_g=0.7, fiber_g=4.7, confidence_score=0.88),
                        FoodItem(name="Filet d'huile d'olive", portion_g=15.0, calories_kcal=132.0, protein_g=0.0, carbs_g=0.0, fat_g=15.0, fiber_g=0.0, confidence_score=0.85),
                    ]
                ))

                # 3. Collation
                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="snack",
                    total_calories_kcal=195.0,
                    protein_g=4.0,
                    carbs_g=34.0,
                    fat_g=4.5,
                    fiber_g=4.2,
                    items=[
                        FoodItem(name="Pomme", portion_g=160.0, calories_kcal=83.0, protein_g=0.5, carbs_g=22.4, fat_g=0.3, fiber_g=3.8, confidence_score=0.95),
                        FoodItem(name="Amandes", portion_g=20.0, calories_kcal=116.0, protein_g=4.2, carbs_g=4.3, fat_g=10.0, fiber_g=2.5, confidence_score=0.90),
                    ]
                ))

                # 4. Dîner
                self.insert_meal(MealEntry(
                    date=day,
                    meal_type="dinner",
                    total_calories_kcal=560.0,
                    protein_g=38.0,
                    carbs_g=38.0,
                    fat_g=26.0,
                    fiber_g=9.5,
                    items=[
                        FoodItem(name="Pavé de saumon", portion_g=150.0, calories_kcal=312.0, protein_g=30.0, carbs_g=0.0, fat_g=19.5, fiber_g=0.0, confidence_score=0.94),
                        FoodItem(name="Haricots verts", portion_g=200.0, calories_kcal=62.0, protein_g=3.6, carbs_g=14.0, fat_g=0.4, fiber_g=5.4, confidence_score=0.89),
                        FoodItem(name="Demi-avocat", portion_g=70.0, calories_kcal=112.0, protein_g=1.4, carbs_g=6.0, fat_g=10.3, fiber_g=4.7, confidence_score=0.91),
                        FoodItem(name="Pain complet", portion_g=30.0, calories_kcal=75.0, protein_g=2.7, carbs_g=15.0, fat_g=0.5, fiber_g=1.8, confidence_score=0.88),
                    ]
                ))

    def export_full_backup(self) -> Dict[str, Any]:
        """Exporte l'intégralité du profil et de l'historique sous forme de dictionnaire JSON."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Profil
            cursor.execute("SELECT * FROM user_profile ORDER BY id ASC LIMIT 1")
            prof_row = cursor.fetchone()
            profile_dict = dict(prof_row) if prof_row else self.get_user_profile()

            # Appareils
            cursor.execute("SELECT * FROM user_devices ORDER BY id ASC")
            devices_list = [dict(r) for r in cursor.fetchall()]

            # Pesées
            cursor.execute("SELECT * FROM weights ORDER BY date ASC")
            weights_list = [dict(r) for r in cursor.fetchall()]

            # Activités
            cursor.execute("SELECT * FROM activities ORDER BY date ASC")
            activities_list = [dict(r) for r in cursor.fetchall()]

            # Repas
            cursor.execute("SELECT * FROM meals ORDER BY date ASC, id ASC")
            meals_rows = cursor.fetchall()
            meals_list = []
            for r in meals_rows:
                m = dict(r)
                if m.get("items_json"):
                    try:
                        m["items"] = json.loads(m["items_json"])
                    except Exception:
                        m["items"] = []
                else:
                    m["items"] = []
                meals_list.append(m)

        return {
            "version": "1.0",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_dict,
            "devices": devices_list,
            "weights": weights_list,
            "activities": activities_list,
            "meals": meals_list
        }

    def import_full_backup(self, data: Dict[str, Any], overwrite: bool = False) -> Dict[str, Any]:
        """Restaure ou synchronise des données de sauvegarde JSON dans SQLite.
        
        Si overwrite=True, vide les tables au préalable.
        Sinon effectue des INSERT OR REPLACE / ON CONFLICT.
        """
        imported_counts = {"weights": 0, "activities": 0, "meals": 0, "devices": 0}

        with self.get_connection() as conn:
            cursor = conn.cursor()

            if overwrite:
                cursor.execute("DELETE FROM weights")
                cursor.execute("DELETE FROM activities")
                cursor.execute("DELETE FROM meals")

            # 1. Profil
            if "profile" in data and isinstance(data["profile"], dict):
                p = data["profile"]
                now_str = datetime.now(timezone.utc).isoformat()
                cursor.execute("""
                    INSERT INTO user_profile (id, name, gender, age, height_cm, target_weight_kg, goal_profile_id, target_steps, target_calories_intake, protein_target_per_kg, preferred_ring, preferred_scale, google_email, google_name, google_picture, google_sub, updated_at)
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        name = excluded.name,
                        gender = excluded.gender,
                        age = excluded.age,
                        height_cm = excluded.height_cm,
                        target_weight_kg = excluded.target_weight_kg,
                        goal_profile_id = excluded.goal_profile_id,
                        target_steps = excluded.target_steps,
                        target_calories_intake = excluded.target_calories_intake,
                        protein_target_per_kg = excluded.protein_target_per_kg,
                        preferred_ring = excluded.preferred_ring,
                        preferred_scale = excluded.preferred_scale,
                        google_email = COALESCE(excluded.google_email, user_profile.google_email),
                        google_name = COALESCE(excluded.google_name, user_profile.google_name),
                        google_picture = COALESCE(excluded.google_picture, user_profile.google_picture),
                        google_sub = COALESCE(excluded.google_sub, user_profile.google_sub),
                        updated_at = excluded.updated_at
                """, (
                    p.get("name", "Sébastien"),
                    p.get("gender", "male"),
                    int(p.get("age", 35)),
                    float(p.get("height_cm", 178.0)),
                    float(p.get("target_weight_kg", 77.0)),
                    p.get("goal_profile_id", "weight_loss"),
                    int(p.get("target_steps", 10000)),
                    float(p.get("target_calories_intake", 2000.0)),
                    float(p.get("protein_target_per_kg", 1.8)),
                    p.get("preferred_ring", "ringconn"),
                    p.get("preferred_scale", "withings"),
                    p.get("google_email"),
                    p.get("google_name"),
                    p.get("google_picture"),
                    p.get("google_sub"),
                    now_str
                ))

            # 2. Appareils
            for dev in data.get("devices", []):
                dev_id = dev.get("device_id")
                if not dev_id:
                    continue
                cursor.execute("""
                    INSERT INTO user_devices (device_id, name, device_type, connected, auth_type, api_key, account_email, last_sync, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(device_id) DO UPDATE SET
                        name = excluded.name,
                        device_type = excluded.device_type,
                        connected = excluded.connected,
                        auth_type = excluded.auth_type,
                        api_key = COALESCE(excluded.api_key, user_devices.api_key),
                        account_email = COALESCE(excluded.account_email, user_devices.account_email),
                        last_sync = excluded.last_sync,
                        updated_at = excluded.updated_at
                """, (
                    dev_id,
                    dev.get("name", dev_id),
                    dev.get("device_type", "unknown"),
                    1 if dev.get("connected") else 0,
                    dev.get("auth_type", "demo"),
                    dev.get("api_key"),
                    dev.get("account_email"),
                    dev.get("last_sync"),
                    dev.get("updated_at") or datetime.now(timezone.utc).isoformat()
                ))
                imported_counts["devices"] += 1

            # 3. Pesées
            for w in data.get("weights", []):
                d_str = w.get("date")
                if not d_str:
                    continue
                cursor.execute("""
                    INSERT INTO weights (date, weight_kg, body_fat_pct, muscle_mass_kg, water_pct, bmi, trend_7d_kg, source, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        weight_kg = excluded.weight_kg,
                        body_fat_pct = excluded.body_fat_pct,
                        muscle_mass_kg = excluded.muscle_mass_kg,
                        water_pct = excluded.water_pct,
                        bmi = excluded.bmi,
                        trend_7d_kg = excluded.trend_7d_kg,
                        source = excluded.source,
                        notes = excluded.notes
                """, (
                    d_str[:10],
                    float(w["weight_kg"]),
                    float(w["body_fat_pct"]) if w.get("body_fat_pct") is not None else None,
                    float(w["muscle_mass_kg"]) if w.get("muscle_mass_kg") is not None else None,
                    float(w["water_pct"]) if w.get("water_pct") is not None else None,
                    float(w["bmi"]) if w.get("bmi") is not None else None,
                    float(w["trend_7d_kg"]) if w.get("trend_7d_kg") is not None else None,
                    w.get("source", "manual"),
                    w.get("notes"),
                    w.get("created_at") or datetime.now(timezone.utc).isoformat()
                ))
                imported_counts["weights"] += 1

            # 4. Activités
            for a in data.get("activities", []):
                d_str = a.get("date")
                if not d_str:
                    continue
                cursor.execute("""
                    INSERT INTO activities (date, steps, active_calories_kcal, bmr_kcal, total_burned_kcal, workout_minutes, workout_type, resting_hr_bpm, hrv_ms, sleep_score, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(date) DO UPDATE SET
                        steps = excluded.steps,
                        active_calories_kcal = excluded.active_calories_kcal,
                        bmr_kcal = excluded.bmr_kcal,
                        total_burned_kcal = excluded.total_burned_kcal,
                        workout_minutes = excluded.workout_minutes,
                        workout_type = excluded.workout_type,
                        resting_hr_bpm = excluded.resting_hr_bpm,
                        hrv_ms = excluded.hrv_ms,
                        sleep_score = excluded.sleep_score,
                        source = excluded.source
                """, (
                    d_str[:10],
                    int(a.get("steps", 0)),
                    float(a.get("active_calories_kcal", 0.0)),
                    float(a.get("bmr_kcal", 0.0)),
                    float(a.get("total_burned_kcal", 0.0)),
                    int(a.get("workout_minutes", 0)),
                    a.get("workout_type"),
                    int(a["resting_hr_bpm"]) if a.get("resting_hr_bpm") is not None else None,
                    float(a["hrv_ms"]) if a.get("hrv_ms") is not None else None,
                    int(a["sleep_score"]) if a.get("sleep_score") is not None else None,
                    a.get("source", "health_connect"),
                    a.get("created_at") or datetime.now(timezone.utc).isoformat()
                ))
                imported_counts["activities"] += 1

            # 5. Repas
            for m in data.get("meals", []):
                d_str = m.get("date")
                if not d_str:
                    continue
                raw_items = m.get("items", [])
                items_json = m.get("items_json") or json.dumps(raw_items)
                cursor.execute("""
                    INSERT INTO meals (date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    d_str[:10],
                    m.get("meal_type", "lunch"),
                    float(m.get("total_calories_kcal", 0.0)),
                    float(m.get("protein_g", 0.0)),
                    float(m.get("carbs_g", 0.0)),
                    float(m.get("fat_g", 0.0)),
                    float(m["fiber_g"]) if m.get("fiber_g") is not None else None,
                    m.get("photo_data_url"),
                    items_json,
                    m.get("created_at") or datetime.now(timezone.utc).isoformat()
                ))
                imported_counts["meals"] += 1

            conn.commit()

        return {
            "status": "success",
            "imported": imported_counts,
            "message": f"Restauration terminée : {imported_counts['weights']} pesées, {imported_counts['activities']} activités, {imported_counts['meals']} repas."
        }

    def clear_all_history(self, keep_profile: bool = True):
        """Efface tout l'historique (pesées, activités, repas) pour réinitialiser ou démarrer un profil vierge."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM weights")
            cursor.execute("DELETE FROM activities")
            cursor.execute("DELETE FROM meals")
            if not keep_profile:
                cursor.execute("DELETE FROM user_profile")
                cursor.execute("DELETE FROM user_devices")
            conn.commit()

    def reset_demo_data(self):
        """Réinitialise et recharge le jeu complet de démonstration sur 30 jours."""
        self.clear_all_history(keep_profile=True)
        self._seed_demo_data_if_empty()
