"""Tests unitaires et d'intégration pour le Catalogue d'Aliments & Plats (Stage 12)."""

import os
import tempfile
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.db import Database
from src.auth import create_access_token


@pytest.fixture
def catalog_setup():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass

    test_db = Database(db_path=temp_path)
    user1 = test_db.get_or_create_user(email="alice@vitaltrack.local", name="Alice")
    user2 = test_db.get_or_create_user(email="bob@vitaltrack.local", name="Bob")

    token1 = create_access_token(user1["id"], user1["uuid"], user1["email"], user1["name"])
    token2 = create_access_token(user2["id"], user2["uuid"], user2["email"], user2["name"])

    from src import app as app_module
    old_db = app_module.db
    app_module.db = test_db

    client = TestClient(app)

    yield {
        "db": test_db,
        "client": client,
        "user1": user1,
        "user2": user2,
        "token1": token1,
        "token2": token2,
    }

    app_module.db = old_db
    if os.path.exists(temp_path):
        try:
            os.remove(temp_path)
        except OSError:
            pass


def test_catalog_crud_and_search(catalog_setup):
    """Teste la création, lecture, recherche, mise à jour et suppression d'aliments et plats."""
    client = catalog_setup["client"]
    token1 = catalog_setup["token1"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # 1. Création d'un aliment simple
    item_food = {
        "name": "Blanc de poulet",
        "item_type": "food",
        "default_unit": "g",
        "default_quantity": 100.0,
        "calories_per_unit": 120.0,
        "protein_per_unit_g": 26.0,
        "carbs_per_unit_g": 0.0,
        "fat_per_unit_g": 1.5,
        "fiber_per_unit_g": 0.0,
        "photo_url": "data:image/jpeg;base64,mockphoto"
    }
    res_food = client.post("/api/catalog/items", json=item_food, headers=headers1)
    assert res_food.status_code == 200
    food_data = res_food.json()
    assert food_data["id"] is not None
    assert food_data["name"] == "Blanc de poulet"
    assert food_data["item_type"] == "food"
    assert food_data["calories_per_unit"] == 120.0
    food_id = food_data["id"]

    # 2. Création d'un plat préparé
    item_dish = {
        "name": "Bowl Poulet & Quinoa",
        "item_type": "dish",
        "default_unit": "portion",
        "default_quantity": 1.0,
        "calories_per_unit": 480.0,
        "protein_per_unit_g": 38.0,
        "carbs_per_unit_g": 52.0,
        "fat_per_unit_g": 12.0,
        "fiber_per_unit_g": 6.5
    }
    res_dish = client.post("/api/catalog/items", json=item_dish, headers=headers1)
    assert res_dish.status_code == 200
    dish_id = res_dish.json()["id"]

    # 3. Liste du catalogue complet
    res_list = client.get("/api/catalog/items", headers=headers1)
    assert res_list.status_code == 200
    all_items = res_list.json()
    assert len(all_items) == 2

    # 4. Filtrage par type=food
    res_filter_food = client.get("/api/catalog/items?type=food", headers=headers1)
    assert res_filter_food.status_code == 200
    foods = res_filter_food.json()
    assert len(foods) == 1
    assert foods[0]["name"] == "Blanc de poulet"

    # 5. Filtrage par type=dish
    res_filter_dish = client.get("/api/catalog/items?type=dish", headers=headers1)
    assert res_filter_dish.status_code == 200
    dishes = res_filter_dish.json()
    assert len(dishes) == 1
    assert dishes[0]["name"] == "Bowl Poulet & Quinoa"

    # 6. Recherche par nom (query q=)
    res_search = client.get("/api/catalog/items?q=poulet", headers=headers1)
    assert res_search.status_code == 200
    search_res = res_search.json()
    assert len(search_res) == 2

    res_search_specific = client.get("/api/catalog/items?q=quinoa", headers=headers1)
    assert res_search_specific.status_code == 200
    assert len(res_search_specific.json()) == 1

    # 7. Modification (PUT)
    update_payload = {
        "name": "Blanc de poulet bio",
        "calories_per_unit": 125.0,
        "protein_per_unit_g": 27.0
    }
    res_put = client.put(f"/api/catalog/items/{food_id}", json=update_payload, headers=headers1)
    assert res_put.status_code == 200
    updated_data = res_put.json()
    assert updated_data["name"] == "Blanc de poulet bio"
    assert updated_data["calories_per_unit"] == 125.0
    assert updated_data["protein_per_unit_g"] == 27.0

    # 8. Suppression (DELETE)
    res_del = client.delete(f"/api/catalog/items/{food_id}", headers=headers1)
    assert res_del.status_code == 200
    assert res_del.json()["status"] == "success"

    # Vérification après suppression
    res_after = client.get("/api/catalog/items", headers=headers1)
    assert len(res_after.json()) == 1
    assert res_after.json()[0]["id"] == dish_id


def test_catalog_multi_user_isolation(catalog_setup):
    """Vérifie l'étanchéité stricte du catalogue entre Alice et Bob."""
    client = catalog_setup["client"]
    token1 = catalog_setup["token1"]
    token2 = catalog_setup["token2"]
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # Alice ajoute un aliment
    client.post("/api/catalog/items", json={
        "name": "Pomme Gala",
        "item_type": "food",
        "default_unit": "pièce",
        "default_quantity": 1.0,
        "calories_per_unit": 80.0
    }, headers=headers1)

    # Bob ajoute un plat
    client.post("/api/catalog/items", json={
        "name": "Steak Frites Bob",
        "item_type": "dish",
        "default_unit": "portion",
        "default_quantity": 1.0,
        "calories_per_unit": 750.0
    }, headers=headers2)

    # Alice ne voit QUE sa pomme
    alice_items = client.get("/api/catalog/items", headers=headers1).json()
    assert len(alice_items) == 1
    assert alice_items[0]["name"] == "Pomme Gala"

    # Bob ne voit QUE son steak
    bob_items = client.get("/api/catalog/items", headers=headers2).json()
    assert len(bob_items) == 1
    assert bob_items[0]["name"] == "Steak Frites Bob"

    # Bob ne peut pas modifier l'aliment d'Alice
    alice_item_id = alice_items[0]["id"]
    res_bad_put = client.put(f"/api/catalog/items/{alice_item_id}", json={"name": "Hacked"}, headers=headers2)
    assert res_bad_put.status_code == 404

    # Bob ne peut pas supprimer l'aliment d'Alice
    res_bad_del = client.delete(f"/api/catalog/items/{alice_item_id}", headers=headers2)
    assert res_bad_del.status_code == 404


def test_dish_with_recipe_items_composition(catalog_setup):
    """Teste la création d'un plat composé d'ingrédients existants avec ajustement des quantités et précalcul."""
    client = catalog_setup["client"]
    token1 = catalog_setup["token1"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    # 1. Alice ajoute deux ingrédients au catalogue : Pain complet et Beurre doux
    res_pain = client.post("/api/catalog/items", json={
        "name": "Pain complet",
        "item_type": "food",
        "default_unit": "g",
        "default_quantity": 100.0,
        "calories_per_unit": 247.0,
        "protein_per_unit_g": 9.0,
        "carbs_per_unit_g": 45.0,
        "fat_per_unit_g": 2.0,
        "fiber_per_unit_g": 7.0
    }, headers=headers1)
    assert res_pain.status_code == 200
    pain_id = res_pain.json()["id"]

    res_beurre = client.post("/api/catalog/items", json={
        "name": "Beurre doux",
        "item_type": "food",
        "default_unit": "g",
        "default_quantity": 100.0,
        "calories_per_unit": 720.0,
        "protein_per_unit_g": 0.7,
        "carbs_per_unit_g": 0.7,
        "fat_per_unit_g": 82.0,
        "fiber_per_unit_g": 0.0
    }, headers=headers1)
    assert res_beurre.status_code == 200
    beurre_id = res_beurre.json()["id"]

    # 2. Composition du plat : Tartine beurrée (40g pain + 10g beurre)
    recipe_items = [
        {
            "food_item_id": pain_id,
            "name": "Pain complet",
            "quantity": 40.0,
            "unit": "g",
            "default_quantity": 100.0,
            "calories_per_unit": 247.0,
            "protein_per_unit_g": 9.0,
            "carbs_per_unit_g": 45.0,
            "fat_per_unit_g": 2.0,
            "fiber_per_unit_g": 7.0,
            "calories": 98.8,
            "protein_g": 3.6,
            "carbs_g": 18.0,
            "fat_g": 0.8,
            "fiber_g": 2.8
        },
        {
            "food_item_id": beurre_id,
            "name": "Beurre doux",
            "quantity": 10.0,
            "unit": "g",
            "default_quantity": 100.0,
            "calories_per_unit": 720.0,
            "protein_per_unit_g": 0.7,
            "carbs_per_unit_g": 0.7,
            "fat_per_unit_g": 82.0,
            "fiber_per_unit_g": 0.0,
            "calories": 72.0,
            "protein_g": 0.1,
            "carbs_g": 0.1,
            "fat_g": 8.2,
            "fiber_g": 0.0
        }
    ]

    res_dish = client.post("/api/catalog/items", json={
        "name": "Tartine beurrée",
        "item_type": "dish",
        "default_unit": "portion",
        "default_quantity": 1.0,
        "calories_per_unit": 171.0,
        "protein_per_unit_g": 3.7,
        "carbs_per_unit_g": 18.1,
        "fat_per_unit_g": 9.0,
        "fiber_per_unit_g": 2.8,
        "recipe_items": recipe_items
    }, headers=headers1)

    assert res_dish.status_code == 200
    dish_data = res_dish.json()
    assert dish_data["name"] == "Tartine beurrée"
    assert dish_data["item_type"] == "dish"
    assert len(dish_data["recipe_items"]) == 2
    assert dish_data["recipe_items"][0]["name"] == "Pain complet"
    assert dish_data["recipe_items"][0]["quantity"] == 40.0
    assert dish_data["recipe_items"][1]["name"] == "Beurre doux"
    assert dish_data["recipe_items"][1]["quantity"] == 10.0

    dish_id = dish_data["id"]
    list_res = client.get("/api/catalog/items?type=dish", headers=headers1).json()
    my_dish = next(d for d in list_res if d["id"] == dish_id)
    assert len(my_dish["recipe_items"]) == 2
    assert my_dish["recipe_items"][0]["quantity"] == 40.0


def test_public_catalog_and_subscriptions(catalog_setup):
    """Teste le catalogue public partagé, le filtrage par source et l'abonnement aux amis."""
    client = catalog_setup["client"]
    token1 = catalog_setup["token1"]
    token2 = catalog_setup["token2"]
    user1 = catalog_setup["user1"]
    user2 = catalog_setup["user2"]
    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    # 1. Vérification de la présence des aliments publics du socle
    res_pub = client.get("/api/catalog/items?source=public", headers=headers1)
    assert res_pub.status_code == 200
    public_items = res_pub.json()
    assert len(public_items) >= 10
    assert any(it["name"] == "Flocons d'avoine complets" for it in public_items)
    assert any(it["name"] == "Blanc de poulet rôti" for it in public_items)
    assert all(it["is_public"] is True for it in public_items)

    # 2. Alice crée un aliment personnel et un plat personnalisé
    client.post("/api/catalog/items", json={
        "name": "Porridge Maison Alice",
        "item_type": "dish",
        "default_unit": "bol",
        "default_quantity": 1.0,
        "calories_per_unit": 320.0,
        "protein_per_unit_g": 18.0,
        "carbs_per_unit_g": 45.0,
        "fat_per_unit_g": 6.0
    }, headers=headers1)

    # Bob consulte sans abonnement :
    # source=mine -> vide
    bob_mine = client.get("/api/catalog/items?source=mine", headers=headers2).json()
    assert len(bob_mine) == 0

    # source=friends -> vide (pas encore abonné)
    bob_friends = client.get("/api/catalog/items?source=friends", headers=headers2).json()
    assert len(bob_friends) == 0

    # source=all -> seulement les publics
    bob_all = client.get("/api/catalog/items?source=all", headers=headers2).json()
    assert len(bob_all) == len(public_items)
    assert not any(it["name"] == "Porridge Maison Alice" for it in bob_all)

    # 3. Bob explore le catalogue d'Alice (friend_id)
    res_explore = client.get(f"/api/catalog/friends/{user1['id']}/items", headers=headers2)
    assert res_explore.status_code == 200
    explore_data = res_explore.json()
    assert explore_data["friend"]["id"] == user1["id"]
    assert explore_data["is_subscribed"] is False
    assert len(explore_data["items"]) == 1
    assert explore_data["items"][0]["name"] == "Porridge Maison Alice"

    # 4. Bob s'abonne au catalogue d'Alice par email
    res_sub = client.post("/api/catalog/subscriptions", json={"email": "alice@vitaltrack.local"}, headers=headers2)
    assert res_sub.status_code == 200
    assert res_sub.json()["status"] == "success"

    # Vérification dans la liste des abonnements de Bob
    res_subs_list = client.get("/api/catalog/subscriptions", headers=headers2)
    assert res_subs_list.status_code == 200
    subs = res_subs_list.json()
    assert len(subs) == 1
    assert subs[0]["target_user_id"] == user1["id"]
    assert subs[0]["target_user_name"] == "Alice"

    # 5. Bob filtre source=friends -> Il voit le porridge d'Alice
    bob_friends_after = client.get("/api/catalog/items?source=friends", headers=headers2).json()
    assert len(bob_friends_after) == 1
    assert bob_friends_after[0]["name"] == "Porridge Maison Alice"

    # Bob filtre source=all -> Publics + Amis abonnés
    bob_all_after = client.get("/api/catalog/items?source=all", headers=headers2).json()
    assert len(bob_all_after) == len(public_items) + 1
    assert any(it["name"] == "Porridge Maison Alice" for it in bob_all_after)

    # 6. Synchronisation automatique : Alice met à jour sa recette
    alice_items = client.get("/api/catalog/items?source=mine", headers=headers1).json()
    alice_dish_id = next(it["id"] for it in alice_items if it["name"] == "Porridge Maison Alice")
    client.put(f"/api/catalog/items/{alice_dish_id}", json={
        "name": "Porridge Protéiné Alice",
        "calories_per_unit": 350.0,
        "protein_per_unit_g": 24.0
    }, headers=headers1)

    # Bob voit immédiatement la mise à jour reflétée
    bob_friends_updated = client.get("/api/catalog/items?source=friends", headers=headers2).json()
    assert len(bob_friends_updated) == 1
    assert bob_friends_updated[0]["name"] == "Porridge Protéiné Alice"
    assert bob_friends_updated[0]["calories_per_unit"] == 350.0
    assert bob_friends_updated[0]["protein_per_unit_g"] == 24.0

    # 7. Bob se désabonne du catalogue d'Alice
    res_unsub = client.delete(f"/api/catalog/subscriptions/{user1['id']}", headers=headers2)
    assert res_unsub.status_code == 200

    # Bob ne voit plus l'aliment dans ses amis
    bob_friends_empty = client.get("/api/catalog/items?source=friends", headers=headers2).json()
    assert len(bob_friends_empty) == 0


def test_get_food_items_eliminates_n_plus_1(catalog_setup, monkeypatch):
    """Vérifie que get_food_items charge les bienfaits en une seule requête groupée sans appel N+1 unitaire."""
    db = catalog_setup["db"]
    client = catalog_setup["client"]
    token1 = catalog_setup["token1"]
    user1 = catalog_setup["user1"]
    headers1 = {"Authorization": f"Bearer {token1}"}

    for idx in range(5):
        res = client.post(
            "/api/catalog/items",
            json={
                "name": f"Aliment Perf {idx}",
                "item_type": "food",
                "default_unit": "g",
                "default_quantity": 100.0,
                "calories_per_unit": 100.0 + idx * 10,
            },
            headers=headers1,
        )
        assert res.status_code == 200

    def forbidden_per_item_benefits(*args, **kwargs):
        raise AssertionError("get_food_item_benefits ne doit pas être appelé en boucle dans get_food_items (N+1)")

    monkeypatch.setattr(db, "get_food_item_benefits", forbidden_per_item_benefits)

    items = db.get_food_items(user_id=user1["id"], source="all")
    assert len(items) >= 5
    for it in items:
        assert hasattr(it, "benefits")
        assert isinstance(it.benefits, list)

