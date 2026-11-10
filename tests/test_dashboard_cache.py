import time
from unittest.mock import MagicMock
import pytest

from src.cache import DashboardCache


def test_dashboard_cache_ttl_expiration():
    """Vérifie l'expiration automatique selon le TTL."""
    cache = DashboardCache(ttl=0.1, maxsize=10)
    key = (1, False)
    cache.set(key, {"data": "ok"})
    
    assert cache.get(key) == {"data": "ok"}
    assert key in cache
    
    time.sleep(0.15)
    assert cache.get(key) is None
    assert key not in cache


def test_dashboard_cache_maxsize_eviction():
    """Vérifie l'éviction LRU/TTL quand la taille max est atteinte (anti fuite mémoire)."""
    cache = DashboardCache(ttl=60.0, maxsize=3)
    cache.set((1, False), {"user": 1})
    cache.set((2, False), {"user": 2})
    cache.set((3, False), {"user": 3})
    
    assert len(cache.keys()) == 3
    
    # Ajout du 4ème élément : doit évincer le plus ancien
    cache.set((4, False), {"user": 4})
    assert len(cache.keys()) == 3
    assert cache.get((4, False)) == {"user": 4}
    assert cache.get((1, False)) is None


def test_dashboard_cache_invalidation_user_and_global():
    """Vérifie l'invalidation ciblée par utilisateur et globale."""
    cache = DashboardCache(ttl=60.0, maxsize=10)
    cache.set((1, False), {"data": "u1_f"})
    cache.set((1, True), {"data": "u1_t"})
    cache.set((2, False), {"data": "u2_f"})
    
    # Invalidation utilisateur 1
    cache.invalidate(user_id=1)
    assert cache.get((1, False)) is None
    assert cache.get((1, True)) is None
    assert cache.get((2, False)) == {"data": "u2_f"}
    
    # Invalidation globale
    cache.invalidate(None)
    assert cache.get((2, False)) is None
    assert len(cache.keys()) == 0


def test_dashboard_cache_redis_integration(monkeypatch):
    """Vérifie l'intégration distribuée avec un client Redis mocké."""
    mock_redis = MagicMock()
    mock_storage = {}

    def mock_get(k):
        return mock_storage.get(k)

    def mock_set(k, v, ex=None):
        mock_storage[k] = v
        return True

    def mock_keys(pattern):
        import fnmatch
        return [k for k in mock_storage.keys() if fnmatch.fnmatch(k, pattern)]

    def mock_delete(*keys):
        for k in keys:
            mock_storage.pop(k, None)

    def mock_exists(k):
        return k in mock_storage

    mock_redis.get.side_effect = mock_get
    mock_redis.set.side_effect = mock_set
    mock_redis.keys.side_effect = mock_keys
    mock_redis.delete.side_effect = mock_delete
    mock_redis.exists.side_effect = mock_exists

    cache = DashboardCache(ttl=30.0, maxsize=10)
    cache._redis_client = mock_redis

    key = (42, False)
    cache.set(key, {"metrics": [1, 2, 3]})
    assert mock_redis.set.called
    assert "dashboard:42:false" in mock_storage

    val = cache.get(key)
    assert val == {"metrics": [1, 2, 3]}

    # Invalidation ciblée
    cache.invalidate(user_id=42)
    assert "dashboard:42:false" not in mock_storage
    assert cache.get(key) is None
