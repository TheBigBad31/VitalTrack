"""Script de seed des données démo réalistes (30 jours) hors production."""

import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Ajouter la racine du projet au sys.path si nécessaire
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.models import ActivityEntry, FoodItem, MealEntry, WeightEntry


def seed_demo_data(db=None, user_id: int = 1) -> bool:
    """Pré-charge 30 jours d'historique réaliste si la table weights est vide pour cet utilisateur."""
    if db is None:
        from src.db import Database
        db = Database()

    with db.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM weights WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        count = row["count"] if row else 0

    if count > 0:
        return False

    today = date.today()
    base_weight = 82.5
    target_loss = 2.7
    bmr = 1780.0

    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_progress = (29 - i) / 29.0
        fluctuation = math.sin(i * 0.7) * 0.35 + (0.1 if i % 4 == 0 else -0.1)
        weight = round(base_weight - (target_loss * day_progress) + fluctuation, 2)
        fat_pct = round(21.5 - (1.2 * day_progress) + (fluctuation * 0.2), 1)
        muscle_kg = round(38.2 - (0.3 * day_progress), 1)
        water_pct = round(56.0 + (0.5 * day_progress), 1)
        bmi = round(weight / (1.78 ** 2), 1)

        weight_entry = WeightEntry(
            date=day,
            weight_kg=weight,
            body_fat_pct=fat_pct,
            muscle_mass_kg=muscle_kg,
            water_pct=water_pct,
            bmi=bmi,
            source="simulation",
            is_simulated=True,
            notes="Pesée automatique matinale (Balance Démo)"
        )
        db.insert_weight(weight_entry, user_id=user_id)

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
            source="simulation",
            is_simulated=True
        )
        db.insert_activity(activity_entry, user_id=user_id)

        if i <= 6:
            db.insert_meal(MealEntry(
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
            ), user_id=user_id)

            db.insert_meal(MealEntry(
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
            ), user_id=user_id)

            db.insert_meal(MealEntry(
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
            ), user_id=user_id)

            db.insert_meal(MealEntry(
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
            ), user_id=user_id)

    return True


if __name__ == "__main__":
    success = seed_demo_data()
    print(f"[Seed Démo] Succès: {success}")
