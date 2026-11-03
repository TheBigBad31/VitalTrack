"""Script de seed du catalogue CIQUAL / OpenFoodFacts hors production."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ajouter la racine du projet au sys.path si nécessaire
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.seeds.ciqual import PUBLIC_BASE_ITEMS


def seed_ciqual_catalog(db=None) -> int:
    """Insère les aliments du catalogue public de base dans la base de données."""
    if db is None:
        from src.db import Database
        db = Database()

    inserted_count = 0
    now_str = datetime.now(timezone.utc).isoformat()
    is_pub_val = True if db.is_postgres else 1
    bool_check = True if db.is_postgres else 1

    with db.get_connection() as conn:
        cursor = conn.cursor()
        for it in PUBLIC_BASE_ITEMS:
            cursor.execute("SELECT id FROM food_items WHERE name = ? AND is_public = ?", (it["name"], bool_check))
            if not cursor.fetchone():
                cursor.execute("""
                    INSERT INTO food_items (
                        user_id, name, item_type, default_unit, default_quantity,
                        calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                        fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json,
                        is_public, created_at, updated_at
                    )
                    VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                """, (
                    it["name"], it["item_type"], it["default_unit"], it["default_quantity"],
                    it["calories_per_unit"], it["protein_per_unit_g"], it["carbs_per_unit_g"],
                    it["fat_per_unit_g"], it["fiber_per_unit_g"], is_pub_val, now_str, now_str
                ))
                inserted_count += 1
        conn.commit()

    return inserted_count


if __name__ == "__main__":
    count = seed_ciqual_catalog()
    print(f"[Seed CIQUAL] {count} aliment(s) public(s) inséré(s).")
