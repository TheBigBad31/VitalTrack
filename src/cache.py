"""Cache de données pour VitalTrack (TTLCache local en mémoire avec support optionnel Upstash Redis / Redis distribué)."""

import json
import logging
import os
import threading
from typing import Any, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 45.0
DEFAULT_MAXSIZE = 1000

# Tentative d'import de cachetools avec fallback dict si non disponible
try:
    from cachetools import TTLCache
except ImportError:
    TTLCache = None  # type: ignore

# Tentative d'import de redis
try:
    import redis
except ImportError:
    redis = None  # type: ignore


class DashboardCache:
    """Gestionnaire de cache hybride pour le dashboard.
    
    Supporte:
    1. Upstash Redis / Redis distribué via REDIS_URL ou UPSTASH_REDIS_REST_URL/REDIS_URI si configuré.
    2. Fallback automatique sur cachetools.TTLCache (avec maxsize anti-fuite mémoire et thread-safety).
    Expose également une interface dict-like pour rétro-compatibilité (ex: `cache_key in DASHBOARD_CACHE`, `DASHBOARD_CACHE[cache_key]`).
    """

    def __init__(self, ttl: float = DEFAULT_TTL_SECONDS, maxsize: int = DEFAULT_MAXSIZE):
        self.ttl = ttl
        self.maxsize = maxsize
        self._lock = threading.RLock()
        
        # Initialisation du cache local
        if TTLCache is not None:
            self._local_cache = TTLCache(maxsize=self.maxsize, ttl=self.ttl)
        else:
            self._local_cache = {}

        self._redis_client = None
        self._init_redis()

    def _init_redis(self) -> None:
        """Initialise la connexion Redis si REDIS_URL ou UPSTASH_REDIS_URL est présent."""
        redis_url = os.getenv("UPSTASH_REDIS_URL") or os.getenv("REDIS_URL")
        if redis_url and redis is not None:
            try:
                # Upstash Redis supporte redis-py avec ssl si rediss://
                self._redis_client = redis.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=2.0,
                )
                # Test ping rapide
                self._redis_client.ping()
                logger.info("DashboardCache: Connecté avec succès à Redis (%s)", redis_url.split("@")[-1])
            except Exception as e:
                logger.warning("DashboardCache: Impossible de se connecter à Redis (%s), fallback local TTLCache actif.", e)
                self._redis_client = None

    def _make_key(self, key: Any) -> str:
        if isinstance(key, tuple):
            return f"dashboard:{key[0]}:{str(key[1]).lower()}"
        return f"dashboard:{key}"

    def get(self, key: Tuple[int, bool]) -> Optional[Any]:
        """Récupère la valeur en cache pour la clé (user_id, include_simulation)."""
        # 1. Tentative Redis si disponible
        if self._redis_client is not None:
            try:
                redis_key = self._make_key(key)
                val = self._redis_client.get(redis_key)
                if val is not None:
                    return json.loads(val)
            except Exception as e:
                logger.debug("DashboardCache Redis get error: %s", e)

        # 2. Fallback cache local
        with self._lock:
            val = self._local_cache.get(key)
            if val is not None and not isinstance(self._local_cache, TTLCache):
                # Fallback dict simple avec timestamp
                ts, data = val
                import time
                if time.time() - ts < self.ttl:
                    return data
                else:
                    self._local_cache.pop(key, None)
                    return None
            return val

    def set(self, key: Tuple[int, bool], value: Any, ttl: Optional[float] = None) -> None:
        """Stocke une valeur en cache avec TTL."""
        expiry = int(ttl or self.ttl)
        # 1. Redis
        if self._redis_client is not None:
            try:
                redis_key = self._make_key(key)
                self._redis_client.set(redis_key, json.dumps(value), ex=expiry)
            except Exception as e:
                logger.debug("DashboardCache Redis set error: %s", e)

        # 2. Cache local
        with self._lock:
            if isinstance(self._local_cache, TTLCache):
                self._local_cache[key] = value
            else:
                import time
                self._local_cache[key] = (time.time(), value)

    def invalidate(self, user_id: Optional[int] = None) -> None:
        """Invalide le cache globalement ou pour un utilisateur spécifique."""
        # 1. Redis
        if self._redis_client is not None:
            try:
                if user_id is None:
                    # Invalide tous les dashboards
                    keys = self._redis_client.keys("dashboard:*")
                    if keys:
                        self._redis_client.delete(*keys)
                else:
                    pattern = f"dashboard:{user_id}:*"
                    keys = self._redis_client.keys(pattern)
                    if keys:
                        self._redis_client.delete(*keys)
            except Exception as e:
                logger.debug("DashboardCache Redis invalidate error: %s", e)

        # 2. Local
        with self._lock:
            if user_id is None:
                self._local_cache.clear()
            else:
                to_delete = [k for k in list(self._local_cache.keys()) if (isinstance(k, tuple) and k[0] == user_id)]
                for k in to_delete:
                    self._local_cache.pop(k, None)

    # Compatibilité dict-like pour le code existant et les tests
    def __contains__(self, key: Any) -> bool:
        if self._redis_client is not None:
            try:
                redis_key = self._make_key(key)
                if self._redis_client.exists(redis_key):
                    return True
            except Exception:
                pass
        with self._lock:
            return key in self._local_cache

    def __getitem__(self, key: Any) -> Any:
        # Pour compatibilité avec cached_ts, cached_payload = DASHBOARD_CACHE[cache_key]
        import time
        if self._redis_client is not None:
            try:
                redis_key = self._make_key(key)
                val = self._redis_client.get(redis_key)
                if val is not None:
                    return (time.time(), json.loads(val))
            except Exception:
                pass
        with self._lock:
            val = self._local_cache[key]
            if isinstance(self._local_cache, TTLCache):
                return (time.time(), val)
            return val

    def __setitem__(self, key: Any, val: Any) -> None:
        # Pour compatibilité DASHBOARD_CACHE[cache_key] = (now_ts, dashboard_res) ou DASHBOARD_CACHE[cache_key] = val
        if isinstance(val, tuple) and len(val) == 2 and isinstance(val[0], (int, float)):
            actual_val = val[1]
        else:
            actual_val = val
        self.set(key, actual_val)

    def pop(self, key: Any, default: Any = None) -> Any:
        if self._redis_client is not None:
            try:
                redis_key = self._make_key(key)
                self._redis_client.delete(redis_key)
            except Exception:
                pass
        with self._lock:
            return self._local_cache.pop(key, default)

    def clear(self) -> None:
        self.invalidate(None)

    def keys(self):
        with self._lock:
            return list(self._local_cache.keys())


# Instance singleton globale
dashboard_cache = DashboardCache(ttl=DEFAULT_TTL_SECONDS, maxsize=DEFAULT_MAXSIZE)
