"""Tests unitaires de la couche DAO pour la gestion des amitiés et du partage de données (friendships)."""
import os
import tempfile
import pytest

from src.db import Database


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_path = f.name

    db = Database(db_path=temp_path, database_url=None, auto_migrate=True)
    yield db

    try:
        os.remove(temp_path)
    except OSError:
        pass


def test_friendships_crud_and_lifecycle(temp_db):
    """Teste le cycle de vie complet d'une amitié : création, acceptation, listage, révocation, permission."""
    # Création de deux utilisateurs de test
    u1 = temp_db.get_or_create_user(
        email="alice@vitaltrack.io",
        password_hash="fakehash1",
        name="Alice Dupont",
        auth_provider="password"
    )
    u2 = temp_db.get_or_create_user(
        email="bob@vitaltrack.io",
        password_hash="fakehash2",
        name="Bob Martin",
        auth_provider="password"
    )
    u1_id = u1["id"]
    u2_id = u2["id"]

    # 1. Avant toute demande, pas de permission de lecture croisée
    assert temp_db.check_read_permission(owner_id=u1_id, viewer_id=u1_id) is True
    assert temp_db.check_read_permission(owner_id=u1_id, viewer_id=u2_id) is False
    assert temp_db.check_read_permission(owner_id=u2_id, viewer_id=u1_id) is False

    # 2. Alice envoie une demande d'ami à Bob via son email
    req = temp_db.create_friend_request(user_id=u1_id, friend_email_or_username="bob@vitaltrack.io")
    assert req["id"] is not None
    assert req["user_id"] == u1_id
    assert req["friend_id"] == u2_id
    assert req["status"] == "pending"
    assert req["permission"] == "read_only"

    # Vérification du listage chez Alice
    alice_lists = temp_db.list_friendships(user_id=u1_id)
    assert len(alice_lists["friends"]) == 0
    assert len(alice_lists["pending_sent"]) == 1
    assert alice_lists["pending_sent"][0]["target_id"] == u2_id
    assert len(alice_lists["pending_received"]) == 0

    # Vérification du listage chez Bob
    bob_lists = temp_db.list_friendships(user_id=u2_id)
    assert len(bob_lists["friends"]) == 0
    assert len(bob_lists["pending_sent"]) == 0
    assert len(bob_lists["pending_received"]) == 1
    assert bob_lists["pending_received"][0]["requester_id"] == u1_id

    # Toujours pas de permission tant que c'est 'pending'
    assert temp_db.check_read_permission(owner_id=u1_id, viewer_id=u2_id) is False

    # 3. Bob répond et accepte la demande
    req_id = req["id"]
    accepted_req = temp_db.respond_friend_request(request_id=req_id, target_user_id=u2_id, status="accepted")
    assert accepted_req["status"] == "accepted"

    # 4. Vérification des permissions et listes après acceptation
    assert temp_db.check_read_permission(owner_id=u1_id, viewer_id=u2_id) is True
    assert temp_db.check_read_permission(owner_id=u2_id, viewer_id=u1_id) is True

    alice_lists_acc = temp_db.list_friendships(user_id=u1_id)
    assert len(alice_lists_acc["friends"]) == 1
    assert alice_lists_acc["friends"][0]["friend_user_id"] == u2_id
    assert len(alice_lists_acc["pending_sent"]) == 0
    assert len(alice_lists_acc["pending_received"]) == 0

    bob_lists_acc = temp_db.list_friendships(user_id=u2_id)
    assert len(bob_lists_acc["friends"]) == 1
    assert bob_lists_acc["friends"][0]["friend_user_id"] == u1_id

    # 5. Révocation de l'amitié par Alice
    revoked = temp_db.revoke_friendship(user_id=u1_id, friend_id=u2_id)
    assert revoked is True

    # Après révocation, la permission est révoquée et ils ne sont plus dans 'friends'
    assert temp_db.check_read_permission(owner_id=u1_id, viewer_id=u2_id) is False
    assert temp_db.check_read_permission(owner_id=u2_id, viewer_id=u1_id) is False
    assert len(temp_db.list_friendships(user_id=u1_id)["friends"]) == 0


def test_friend_request_validations_and_edge_cases(temp_db):
    """Teste les cas limites : auto-invitation, utilisateur inexistant, permission de réponse non autorisée."""
    u1 = temp_db.get_or_create_user("charlie@vitaltrack.io", name="Charlie")
    u2 = temp_db.get_or_create_user("david@vitaltrack.io", name="David")
    u3 = temp_db.get_or_create_user("eve@vitaltrack.io", name="Eve")

    # Impossible de s'ajouter soi-même
    with pytest.raises(ValueError, match="Vous ne pouvez pas vous ajouter vous-même"):
        temp_db.create_friend_request(u1["id"], "charlie@vitaltrack.io")

    # Utilisateur inconnu
    with pytest.raises(ValueError, match="Aucun utilisateur trouvé"):
        temp_db.create_friend_request(u1["id"], "unknown@vitaltrack.io")

    # Chaîne vide
    with pytest.raises(ValueError):
        temp_db.create_friend_request(u1["id"], "   ")

    # Charlie invite David
    req = temp_db.create_friend_request(u1["id"], "david@vitaltrack.io")

    # Eve tente d'accepter la demande adressée à David -> PermissionError
    with pytest.raises(PermissionError):
        temp_db.respond_friend_request(request_id=req["id"], target_user_id=u3["id"], status="accepted")

    # Statut invalide
    with pytest.raises(ValueError, match="Statut invalide"):
        temp_db.respond_friend_request(request_id=req["id"], target_user_id=u2["id"], status="invalid_status")

    # David refuse la demande
    rejected = temp_db.respond_friend_request(request_id=req["id"], target_user_id=u2["id"], status="rejected")
    assert rejected["status"] == "rejected"
    assert temp_db.check_read_permission(u1["id"], u2["id"]) is False

    # Charlie ré-invite David par son pseudo "David"
    re_req = temp_db.create_friend_request(u1["id"], "David")
    assert re_req["status"] == "pending"


def test_friend_request_mutual_auto_accept(temp_db):
    """Si Bob envoie une requête à Alice alors qu'Alice lui a déjà envoyé une requête pending, elle est auto-acceptée."""
    u1 = temp_db.get_or_create_user("user_a@vitaltrack.io", name="User A")
    u2 = temp_db.get_or_create_user("user_b@vitaltrack.io", name="User B")

    # Alice invite Bob
    req1 = temp_db.create_friend_request(u1["id"], "user_b@vitaltrack.io")
    assert req1["status"] == "pending"

    # Bob invite Alice
    req2 = temp_db.create_friend_request(u2["id"], "user_a@vitaltrack.io")
    assert req2["status"] == "accepted"

    assert temp_db.check_read_permission(u1["id"], u2["id"]) is True
