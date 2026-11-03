"""Repository pour la gestion des repas, catalogue alimentaire, bienfaits et meal logs."""

import json
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from src.models import (
    AssociatedBenefit, CatalogItem, FoodItem, MealEntry,
    MealLog, MealLogItem, NutritionBenefitItem, SavedMeal
)
from src.repositories.base import BaseRepository
from src.seeds.ciqual import PUBLIC_BASE_ITEMS


class MealsRepository(BaseRepository):
    """Gestion des repas, plats sauvegardés, catalogue d'aliments, abonnements et journalisation (meal logs)."""

    def insert_meal(self, entry: MealEntry, user_id: int = 1) -> MealEntry:
        """Insère un repas pour user_id avec ses aliments décomposés."""
        now_str = datetime.now(timezone.utc).isoformat()
        date_str = entry.date.isoformat()
        items_json = json.dumps([item.model_dump() for item in entry.items])

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO meals (user_id, date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id;
                """, (
                    user_id, date_str, entry.meal_type, entry.total_calories_kcal,
                    entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                    entry.photo_data_url, items_json, now_str
                ))
                res = cursor.fetchone()
                entry_id = res["id"] if res else None
            else:
                cursor.execute("""
                    INSERT INTO meals (user_id, date, meal_type, total_calories_kcal, protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, date_str, entry.meal_type, entry.total_calories_kcal,
                    entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                    entry.photo_data_url, items_json, now_str
                ))
                entry_id = cursor.lastrowid
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = entry_id
        entry_dict["created_at"] = datetime.fromisoformat(now_str)
        return MealEntry(**entry_dict)

    def get_meals_for_date(self, target_date: date, user_id: int = 1) -> List[MealEntry]:
        """Récupère tous les repas d'une date spécifique pour user_id."""
        date_str = target_date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meals
                WHERE user_id = ? AND date = ?
                ORDER BY id ASC
            """, (user_id, date_str))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
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

    def get_meals(self, limit: int = 50, user_id: int = 1) -> List[MealEntry]:
        """Récupère l'historique récent des repas pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM (
                    SELECT * FROM meals WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT ?
                ) sub ORDER BY date ASC, id ASC
            """, (user_id, limit))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(MealEntry(
                id=r["id"],
                date=date.fromisoformat(r["date"][:10]),
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

    def get_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[MealEntry]:
        """Récupère un repas spécifique par son ID pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
        items = [FoodItem(**item) for item in raw_items]
        return MealEntry(
            id=r["id"],
            date=date.fromisoformat(r["date"][:10]),
            meal_type=r["meal_type"],
            total_calories_kcal=r["total_calories_kcal"],
            protein_g=r["protein_g"],
            carbs_g=r["carbs_g"],
            fat_g=r["fat_g"],
            fiber_g=r["fiber_g"],
            photo_data_url=r["photo_data_url"],
            items=items,
            created_at=datetime.fromisoformat(r["created_at"]) if r["created_at"] else None
        )

    def update_meal(self, meal_id: int, entry: MealEntry, user_id: int = 1) -> Optional[MealEntry]:
        """Met à jour un repas existant pour user_id."""
        existing = self.get_meal_by_id(meal_id, user_id=user_id)
        if not existing:
            return None

        items_json = json.dumps([item.model_dump() for item in entry.items])
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE meals
                SET date = ?, meal_type = ?, total_calories_kcal = ?, protein_g = ?,
                    carbs_g = ?, fat_g = ?, fiber_g = ?, photo_data_url = ?, items_json = ?
                WHERE id = ? AND user_id = ?
            """, (
                entry.date.isoformat(), entry.meal_type, entry.total_calories_kcal,
                entry.protein_g, entry.carbs_g, entry.fat_g, entry.fiber_g,
                entry.photo_data_url or existing.photo_data_url, items_json, meal_id, user_id
            ))
            conn.commit()

        entry_dict = entry.model_dump()
        entry_dict["id"] = meal_id
        entry_dict["created_at"] = existing.created_at
        return MealEntry(**entry_dict)

    def delete_meal(self, meal_id: int, user_id: int = 1) -> bool:
        """Supprime un repas pour user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            conn.commit()
            return True

    def insert_saved_meal(self, saved_meal: SavedMeal, user_id: int = 1) -> SavedMeal:
        """Enregistre un nouveau plat type dans la bibliothèque réutilisable."""
        now_str = datetime.now(timezone.utc).isoformat()
        items_json = json.dumps([item.model_dump() for item in saved_meal.items]) if saved_meal.items else "[]"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO saved_meals (
                        user_id, name, meal_type, serving_size, quantity_grams,
                        calories, protein_g, carbs_g, fat_g, fiber_g,
                        ingredients, items_json, photo_url, is_favorite,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, created_at, updated_at;
                """, (
                    user_id, saved_meal.name, saved_meal.meal_type, saved_meal.serving_size or "1 portion",
                    saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                    saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                    saved_meal.ingredients, items_json, saved_meal.photo_url,
                    1 if saved_meal.is_favorite else 0, now_str, now_str
                ))
                row = cursor.fetchone()
                meal_id = row["id"]
                created_at = row["created_at"]
            else:
                cursor.execute("""
                    INSERT INTO saved_meals (
                        user_id, name, meal_type, serving_size, quantity_grams,
                        calories, protein_g, carbs_g, fat_g, fiber_g,
                        ingredients, items_json, photo_url, is_favorite,
                        created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, saved_meal.name, saved_meal.meal_type, saved_meal.serving_size or "1 portion",
                    saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                    saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                    saved_meal.ingredients, items_json, saved_meal.photo_url,
                    1 if saved_meal.is_favorite else 0, now_str, now_str
                ))
                meal_id = cursor.lastrowid
                created_at = now_str
            conn.commit()

        result = saved_meal.model_copy()
        result.id = meal_id
        result.user_id = user_id
        result.created_at = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
        result.updated_at = datetime.fromisoformat(now_str)
        return result

    def get_saved_meals(
        self,
        meal_type: Optional[str] = None,
        is_favorite: Optional[bool] = None,
        user_id: int = 1
    ) -> List[SavedMeal]:
        """Récupère les plats sauvegardés d'un utilisateur avec filtres optionnels."""
        query = "SELECT * FROM saved_meals WHERE user_id = ?"
        params: List[Any] = [user_id]

        if meal_type:
            query += " AND meal_type = ?"
            params.append(meal_type)
        if is_favorite is not None:
            query += " AND is_favorite = ?"
            params.append(1 if is_favorite else 0)

        query += " ORDER BY is_favorite DESC, updated_at DESC, id DESC"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
            items = [FoodItem(**item) for item in raw_items]
            results.append(SavedMeal(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                meal_type=r["meal_type"],
                serving_size=r["serving_size"],
                quantity_grams=r["quantity_grams"],
                calories=r["calories"],
                protein_g=r["protein_g"],
                carbs_g=r["carbs_g"],
                fat_g=r["fat_g"],
                fiber_g=r["fiber_g"],
                ingredients=r["ingredients"],
                items=items,
                photo_url=r["photo_url"],
                is_favorite=bool(r["is_favorite"]),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None
            ))
        return results

    def get_saved_meal_by_id(self, meal_id: int, user_id: int = 1) -> Optional[SavedMeal]:
        """Récupère un plat réutilisable précis par son ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            r = cursor.fetchone()
        if not r:
            return None
        raw_items = json.loads(r["items_json"]) if r.get("items_json") else []
        items = [FoodItem(**item) for item in raw_items]
        return SavedMeal(
            id=r["id"],
            user_id=r["user_id"],
            name=r["name"],
            meal_type=r["meal_type"],
            serving_size=r["serving_size"],
            quantity_grams=r["quantity_grams"],
            calories=r["calories"],
            protein_g=r["protein_g"],
            carbs_g=r["carbs_g"],
            fat_g=r["fat_g"],
            fiber_g=r["fiber_g"],
            ingredients=r["ingredients"],
            items=items,
            photo_url=r["photo_url"],
            is_favorite=bool(r["is_favorite"]),
            created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
            updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None
        )

    def update_saved_meal(self, meal_id: int, saved_meal: SavedMeal, user_id: int = 1) -> Optional[SavedMeal]:
        """Met à jour un plat type réutilisable."""
        existing = self.get_saved_meal_by_id(meal_id, user_id=user_id)
        if not existing:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        items_json = json.dumps([item.model_dump() for item in saved_meal.items]) if saved_meal.items else "[]"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE saved_meals
                SET name = ?, meal_type = ?, serving_size = ?, quantity_grams = ?,
                    calories = ?, protein_g = ?, carbs_g = ?, fat_g = ?, fiber_g = ?,
                    ingredients = ?, items_json = ?, photo_url = ?, is_favorite = ?,
                    updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                saved_meal.name, saved_meal.meal_type, saved_meal.serving_size,
                saved_meal.quantity_grams, saved_meal.calories, saved_meal.protein_g,
                saved_meal.carbs_g, saved_meal.fat_g, saved_meal.fiber_g or 0.0,
                saved_meal.ingredients, items_json,
                saved_meal.photo_url if saved_meal.photo_url is not None else existing.photo_url,
                1 if saved_meal.is_favorite else 0, now_str, meal_id, user_id
            ))
            conn.commit()

        updated = saved_meal.model_copy()
        updated.id = meal_id
        updated.user_id = user_id
        updated.created_at = existing.created_at
        updated.updated_at = datetime.fromisoformat(now_str)
        return updated

    def delete_saved_meal(self, meal_id: int, user_id: int = 1) -> bool:
        """Supprime un plat réutilisable de la bibliothèque."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM saved_meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
            conn.commit()
            return True

    def insert_food_item(self, item: CatalogItem, user_id: int = 1) -> CatalogItem:
        """Crée un aliment ou un plat dans le catalogue de l'utilisateur."""
        now_str = datetime.now(timezone.utc).isoformat()
        is_pub = item.is_public if self.is_postgres else (1 if item.is_public else 0)
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO food_items (
                        user_id, name, item_type, default_unit, default_quantity,
                        calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                        fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json,
                        is_public, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    RETURNING id, created_at, updated_at;
                """, (
                    user_id, item.name, item.item_type, item.default_unit or "g",
                    item.default_quantity or 100.0, item.calories_per_unit,
                    item.protein_per_unit_g or 0.0, item.carbs_per_unit_g or 0.0,
                    item.fat_per_unit_g or 0.0, item.fiber_per_unit_g or 0.0,
                    item.photo_url, json.dumps(item.recipe_items) if item.recipe_items else None,
                    is_pub, now_str, now_str
                ))
                row = cursor.fetchone()
                item_id = row["id"]
                created_at = row["created_at"]
                updated_at = row["updated_at"]
            else:
                cursor.execute("""
                    INSERT INTO food_items (
                        user_id, name, item_type, default_unit, default_quantity,
                        calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                        fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json,
                        is_public, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, item.name, item.item_type, item.default_unit or "g",
                    item.default_quantity or 100.0, item.calories_per_unit,
                    item.protein_per_unit_g or 0.0, item.carbs_per_unit_g or 0.0,
                    item.fat_per_unit_g or 0.0, item.fiber_per_unit_g or 0.0,
                    item.photo_url, json.dumps(item.recipe_items) if item.recipe_items else None,
                    is_pub, now_str, now_str
                ))
                item_id = cursor.lastrowid
                created_at = now_str
                updated_at = now_str
            conn.commit()

        res = item.model_copy()
        res.id = item_id
        res.user_id = user_id
        res.created_at = datetime.fromisoformat(created_at) if isinstance(created_at, str) else created_at
        res.updated_at = datetime.fromisoformat(updated_at) if isinstance(updated_at, str) else updated_at
        if item.benefits:
            self.set_food_item_benefits(item_id, [b.model_dump() for b in item.benefits])
            res.benefits = self.get_food_item_benefits(item_id)
        else:
            res.benefits = []
        return res

    def get_food_items(
        self,
        item_type: Optional[str] = None,
        query: Optional[str] = None,
        user_id: int = 1,
        source: str = "mine",
        friend_id: Optional[int] = None,
        limit: Optional[int] = None,
        offset: int = 0
    ) -> List[CatalogItem]:
        """Récupère les éléments du catalogue selon la source demandée ('mine', 'public', 'friends', 'all', ou friend_id), avec support optionnel de pagination (limit, offset)."""
        params: List[Any] = []
        where_clauses: List[str] = []

        if friend_id is not None:
            where_clauses.append("user_id = ?")
            params.append(friend_id)
        elif source == "mine":
            where_clauses.append("user_id = ?")
            params.append(user_id)
        elif source == "public":
            where_clauses.append("is_public = ?")
            params.append(self._pg_bool_true())
        elif source == "friends":
            where_clauses.append("user_id IN (SELECT target_user_id FROM catalog_subscriptions WHERE subscriber_id = ?)")
            params.append(user_id)
        elif source == "all":
            where_clauses.append("(user_id = ? OR is_public = ? OR user_id IN (SELECT target_user_id FROM catalog_subscriptions WHERE subscriber_id = ?))")
            params.extend([user_id, self._pg_bool_true(), user_id])
        else:
            where_clauses.append("user_id = ?")
            params.append(user_id)

        if item_type:
            where_clauses.append("item_type = ?")
            params.append(item_type)

        if query:
            where_clauses.append("LOWER(name) LIKE ?")
            params.append(f"%{query.strip().lower()}%")

        sql = f"SELECT * FROM food_items WHERE {' AND '.join(where_clauses)} ORDER BY is_public DESC, name ASC"
        if limit is not None:
            sql += f" LIMIT {int(limit)} OFFSET {int(offset)}"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()

            food_ids = [r["id"] for r in rows]
            benefits_by_food_id: Dict[int, List[AssociatedBenefit]] = {fid: [] for fid in food_ids}

            if food_ids:
                placeholders = ", ".join(["?"] * len(food_ids))
                cursor.execute(f"""
                    SELECT fib.food_item_id, nb.id, nb.category, nb.category_id, nb.title, nb.description, nb.icon,
                           fib.source, fib.explanation
                    FROM food_item_benefits fib
                    JOIN nutrition_benefits nb ON fib.benefit_id = nb.id
                    WHERE fib.food_item_id IN ({placeholders})
                    ORDER BY nb.category_id ASC, nb.title ASC
                """, tuple(food_ids))
                b_rows = cursor.fetchall()
                for br in b_rows:
                    fid = br["food_item_id"]
                    if fid in benefits_by_food_id:
                        benefits_by_food_id[fid].append(AssociatedBenefit(
                            benefit_id=br["id"],
                            category=br["category"],
                            category_id=int(br["category_id"]),
                            title=br["title"],
                            description=br["description"],
                            icon=br["icon"],
                            source=br["source"],
                            explanation=br.get("explanation")
                        ))

        items = []
        for r in rows:
            it = CatalogItem(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                item_type=r["item_type"],
                default_unit=r["default_unit"],
                default_quantity=float(r["default_quantity"]),
                calories_per_unit=float(r["calories_per_unit"]),
                protein_per_unit_g=float(r.get("protein_per_unit_g") or 0.0),
                carbs_per_unit_g=float(r.get("carbs_per_unit_g") or 0.0),
                fat_per_unit_g=float(r.get("fat_per_unit_g") or 0.0),
                fiber_per_unit_g=float(r["fiber_per_unit_g"]) if r.get("fiber_per_unit_g") is not None else 0.0,
                photo_url=r.get("photo_url"),
                recipe_items=json.loads(r["recipe_items_json"]) if r.get("recipe_items_json") else [],
                benefits=benefits_by_food_id.get(r["id"], []),
                is_public=bool(r.get("is_public")),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None,
            )
            items.append(it)
        return items

    def get_food_item_by_id(self, item_id: int, user_id: Optional[int] = None) -> Optional[CatalogItem]:
        """Récupère un élément du catalogue par son ID pour user_id ou s'il est public."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id is not None:
                cursor.execute("""
                    SELECT * FROM food_items
                    WHERE id = ? AND (
                        user_id = ? OR is_public = ?
                        OR user_id IN (SELECT target_user_id FROM catalog_subscriptions WHERE subscriber_id = ?)
                    )
                """, (item_id, user_id, self._pg_bool_true(), user_id))
            else:
                cursor.execute("SELECT * FROM food_items WHERE id = ?", (item_id,))
            r = cursor.fetchone()
            if not r:
                return None
            return CatalogItem(
                id=r["id"],
                user_id=r["user_id"],
                name=r["name"],
                item_type=r["item_type"],
                default_unit=r["default_unit"],
                default_quantity=float(r["default_quantity"]),
                calories_per_unit=float(r["calories_per_unit"]),
                protein_per_unit_g=float(r.get("protein_per_unit_g") or 0.0),
                carbs_per_unit_g=float(r.get("carbs_per_unit_g") or 0.0),
                fat_per_unit_g=float(r.get("fat_per_unit_g") or 0.0),
                fiber_per_unit_g=float(r["fiber_per_unit_g"]) if r.get("fiber_per_unit_g") is not None else 0.0,
                photo_url=r.get("photo_url"),
                recipe_items=json.loads(r["recipe_items_json"]) if r.get("recipe_items_json") else [],
                benefits=self.get_food_item_benefits(r["id"]),
                is_public=bool(r.get("is_public")),
                created_at=datetime.fromisoformat(r["created_at"]) if r.get("created_at") else None,
                updated_at=datetime.fromisoformat(r["updated_at"]) if r.get("updated_at") else None,
            )

    def update_food_item(self, item_id: int, data: Dict[str, Any], user_id: int = 1) -> Optional[CatalogItem]:
        """Met à jour un aliment ou plat du catalogue (uniquement si l'utilisateur en est propriétaire)."""
        existing = self.get_food_item_by_id(item_id, user_id=user_id)
        if not existing or existing.user_id != user_id:
            return None

        now_str = datetime.now(timezone.utc).isoformat()
        name = data.get("name", existing.name)
        item_type = data.get("item_type", existing.item_type)
        default_unit = data.get("default_unit", existing.default_unit)
        default_quantity = data.get("default_quantity", existing.default_quantity)
        calories_per_unit = data.get("calories_per_unit", existing.calories_per_unit)
        protein_per_unit_g = data.get("protein_per_unit_g", existing.protein_per_unit_g)
        carbs_per_unit_g = data.get("carbs_per_unit_g", existing.carbs_per_unit_g)
        fat_per_unit_g = data.get("fat_per_unit_g", existing.fat_per_unit_g)
        fiber_per_unit_g = data.get("fiber_per_unit_g", existing.fiber_per_unit_g)
        photo_url = data.get("photo_url", existing.photo_url)
        recipe_items = data.get("recipe_items", existing.recipe_items)
        recipe_items_json = json.dumps(recipe_items) if recipe_items is not None else None
        is_public = data.get("is_public", existing.is_public)
        is_pub = is_public if self.is_postgres else (1 if is_public else 0)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE food_items
                SET name = ?, item_type = ?, default_unit = ?, default_quantity = ?,
                    calories_per_unit = ?, protein_per_unit_g = ?, carbs_per_unit_g = ?,
                    fat_per_unit_g = ?, fiber_per_unit_g = ?, photo_url = ?, recipe_items_json = ?,
                    is_public = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                name, item_type, default_unit, default_quantity,
                calories_per_unit, protein_per_unit_g, carbs_per_unit_g,
                fat_per_unit_g, fiber_per_unit_g, photo_url, recipe_items_json,
                is_pub, now_str, item_id, user_id
            ))
            conn.commit()

        updated = existing.model_copy()
        updated.name = name
        updated.item_type = item_type
        updated.recipe_items = recipe_items or []
        updated.default_unit = default_unit
        updated.default_quantity = default_quantity
        updated.calories_per_unit = calories_per_unit
        updated.protein_per_unit_g = protein_per_unit_g
        updated.carbs_per_unit_g = carbs_per_unit_g
        updated.fat_per_unit_g = fat_per_unit_g
        updated.fiber_per_unit_g = fiber_per_unit_g
        updated.photo_url = photo_url
        updated.is_public = bool(is_public)
        updated.updated_at = datetime.fromisoformat(now_str)
        return updated

    def delete_food_item(self, item_id: int, user_id: int = 1) -> bool:
        """Supprime un aliment ou plat du catalogue de l'utilisateur."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM food_items WHERE id = ? AND user_id = ?", (item_id, user_id))
            if not cursor.fetchone():
                return False
            cursor.execute("DELETE FROM food_items WHERE id = ? AND user_id = ?", (item_id, user_id))
            conn.commit()
            return True

    def add_catalog_subscription(self, subscriber_id: int, target_user_id: int) -> bool:
        """Abonne un utilisateur au catalogue d'un autre utilisateur."""
        if subscriber_id == target_user_id:
            raise ValueError("Impossible de s'abonner à son propre catalogue")

        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE id = ?", (target_user_id,))
            if not cursor.fetchone():
                return False

            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO catalog_subscriptions (subscriber_id, target_user_id, created_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (subscriber_id, target_user_id) DO NOTHING;
                """, (subscriber_id, target_user_id, now_str))
            else:
                cursor.execute("""
                    INSERT OR IGNORE INTO catalog_subscriptions (subscriber_id, target_user_id, created_at)
                    VALUES (?, ?, ?);
                """, (subscriber_id, target_user_id, now_str))
            conn.commit()
            return True

    def remove_catalog_subscription(self, subscriber_id: int, target_user_id: int) -> bool:
        """Désabonne un utilisateur du catalogue d'un ami."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM catalog_subscriptions
                WHERE subscriber_id = ? AND target_user_id = ?
            """, (subscriber_id, target_user_id))
            affected = cursor.rowcount > 0
            conn.commit()
            return affected

    def get_catalog_subscriptions(self, subscriber_id: int) -> List[Dict[str, Any]]:
        """Liste les catalogues d'amis auxquels l'utilisateur est abonné avec les infos de l'ami."""
        sql = """
            SELECT cs.subscriber_id, cs.target_user_id, cs.created_at,
                   u.name AS target_user_name, u.email AS target_user_email
            FROM catalog_subscriptions cs
            JOIN users u ON u.id = cs.target_user_id
            WHERE cs.subscriber_id = ?
            ORDER BY u.name ASC
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (subscriber_id,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]

    def is_subscribed_to_catalog(self, subscriber_id: int, target_user_id: int) -> bool:
        """Vérifie si subscriber_id est abonné au catalogue de target_user_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 1 FROM catalog_subscriptions
                WHERE subscriber_id = ? AND target_user_id = ?
            """, (subscriber_id, target_user_id))
            return cursor.fetchone() is not None

    def _seed_public_food_items(self):
        """Seede le socle d'aliments publics communs de base (CIQUAL / OpenFoodFacts)."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for it in PUBLIC_BASE_ITEMS:
                cursor.execute("SELECT id FROM food_items WHERE name = ? AND is_public = ?", (it["name"], self._pg_bool_true()))
                if not cursor.fetchone():
                    is_pub_val = True if self.is_postgres else 1
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
            conn.commit()

    def _seed_nutrition_benefits(self):
        """Seede le référentiel des bienfaits nutritionnels depuis le catalogue expert."""
        from src.nutrition_rules import EXPERT_BENEFITS_CATALOG

        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for b in EXPERT_BENEFITS_CATALOG:
                rule_cfg = json.dumps(b.get("rule_config") or {})
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO nutrition_benefits (id, category, category_id, title, description, icon, rule_config, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            category = EXCLUDED.category,
                            category_id = EXCLUDED.category_id,
                            title = EXCLUDED.title,
                            description = EXCLUDED.description,
                            icon = EXCLUDED.icon,
                            rule_config = EXCLUDED.rule_config;
                    """, (
                        b["id"], b["category"], b["category_id"], b["title"],
                        b["description"], b["icon"], rule_cfg, now_str
                    ))
                else:
                    cursor.execute("""
                        INSERT INTO nutrition_benefits (id, category, category_id, title, description, icon, rule_config, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (id) DO UPDATE SET
                            category = excluded.category,
                            category_id = excluded.category_id,
                            title = excluded.title,
                            description = excluded.description,
                            icon = excluded.icon,
                            rule_config = excluded.rule_config;
                    """, (
                        b["id"], b["category"], b["category_id"], b["title"],
                        b["description"], b["icon"], rule_cfg, now_str
                    ))
            conn.commit()

    def get_all_nutrition_benefits(self) -> List[NutritionBenefitItem]:
        """Retourne la liste de tous les bienfaits disponibles ordonnés par catégorie."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM nutrition_benefits ORDER BY category_id ASC, title ASC")
            rows = cursor.fetchall()

        benefits = []
        for r in rows:
            cfg = None
            if r.get("rule_config"):
                try:
                    cfg = json.loads(r["rule_config"])
                except Exception:
                    cfg = None
            benefits.append(NutritionBenefitItem(
                id=r["id"],
                category=r["category"],
                category_id=int(r["category_id"]),
                title=r["title"],
                description=r["description"],
                icon=r["icon"],
                rule_config=cfg
            ))
        return benefits

    def get_food_item_benefits(self, food_item_id: int) -> List[AssociatedBenefit]:
        """Récupère les bienfaits associés à un aliment/plat du catalogue."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT nb.id, nb.category, nb.category_id, nb.title, nb.description, nb.icon,
                       fib.source, fib.explanation
                FROM food_item_benefits fib
                JOIN nutrition_benefits nb ON fib.benefit_id = nb.id
                WHERE fib.food_item_id = ?
                ORDER BY nb.category_id ASC, nb.title ASC
            """, (food_item_id,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(AssociatedBenefit(
                benefit_id=r["id"],
                category=r["category"],
                category_id=int(r["category_id"]),
                title=r["title"],
                description=r["description"],
                icon=r["icon"],
                source=r["source"],
                explanation=r.get("explanation")
            ))
        return results

    def set_food_item_benefits(
        self,
        food_item_id: int,
        benefits_data: List[Dict[str, Any]]
    ) -> List[AssociatedBenefit]:
        """Associe ou remplace l'ensemble des bienfaits d'un aliment/plat."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM food_item_benefits WHERE food_item_id = ?", (food_item_id,))

            for b in benefits_data:
                benefit_id = b.get("benefit_id") or b.get("id")
                if not benefit_id:
                    continue
                source = b.get("source", "manual")
                explanation = b.get("explanation", "")
                cursor.execute("""
                    INSERT INTO food_item_benefits (food_item_id, benefit_id, source, explanation, created_at)
                    VALUES (?, ?, ?, ?, ?)
                """, (food_item_id, benefit_id, source, explanation, now_str))
            conn.commit()

        return self.get_food_item_benefits(food_item_id)

    def get_or_create_meal_log(self, date_val: date, meal_type: str, user_id: int = 1) -> MealLog:
        """Récupère l'instance de repas pour une date et un type, ou la crée si inexistante."""
        date_str = date_val.isoformat()
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meal_logs
                WHERE user_id = ? AND date = ? AND meal_type = ?
            """, (user_id, date_str, meal_type))
            row = cursor.fetchone()

            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                        ON CONFLICT (user_id, date, meal_type) DO NOTHING
                        RETURNING id, date, meal_type, photo_url, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at;
                    """, (user_id, date_str, meal_type, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                    """, (user_id, date_str, meal_type, now_str, now_str))
                conn.commit()

                if not row:
                    cursor.execute("""
                        SELECT * FROM meal_logs
                        WHERE user_id = ? AND date = ? AND meal_type = ?
                    """, (user_id, date_str, meal_type))
                    row = cursor.fetchone()

        return self._build_meal_log(dict(row), user_id=user_id)

    def _build_meal_log(self, row: Dict[str, Any], user_id: int = 1) -> MealLog:
        """Construit un objet MealLog avec tous ses MealLogItem associés."""
        meal_log_id = row["id"]
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM meal_log_items
                WHERE meal_log_id = ?
                ORDER BY id ASC
            """, (meal_log_id,))
            item_rows = cursor.fetchall()

        items = [
            MealLogItem(
                id=it["id"],
                meal_log_id=it["meal_log_id"],
                food_item_id=it.get("food_item_id"),
                name=it["name"],
                quantity=float(it["quantity"]),
                unit=it["unit"],
                calories=float(it["calories"]),
                protein_g=float(it.get("protein_g") or 0.0),
                carbs_g=float(it.get("carbs_g") or 0.0),
                fat_g=float(it.get("fat_g") or 0.0),
                fiber_g=float(it["fiber_g"]) if it.get("fiber_g") is not None else 0.0,
                created_at=datetime.fromisoformat(it["created_at"]) if it.get("created_at") else None,
            )
            for it in item_rows
        ]

        return MealLog(
            id=row["id"],
            user_id=row["user_id"],
            date=date.fromisoformat(row["date"][:10]),
            meal_type=row["meal_type"],
            photo_url=row.get("photo_url"),
            total_calories=float(row.get("total_calories") or 0.0),
            total_protein_g=float(row.get("total_protein_g") or 0.0),
            total_carbs_g=float(row.get("total_carbs_g") or 0.0),
            total_fat_g=float(row.get("total_fat_g") or 0.0),
            total_fiber_g=float(row["total_fiber_g"]) if row.get("total_fiber_g") is not None else 0.0,
            items=items,
            created_at=datetime.fromisoformat(row["created_at"]) if row.get("created_at") else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row.get("updated_at") else None,
        )

    def get_meal_logs_for_date(self, target_date: date, user_id: int = 1) -> List[MealLog]:
        """Récupère les 4 repas d'une date (avec les instances existantes et leurs items) en 1 seule requête SQL."""
        date_str = target_date.isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    m.id AS m_id,
                    m.user_id AS m_user_id,
                    m.date AS m_date,
                    m.meal_type AS m_meal_type,
                    m.photo_url AS m_photo_url,
                    m.total_calories AS m_total_calories,
                    m.total_protein_g AS m_total_protein_g,
                    m.total_carbs_g AS m_total_carbs_g,
                    m.total_fat_g AS m_total_fat_g,
                    m.total_fiber_g AS m_total_fiber_g,
                    m.created_at AS m_created_at,
                    m.updated_at AS m_updated_at,
                    it.id AS it_id,
                    it.meal_log_id AS it_meal_log_id,
                    it.food_item_id AS it_food_item_id,
                    it.name AS it_name,
                    it.quantity AS it_quantity,
                    it.unit AS it_unit,
                    it.calories AS it_calories,
                    it.protein_g AS it_protein_g,
                    it.carbs_g AS it_carbs_g,
                    it.fat_g AS it_fat_g,
                    it.fiber_g AS it_fiber_g,
                    it.created_at AS it_created_at
                FROM meal_logs m
                LEFT JOIN meal_log_items it ON m.id = it.meal_log_id
                WHERE m.user_id = ? AND m.date = ?
                ORDER BY m.id ASC, it.id ASC
            """, (user_id, date_str))
            rows = cursor.fetchall()

        logs_dict: Dict[int, MealLog] = {}
        for r in rows:
            m_id = r["m_id"]
            if m_id not in logs_dict:
                logs_dict[m_id] = MealLog(
                    id=m_id,
                    user_id=r["m_user_id"],
                    date=date.fromisoformat(r["m_date"][:10]),
                    meal_type=r["m_meal_type"],
                    photo_url=r.get("m_photo_url"),
                    total_calories=float(r.get("m_total_calories") or 0.0),
                    total_protein_g=float(r.get("m_total_protein_g") or 0.0),
                    total_carbs_g=float(r.get("m_total_carbs_g") or 0.0),
                    total_fat_g=float(r.get("m_total_fat_g") or 0.0),
                    total_fiber_g=float(r["m_total_fiber_g"]) if r.get("m_total_fiber_g") is not None else 0.0,
                    items=[],
                    created_at=datetime.fromisoformat(r["m_created_at"]) if r.get("m_created_at") else None,
                    updated_at=datetime.fromisoformat(r["m_updated_at"]) if r.get("m_updated_at") else None,
                )

            if r.get("it_id") is not None:
                logs_dict[m_id].items.append(
                    MealLogItem(
                        id=r["it_id"],
                        meal_log_id=r["it_meal_log_id"],
                        food_item_id=r.get("it_food_item_id"),
                        name=r["it_name"],
                        quantity=float(r["it_quantity"]),
                        unit=r["it_unit"],
                        calories=float(r["it_calories"]),
                        protein_g=float(r.get("it_protein_g") or 0.0),
                        carbs_g=float(r.get("it_carbs_g") or 0.0),
                        fat_g=float(r.get("it_fat_g") or 0.0),
                        fiber_g=float(r["it_fiber_g"]) if r.get("it_fiber_g") is not None else 0.0,
                        created_at=datetime.fromisoformat(r["it_created_at"]) if r.get("it_created_at") else None,
                    )
                )

        return list(logs_dict.values())

    def _atomic_recalculate_and_sync(self, cursor: Any, meal_log_id: int, user_id: int = 1):
        """Recalcule les totaux du MealLog et synchronise vers meals en utilisant le même curseur/connexion."""
        now_str = datetime.now(timezone.utc).isoformat()
        cursor.execute("""
            SELECT
                COALESCE(SUM(calories), 0.0) AS total_cal,
                COALESCE(SUM(protein_g), 0.0) AS total_prot,
                COALESCE(SUM(carbs_g), 0.0) AS total_carbs,
                COALESCE(SUM(fat_g), 0.0) AS total_fat,
                COALESCE(SUM(fiber_g), 0.0) AS total_fiber
            FROM meal_log_items
            WHERE meal_log_id = ?
        """, (meal_log_id,))
        totals = cursor.fetchone()

        cal = round(float(totals["total_cal"]), 1)
        prot = round(float(totals["total_prot"]), 1)
        carbs = round(float(totals["total_carbs"]), 1)
        fat = round(float(totals["total_fat"]), 1)
        fiber = round(float(totals["total_fiber"]), 1)

        cursor.execute("""
            UPDATE meal_logs
            SET total_calories = ?, total_protein_g = ?, total_carbs_g = ?,
                total_fat_g = ?, total_fiber_g = ?, updated_at = ?
            WHERE id = ? AND user_id = ?
        """, (cal, prot, carbs, fat, fiber, now_str, meal_log_id, user_id))

        cursor.execute("SELECT date, meal_type FROM meal_logs WHERE id = ? AND user_id = ?", (meal_log_id, user_id))
        ml = cursor.fetchone()
        if not ml:
            return

        date_str = ml["date"][:10]
        meal_type = ml["meal_type"]

        cursor.execute("""
            SELECT name, quantity, unit, calories, protein_g, carbs_g, fat_g, fiber_g
            FROM meal_log_items
            WHERE meal_log_id = ?
            ORDER BY id ASC
        """, (meal_log_id,))
        items_rows = cursor.fetchall()
        items_list = [
            {
                "name": r["name"],
                "portion_g": float(r["quantity"]) if r["unit"] == "g" else 100.0,
                "calories_kcal": float(r["calories"] or 0.0),
                "protein_g": float(r["protein_g"] or 0.0),
                "carbs_g": float(r["carbs_g"] or 0.0),
                "fat_g": float(r["fat_g"] or 0.0),
                "fiber_g": float(r["fiber_g"] or 0.0),
                "confidence_score": 1.0
            }
            for r in items_rows
        ]
        items_json = json.dumps(items_list)

        cursor.execute("""
            SELECT id FROM meals
            WHERE user_id = ? AND date = ? AND meal_type = ?
            ORDER BY id DESC LIMIT 1
        """, (user_id, date_str, meal_type))
        existing = cursor.fetchone()

        if cal > 0:
            if existing:
                cursor.execute("""
                    UPDATE meals
                    SET total_calories_kcal = ?, protein_g = ?, carbs_g = ?,
                        fat_g = ?, fiber_g = ?, items_json = ?
                    WHERE id = ?
                """, (cal, prot, carbs, fat, fiber, items_json, existing["id"]))
            else:
                cursor.execute("""
                    INSERT INTO meals (
                        user_id, date, meal_type, total_calories_kcal,
                        protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    user_id, date_str, meal_type, cal,
                    prot, carbs, fat, fiber,
                    None, items_json, now_str
                ))
        else:
            if existing:
                cursor.execute("DELETE FROM meals WHERE id = ?", (existing["id"],))

    def _fetch_meal_log_with_cursor(self, cursor: Any, meal_log_id: int, user_id: int = 1) -> Optional[MealLog]:
        """Charge un MealLog complet avec ses items en utilisant un curseur existant."""
        cursor.execute("""
            SELECT * FROM meal_logs
            WHERE id = ? AND user_id = ?
        """, (meal_log_id, user_id))
        ml_row = cursor.fetchone()
        if not ml_row:
            return None

        cursor.execute("""
            SELECT * FROM meal_log_items
            WHERE meal_log_id = ?
            ORDER BY id ASC
        """, (meal_log_id,))
        item_rows = cursor.fetchall()
        items = [
            MealLogItem(
                id=it["id"],
                meal_log_id=it["meal_log_id"],
                food_item_id=it.get("food_item_id"),
                name=it["name"],
                quantity=float(it["quantity"]),
                unit=it["unit"],
                calories=float(it["calories"]),
                protein_g=float(it.get("protein_g") or 0.0),
                carbs_g=float(it.get("carbs_g") or 0.0),
                fat_g=float(it.get("fat_g") or 0.0),
                fiber_g=float(it["fiber_g"]) if it.get("fiber_g") is not None else 0.0,
                created_at=datetime.fromisoformat(it["created_at"]) if it.get("created_at") else None,
            )
            for it in item_rows
        ]
        return MealLog(
            id=ml_row["id"],
            user_id=ml_row["user_id"],
            date=date.fromisoformat(ml_row["date"][:10]),
            meal_type=ml_row["meal_type"],
            photo_url=ml_row.get("photo_url"),
            total_calories=float(ml_row.get("total_calories") or 0.0),
            total_protein_g=float(ml_row.get("total_protein_g") or 0.0),
            total_carbs_g=float(ml_row.get("total_carbs_g") or 0.0),
            total_fat_g=float(ml_row.get("total_fat_g") or 0.0),
            total_fiber_g=float(ml_row["total_fiber_g"]) if ml_row.get("total_fiber_g") is not None else 0.0,
            items=items,
            created_at=datetime.fromisoformat(ml_row["created_at"]) if ml_row.get("created_at") else None,
            updated_at=datetime.fromisoformat(ml_row["updated_at"]) if ml_row.get("updated_at") else None,
        )

    def add_item_to_meal_log(
        self,
        date_val: date,
        meal_type: str,
        name: str,
        quantity: float,
        unit: str,
        calories: float,
        protein_g: float = 0.0,
        carbs_g: float = 0.0,
        fat_g: float = 0.0,
        fiber_g: float = 0.0,
        food_item_id: Optional[int] = None,
        user_id: int = 1
    ) -> MealLog:
        """Ajoute un aliment/plat à un repas pour une date et recalcule les totaux dans une seule transaction atomique."""
        date_str = date_val.isoformat()
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM meal_logs
                WHERE user_id = ? AND date = ? AND meal_type = ?
            """, (user_id, date_str, meal_type))
            row = cursor.fetchone()

            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                        ON CONFLICT (user_id, date, meal_type) DO NOTHING
                        RETURNING id;
                    """, (user_id, date_str, meal_type, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                    """, (user_id, date_str, meal_type, now_str, now_str))

                if not row:
                    cursor.execute("""
                        SELECT id FROM meal_logs
                        WHERE user_id = ? AND date = ? AND meal_type = ?
                    """, (user_id, date_str, meal_type))
                    row = cursor.fetchone()

            meal_log_id = row["id"]

            cursor.execute("""
                INSERT INTO meal_log_items (
                    meal_log_id, food_item_id, name, quantity, unit,
                    calories, protein_g, carbs_g, fat_g, fiber_g, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                meal_log_id, food_item_id, name, quantity, unit,
                calories, protein_g, carbs_g, fat_g, fiber_g, now_str
            ))

            self._atomic_recalculate_and_sync(cursor, meal_log_id, user_id=user_id)
            conn.commit()

            result_log = self._fetch_meal_log_with_cursor(cursor, meal_log_id, user_id=user_id)

        return result_log

    def batch_add_items_to_meal_log(
        self,
        date_val: date,
        meal_type: str,
        items: List[Dict[str, Any]],
        user_id: int = 1
    ) -> MealLog:
        """Ajoute une liste d'aliments/plats à un repas dans une seule transaction atomique et avec un seul recalcul."""
        if not items:
            return self.get_or_create_meal_log(date_val, meal_type, user_id=user_id)
        date_str = date_val.isoformat()
        now_str = datetime.now(timezone.utc).isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM meal_logs
                WHERE user_id = ? AND date = ? AND meal_type = ?
            """, (user_id, date_str, meal_type))
            row = cursor.fetchone()

            if not row:
                if self.is_postgres:
                    cursor.execute("""
                        INSERT INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                        ON CONFLICT (user_id, date, meal_type) DO NOTHING
                        RETURNING id;
                    """, (user_id, date_str, meal_type, now_str, now_str))
                    row = cursor.fetchone()
                else:
                    cursor.execute("""
                        INSERT OR IGNORE INTO meal_logs (user_id, date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g, created_at, updated_at)
                        VALUES (?, ?, ?, 0.0, 0.0, 0.0, 0.0, 0.0, ?, ?)
                    """, (user_id, date_str, meal_type, now_str, now_str))

                if not row:
                    cursor.execute("""
                        SELECT id FROM meal_logs
                        WHERE user_id = ? AND date = ? AND meal_type = ?
                    """, (user_id, date_str, meal_type))
                    row = cursor.fetchone()

            meal_log_id = row["id"]

            params_list = []
            for it in items:
                params_list.append((
                    meal_log_id,
                    it.get("food_item_id"),
                    it.get("name", "Aliment"),
                    float(it.get("quantity", 100.0)),
                    it.get("unit", "g"),
                    float(it.get("calories", 0.0)),
                    float(it.get("protein_g", 0.0)),
                    float(it.get("carbs_g", 0.0)),
                    float(it.get("fat_g", 0.0)),
                    float(it.get("fiber_g", 0.0)),
                    now_str
                ))

            sql = """
                INSERT INTO meal_log_items (
                    meal_log_id, food_item_id, name, quantity, unit,
                    calories, protein_g, carbs_g, fat_g, fiber_g, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            cursor.executemany(sql, params_list)

            self._atomic_recalculate_and_sync(cursor, meal_log_id, user_id=user_id)
            conn.commit()

            result_log = self._fetch_meal_log_with_cursor(cursor, meal_log_id, user_id=user_id)

        return result_log

    def delete_meal_log_item(self, item_id: int, user_id: int = 1) -> Optional[MealLog]:
        """Supprime une ligne d'aliment consommée et recalcule le repas parent dans une seule transaction atomique."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT m.id AS meal_log_id
                FROM meal_log_items it
                JOIN meal_logs m ON it.meal_log_id = m.id
                WHERE it.id = ? AND m.user_id = ?
            """, (item_id, user_id))
            row = cursor.fetchone()
            if not row:
                return None

            meal_log_id = row["meal_log_id"]
            cursor.execute("DELETE FROM meal_log_items WHERE id = ?", (item_id,))

            self._atomic_recalculate_and_sync(cursor, meal_log_id, user_id=user_id)
            conn.commit()

            result_log = self._fetch_meal_log_with_cursor(cursor, meal_log_id, user_id=user_id)

        return result_log

    def _recalculate_meal_log_totals(self, meal_log_id: int, user_id: int = 1):
        """Recalcule et met à jour les totaux d'un MealLog."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    COALESCE(SUM(calories), 0.0) AS total_cal,
                    COALESCE(SUM(protein_g), 0.0) AS total_prot,
                    COALESCE(SUM(carbs_g), 0.0) AS total_carbs,
                    COALESCE(SUM(fat_g), 0.0) AS total_fat,
                    COALESCE(SUM(fiber_g), 0.0) AS total_fiber
                FROM meal_log_items
                WHERE meal_log_id = ?
            """, (meal_log_id,))
            totals = cursor.fetchone()

            cursor.execute("""
                UPDATE meal_logs
                SET total_calories = ?, total_protein_g = ?, total_carbs_g = ?,
                    total_fat_g = ?, total_fiber_g = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
            """, (
                round(float(totals["total_cal"]), 1),
                round(float(totals["total_prot"]), 1),
                round(float(totals["total_carbs"]), 1),
                round(float(totals["total_fat"]), 1),
                round(float(totals["total_fiber"]), 1),
                now_str, meal_log_id, user_id
            ))
            conn.commit()

    def _sync_meal_log_to_meals(self, meal_log_id: int, user_id: int = 1):
        """Synchronise un meal_log avec la table meals pour alimenter l'historique et les calories journalières."""
        now_str = datetime.now(timezone.utc).isoformat()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT date, meal_type, total_calories, total_protein_g, total_carbs_g, total_fat_g, total_fiber_g FROM meal_logs WHERE id = ? AND user_id = ?", (meal_log_id, user_id))
            ml = cursor.fetchone()
            if not ml:
                return

            date_str = ml["date"][:10]
            meal_type = ml["meal_type"]
            total_cals = round(float(ml["total_calories"] or 0.0), 1)
            total_prot = round(float(ml["total_protein_g"] or 0.0), 1)
            total_carbs = round(float(ml["total_carbs_g"] or 0.0), 1)
            total_fat = round(float(ml["total_fat_g"] or 0.0), 1)
            total_fiber = round(float(ml["total_fiber_g"] or 0.0), 1)

            cursor.execute("""
                SELECT name, quantity, unit, calories, protein_g, carbs_g, fat_g, fiber_g
                FROM meal_log_items
                WHERE meal_log_id = ?
                ORDER BY id ASC
            """, (meal_log_id,))
            items_rows = cursor.fetchall()
            items_list = [
                {
                    "name": r["name"],
                    "portion_g": float(r["quantity"]) if r["unit"] == "g" else 100.0,
                    "calories_kcal": float(r["calories"] or 0.0),
                    "protein_g": float(r["protein_g"] or 0.0),
                    "carbs_g": float(r["carbs_g"] or 0.0),
                    "fat_g": float(r["fat_g"] or 0.0),
                    "fiber_g": float(r["fiber_g"] or 0.0),
                    "confidence_score": 1.0
                }
                for r in items_rows
            ]
            items_json = json.dumps(items_list)

            cursor.execute("""
                SELECT id FROM meals
                WHERE user_id = ? AND date = ? AND meal_type = ?
                ORDER BY id DESC LIMIT 1
            """, (user_id, date_str, meal_type))
            existing = cursor.fetchone()

            if total_cals > 0:
                if existing:
                    cursor.execute("""
                        UPDATE meals
                        SET total_calories_kcal = ?, protein_g = ?, carbs_g = ?,
                            fat_g = ?, fiber_g = ?, items_json = ?
                        WHERE id = ?
                    """, (total_cals, total_prot, total_carbs, total_fat, total_fiber, items_json, existing["id"]))
                else:
                    cursor.execute("""
                        INSERT INTO meals (
                            user_id, date, meal_type, total_calories_kcal,
                            protein_g, carbs_g, fat_g, fiber_g, photo_data_url, items_json, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        user_id, date_str, meal_type, total_cals,
                        total_prot, total_carbs, total_fat, total_fiber,
                        None, items_json, now_str
                    ))
            else:
                if existing:
                    cursor.execute("DELETE FROM meals WHERE id = ?", (existing["id"],))
            conn.commit()

    def sync_all_meal_logs_to_meals(self, user_id: Optional[int] = None):
        """Synchronise l'ensemble des meal_logs existants vers la table meals."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if user_id:
                cursor.execute("SELECT id, user_id FROM meal_logs WHERE user_id = ?", (user_id,))
            else:
                cursor.execute("SELECT id, user_id FROM meal_logs")
            rows = cursor.fetchall()
        for r in rows:
            self._sync_meal_log_to_meals(r["id"], user_id=r["user_id"])

    def _get_meal_log_by_id(self, meal_log_id: int, user_id: int = 1) -> MealLog:
        """Récupère un MealLog complet par son ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM meal_logs WHERE id = ? AND user_id = ?", (meal_log_id, user_id))
            row = cursor.fetchone()
        return self._build_meal_log(dict(row), user_id=user_id)
