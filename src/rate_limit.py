"""Module de limitation de débit (Rate Limiting) pour VitalTrack (BALI-127 & BALI-212 / VTR-103).

Fournit un limiteur distribué basé sur Upstash Redis / Vercel KV (REST API)
avec bascule transparente en mémoire (algorithme sliding window) en développement local
ou si les identifiants Redis ne sont pas configurés.

Variables d'environnement :
- `UPSTASH_REDIS_REST_URL` ou `KV_REST_API_URL` : URL de l'API REST Upstash Redis / Vercel KV
- `UPSTASH_REDIS_REST_TOKEN` ou `KV_REST_API_TOKEN` : Jeton d'autorisation Bearer
- `RATE_LIMIT_ENABLED` : Activer/désactiver le rate limiting ("1" / "0")
- `RATE_LIMIT_LOGIN` : Limite pour l'authentification (défaut : "10/minute")
- `RATE_LIMIT_REGISTER` : Limite pour l'inscription (défaut : "15/minute")
- `RATE_LIMIT_PHOTO_ANALYSIS` : Limite pour l'analyse photo IA (défaut : "15/minute")
- `RATE_LIMIT_WEBHOOK` : Limite pour les webhooks santé IoT (défaut : "60/minute")

Endpoints protégés par défaut :
- Authentification : `/api/auth/login` (et `/login`), `/api/auth/register` (et `/register`)
- Analyse photo IA : `/api/meals/analyze-photo`, `/api/meals/estimate`
- Webhooks IoT : `/api/webhook/health`

Retourne HTTP 429 (Too Many Requests) avec l'en-tête `Retry-After` en cas de dépassement.
"""

from abc import ABC, abstractmethod
from collections import defaultdict, deque
import functools
import inspect
import logging
import math
import os
import re
import threading
import time
from typing import Callable, Deque, Dict, Optional, Tuple, Union
import uuid

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
import httpx

logger = logging.getLogger(__name__)

_RATE_REGEX = re.compile(r"^\s*(\d+)\s*/\s*(second|sec|s|minute|min|m|hour|hr|h|day|d)\s*$", re.IGNORECASE)

_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hr": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
}

# Script Lua atomique pour algorithme de fenêtre glissante dans Upstash Redis
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_requests = tonumber(ARGV[3])
local member = ARGV[4]

local cutoff = now - window
redis.call('ZREMRANGEBYSCORE', key, 0, cutoff)
local count = redis.call('ZCARD', key)

if count >= max_requests then
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local retry_after = math.ceil(window)
    if oldest and #oldest >= 2 then
        local oldest_score = tonumber(oldest[2])
        if oldest_score then
            retry_after = math.ceil(oldest_score + window - now)
            if retry_after < 1 then retry_after = 1 end
        end
    end
    return {0, count, retry_after}
else
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 5)
    return {1, max_requests - count - 1, 0}
end
"""


def parse_rate_limit(rate_str: str) -> Tuple[int, int]:
    """Parse une chaîne de limite de type '10/minute' en (max_requests, window_seconds)."""
    match = _RATE_REGEX.match(str(rate_str or ""))
    if not match:
        return 10, 60
    count = max(1, int(match.group(1)))
    unit = match.group(2).lower()
    window = _UNIT_SECONDS.get(unit, 60)
    return count, window


def get_remote_address(request: Request) -> str:
    """Extrait l'adresse IP cliente depuis X-Forwarded-For (Vercel/Proxy) ou request.client."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first_ip = forwarded.split(",")[0].strip()
        if first_ip:
            return first_ip
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    if request.client and request.client.host:
        return str(request.client.host)
    return "127.0.0.1"


def get_upstash_redis_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Récupère l'URL REST et le token Upstash Redis ou Vercel KV depuis l'environnement."""
    url = os.getenv("UPSTASH_REDIS_REST_URL") or os.getenv("KV_REST_API_URL")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN") or os.getenv("KV_REST_API_TOKEN")
    if url:
        url = url.strip().rstrip("/")
    if token:
        token = token.strip()
    return (url or None, token or None)


class RateLimitExceeded(HTTPException):
    """Exception levée lorsqu'une limite de débit est dépassée (HTTP 429)."""

    def __init__(self, detail: str = "Trop de requêtes. Veuillez réessayer plus tard.", retry_after: int = 60, limit_str: str = ""):
        headers = {"Retry-After": str(max(1, int(retry_after)))}
        if limit_str:
            headers["X-RateLimit-Limit"] = limit_str
        super().__init__(status_code=429, detail=detail, headers=headers)
        self.retry_after = max(1, int(retry_after))
        self.limit_str = limit_str


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Gestionnaire d'exception FastAPI retournant une réponse JSON 429 standardisée."""
    retry_after = getattr(exc, "retry_after", 60)
    detail = getattr(exc, "detail", "Trop de requêtes. Veuillez réessayer plus tard.")
    headers = dict(getattr(exc, "headers", {}) or {})
    headers.setdefault("Retry-After", str(retry_after))
    return JSONResponse(
        status_code=429,
        content={
            "status": "error",
            "error": "Too Many Requests",
            "detail": str(detail),
            "retry_after": retry_after,
        },
        headers=headers,
    )


class BaseRateLimitBackend(ABC):
    """Interface abstraite pour les backends de stockage du rate limiting."""

    @abstractmethod
    def check(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        """Vérifie si la requête est autorisée.

        Retourne un triplet:
        (autorisé: bool, requêtes_restantes: int, retry_after_secondes: int)
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Réinitialise les compteurs enregistrés dans ce backend."""
        pass


class InMemoryBackend(BaseRateLimitBackend):
    """Backend en mémoire avec fenêtre glissante (sliding window deque)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)

    def check(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            dq = self._hits[key]
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) >= max_requests:
                oldest = dq[0]
                retry_after = max(1, int(math.ceil((oldest + window_seconds) - now)))
                return False, 0, retry_after

            dq.append(now)
            return True, max_requests - len(dq), 0

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


class UpstashRedisBackend(BaseRateLimitBackend):
    """Backend distribué pour Upstash Redis / Vercel KV via API REST HTTPS."""

    def __init__(
        self,
        url: str,
        token: str,
        timeout: float = 2.0,
        fallback_backend: Optional[BaseRateLimitBackend] = None,
    ):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.fallback = fallback_backend or InMemoryBackend()
        self._client: Optional[httpx.Client] = None
        self._lock = threading.Lock()
        self._touched_keys: set = set()

    def _get_client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            self._client.close()

    def check(self, key: str, max_requests: int, window_seconds: int) -> Tuple[bool, int, int]:
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:8]}"
        with self._lock:
            self._touched_keys.add(key)

        try:
            client = self._get_client()
            # 1. Tentative d'exécution via le script Lua atomique EVAL
            eval_payload = ["EVAL", LUA_SLIDING_WINDOW, 1, key, str(now), str(window_seconds), str(max_requests), member]
            resp = client.post(self.url, json=eval_payload)

            if resp.status_code == 200:
                data = resp.json()
                if "error" in data:
                    logger.warning("Upstash Redis EVAL a retourné une erreur : %s. Bascule en pipeline fallback.", data["error"])
                    return self._check_pipeline(key, max_requests, window_seconds, now, member)

                result = data.get("result")
                if isinstance(result, (list, tuple)) and len(result) >= 3:
                    allowed = bool(result[0])
                    remaining = int(result[1])
                    retry_after = int(result[2])
                    return allowed, remaining, retry_after

            # Si non 200, tenter le pipeline standard
            return self._check_pipeline(key, max_requests, window_seconds, now, member)

        except Exception as exc:
            logger.warning("Erreur Upstash Redis REST (%s) : %s. Bascule transparente sur backend mémoire.", type(exc).__name__, exc)
            return self.fallback.check(key, max_requests, window_seconds)

    def _check_pipeline(self, key: str, max_requests: int, window_seconds: int, now: float, member: str) -> Tuple[bool, int, int]:
        """Méthode alternative en pipeline REST sans Lua si EVAL est restreint."""
        try:
            client = self._get_client()
            cutoff = now - window_seconds
            pipe_query = [
                ["ZREMRANGEBYSCORE", key, "0", str(cutoff)],
                ["ZCARD", key],
                ["ZRANGE", key, "0", "0", "WITHSCORES"],
            ]
            resp = client.post(f"{self.url}/pipeline", json=pipe_query)
            if resp.status_code != 200:
                return self.fallback.check(key, max_requests, window_seconds)

            results = resp.json()
            card = int(results[1].get("result", 0))
            oldest_list = results[2].get("result", [])

            if card >= max_requests:
                retry_after = math.ceil(window_seconds)
                if oldest_list and len(oldest_list) >= 2:
                    try:
                        oldest_score = float(oldest_list[1])
                        retry_after = max(1, int(math.ceil(oldest_score + window_seconds - now)))
                    except (ValueError, TypeError):
                        pass
                return False, 0, retry_after

            # Ajouter le nouveau hit
            add_query = [
                ["ZADD", key, str(now), member],
                ["EXPIRE", key, str(int(math.ceil(window_seconds)) + 5)],
            ]
            client.post(f"{self.url}/pipeline", json=add_query)
            return True, max_requests - card - 1, 0

        except Exception as exc:
            logger.warning("Erreur fallback pipeline Upstash : %s. Bascule en mémoire.", exc)
            return self.fallback.check(key, max_requests, window_seconds)

    def reset(self) -> None:
        """Supprime les clés touchées sur Upstash Redis et réinitialise le fallback."""
        self.fallback.reset()
        with self._lock:
            keys_to_delete = list(self._touched_keys)
            self._touched_keys.clear()

        if not keys_to_delete:
            return

        try:
            client = self._get_client()
            pipeline = [["DEL", k] for k in keys_to_delete]
            client.post(f"{self.url}/pipeline", json=pipeline)
        except Exception as exc:
            logger.debug("Exception lors de la suppression des clés Upstash lors du reset : %s", exc)


class RateLimiter:
    """Limiteur de débit multi-backend (Upstash Redis / Vercel KV distribué avec fallback in-memory).

    Supporte :
    - Détection automatique d'Upstash Redis via UPSTASH_REDIS_REST_URL / UPSTASH_REDIS_REST_TOKEN
    - Support direct de Vercel KV (KV_REST_API_URL / KV_REST_API_TOKEN)
    - Fallback transparent en mémoire (sliding window deque) pour le dev local et les tests
    - `limiter.check_request(request, bucket, rate_str)` : vérification directe ou en dépendance
    - `limiter.dependency(bucket, rate_str)` : dépendance `Depends(...)` pour routeurs FastAPI
    - `limiter.limit(rate_str)` : décorateur compatible avec l'interface `slowapi.Limiter.limit`
    - `limiter.reset()` : réinitialisation de l'état (utile pour l'isolation des tests)
    """

    def __init__(
        self,
        key_func: Callable[[Request], str] = get_remote_address,
        enabled: bool = True,
        backend: Optional[BaseRateLimitBackend] = None,
    ):
        self.key_func = key_func
        self.enabled = enabled
        self._explicit_backend = backend
        self._current_creds: Optional[Tuple[Optional[str], Optional[str]]] = None
        self._cached_backend: Optional[BaseRateLimitBackend] = None
        self._last_db_key: Optional[str] = None

    @property
    def backend(self) -> BaseRateLimitBackend:
        if self._explicit_backend is not None:
            return self._explicit_backend

        creds = get_upstash_redis_credentials()
        if self._cached_backend is None or creds != self._current_creds:
            self._current_creds = creds
            url, token = creds
            if url and token:
                logger.info("Configuration du Rate Limiter distribué Upstash Redis (%s)", url)
                self._cached_backend = UpstashRedisBackend(url=url, token=token)
            else:
                self._cached_backend = InMemoryBackend()
        return self._cached_backend

    @property
    def _hits(self) -> Dict[str, Deque[float]]:
        """Compatibilité ascendante pour les fixtures de tests manipulant `_hits`."""
        b = self.backend
        if isinstance(b, InMemoryBackend):
            return b._hits
        if hasattr(b, "fallback") and isinstance(b.fallback, InMemoryBackend):
            return b.fallback._hits
        return defaultdict(deque)

    @property
    def _lock(self) -> threading.Lock:
        """Compatibilité ascendante pour le lock in-memory."""
        b = self.backend
        if isinstance(b, InMemoryBackend):
            return b._lock
        if hasattr(b, "fallback") and isinstance(b.fallback, InMemoryBackend):
            return b.fallback._lock
        return threading.Lock()

    def is_enabled(self) -> bool:
        if not self.enabled:
            return False
        env_flag = os.getenv("RATE_LIMIT_ENABLED", "1").strip().lower()
        return env_flag not in ("0", "false", "no", "off")

    def reset(self) -> None:
        """Vide tous les compteurs de requêtes (backend actif + fallback)."""
        self.backend.reset()

    def _sync_db_scope(self) -> None:
        """Réinitialise automatiquement les compteurs si l'instance DB de l'application a été remplacée (fixtures de test)."""
        try:
            import src.app as app_module
            current_db = getattr(app_module, "db", None)
            db_key = f"{id(current_db)}:{getattr(current_db, 'db_path', '')}" if current_db is not None else None
        except Exception:
            db_key = None

        if db_key is not None and self._last_db_key is not None and db_key != self._last_db_key:
            self.reset()
        self._last_db_key = db_key

    def check_request(
        self,
        request: Request,
        bucket: str,
        rate_str: Union[str, Callable[[], str]],
    ) -> None:
        """Vérifie et incrémente le compteur pour la requête donnée. Lève RateLimitExceeded (429) si dépassé."""
        if not self.is_enabled():
            return

        resolved_rate = rate_str() if callable(rate_str) else str(rate_str)
        max_requests, window_seconds = parse_rate_limit(resolved_rate)
        client_key = self.key_func(request)
        storage_key = f"ratelimit:{bucket}:{client_key}"

        self._sync_db_scope()

        allowed, remaining, retry_after = self.backend.check(
            key=storage_key,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )

        if not allowed:
            raise RateLimitExceeded(
                detail=f"Limite de requêtes dépassée ({resolved_rate}). Veuillez patienter {retry_after}s avant de réessayer.",
                retry_after=retry_after,
                limit_str=resolved_rate,
            )

    def dependency(self, bucket: str, rate_str: Union[str, Callable[[], str]]) -> Callable[[Request], None]:
        """Crée une dépendance FastAPI `Depends(...)` appliquant la limite sur l'endpoint."""
        def _dep(request: Request) -> None:
            self.check_request(request, bucket=bucket, rate_str=rate_str)

        return _dep

    def limit(self, limit_value: Union[str, Callable[[], str]], key_func: Optional[Callable[[Request], str]] = None):
        """Décorateur compatible avec la signature `slowapi.Limiter.limit(limit_value)`."""
        def decorator(func: Callable):
            bucket = f"{func.__module__}.{func.__qualname__}"

            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    req = self._extract_request(args, kwargs)
                    if req is not None:
                        self.check_request(req, bucket=bucket, rate_str=limit_value)
                    return await func(*args, **kwargs)
                return async_wrapper
            else:
                @functools.wraps(func)
                def sync_wrapper(*args, **kwargs):
                    req = self._extract_request(args, kwargs)
                    if req is not None:
                        self.check_request(req, bucket=bucket, rate_str=limit_value)
                    return func(*args, **kwargs)
                return sync_wrapper

        return decorator

    @staticmethod
    def _extract_request(args: tuple, kwargs: dict) -> Optional[Request]:
        for val in kwargs.values():
            if isinstance(val, Request):
                return val
        for val in args:
            if isinstance(val, Request):
                return val
        return None


# Définition des limites configurables par variables d'environnement
def get_login_rate_limit() -> str:
    return os.getenv("RATE_LIMIT_LOGIN", "10/minute")


def get_register_rate_limit() -> str:
    return os.getenv("RATE_LIMIT_REGISTER", "15/minute")


def get_photo_analysis_rate_limit() -> str:
    return os.getenv("RATE_LIMIT_PHOTO_ANALYSIS", "15/minute")


def get_webhook_rate_limit() -> str:
    return os.getenv("RATE_LIMIT_WEBHOOK", "60/minute")


# Instance globale partagée
limiter = RateLimiter(key_func=get_remote_address)

# Dépendances prêtes à l'emploi pour les routeurs FastAPI
rate_limit_login = limiter.dependency("auth_login", get_login_rate_limit)
rate_limit_register = limiter.dependency("auth_register", get_register_rate_limit)
rate_limit_photo_analysis = limiter.dependency("meals_analyze_photo", get_photo_analysis_rate_limit)
rate_limit_webhook = limiter.dependency("webhook_health", get_webhook_rate_limit)


__all__ = [
    "RateLimiter",
    "RateLimitExceeded",
    "rate_limit_exceeded_handler",
    "parse_rate_limit",
    "get_remote_address",
    "get_upstash_redis_credentials",
    "BaseRateLimitBackend",
    "InMemoryBackend",
    "UpstashRedisBackend",
    "limiter",
    "get_login_rate_limit",
    "get_register_rate_limit",
    "get_photo_analysis_rate_limit",
    "get_webhook_rate_limit",
    "rate_limit_login",
    "rate_limit_register",
    "rate_limit_photo_analysis",
    "rate_limit_webhook",
]
