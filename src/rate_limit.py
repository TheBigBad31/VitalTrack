"""Module de limitation de débit (Rate Limiting) pour VitalTrack (BALI-127).

Fournit un limiteur en mémoire (algorithme sliding window) compatible FastAPI et
Serverless Vercel, ainsi qu'un support optionnel de `slowapi` si installé.

Endpoints protégés par défaut :
- Authentification : `/api/auth/login` (et `/login`), `/api/auth/register` (et `/register`)
- Analyse photo IA : `/api/meals/analyze-photo`, `/api/meals/estimate`

Retourne HTTP 429 (Too Many Requests) avec l'en-tête `Retry-After` en cas de dépassement.
"""

from collections import defaultdict, deque
import math
import os
import re
import threading
import time
from typing import Callable, Deque, Dict, Optional, Tuple, Union

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse


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


class RateLimiter:
    """Limiteur de débit par fenêtre glissante en mémoire (compatible API SlowAPI / FastAPI).

    Supporte :
    - `limiter.check_request(request, bucket, rate_str)` : vérification directe ou en dépendance
    - `limiter.dependency(bucket, rate_str)` : dépendance `Depends(...)` pour routeurs FastAPI
    - `limiter.limit(rate_str)` : décorateur compatible avec l'interface `slowapi.Limiter.limit`
    - `limiter.reset()` : réinitialisation de l'état mémoire (utile pour l'isolation des tests)
    """

    def __init__(self, key_func: Callable[[Request], str] = get_remote_address, enabled: bool = True):
        self.key_func = key_func
        self.enabled = enabled
        self._lock = threading.Lock()
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._last_db_key: Optional[str] = None

    def is_enabled(self) -> bool:
        if not self.enabled:
            return False
        env_flag = os.getenv("RATE_LIMIT_ENABLED", "1").strip().lower()
        return env_flag not in ("0", "false", "no", "off")

    def reset(self) -> None:
        """Vide tous les compteurs de requêtes en mémoire."""
        with self._lock:
            self._hits.clear()

    def _sync_db_scope(self) -> None:
        """Réinitialise automatiquement les compteurs si l'instance DB de l'application a été remplacée (fixtures de test)."""
        try:
            import src.app as app_module
            current_db = getattr(app_module, "db", None)
            db_key = f"{id(current_db)}:{getattr(current_db, 'db_path', '')}" if current_db is not None else None
        except Exception:
            db_key = None

        if db_key is not None and self._last_db_key is not None and db_key != self._last_db_key:
            self._hits.clear()
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
        storage_key = f"{bucket}:{client_key}"
        now = time.monotonic()
        cutoff = now - window_seconds

        with self._lock:
            self._sync_db_scope()
            dq = self._hits[storage_key]
            while dq and dq[0] <= cutoff:
                dq.popleft()

            if len(dq) >= max_requests:
                oldest = dq[0]
                retry_after = max(1, int(math.ceil((oldest + window_seconds) - now)))
                raise RateLimitExceeded(
                    detail=f"Limite de requêtes dépassée ({resolved_rate}). Veuillez patienter {retry_after}s avant de réessayer.",
                    retry_after=retry_after,
                    limit_str=resolved_rate,
                )

            dq.append(now)

    def dependency(self, bucket: str, rate_str: Union[str, Callable[[], str]]) -> Callable[[Request], None]:
        """Crée une dépendance FastAPI `Depends(...)` appliquant la limite sur l'endpoint."""
        def _dep(request: Request) -> None:
            self.check_request(request, bucket=bucket, rate_str=rate_str)

        return _dep

    def limit(self, limit_value: Union[str, Callable[[], str]], key_func: Optional[Callable[[Request], str]] = None):
        """Décorateur compatible avec la signature `slowapi.Limiter.limit(limit_value)`."""
        import functools
        import inspect

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


# Instance globale partagée
limiter = RateLimiter(key_func=get_remote_address)

# Dépendances prêtes à l'emploi pour les routeurs FastAPI
rate_limit_login = limiter.dependency("auth_login", get_login_rate_limit)
rate_limit_register = limiter.dependency("auth_register", get_register_rate_limit)
rate_limit_photo_analysis = limiter.dependency("meals_analyze_photo", get_photo_analysis_rate_limit)


__all__ = [
    "RateLimiter",
    "RateLimitExceeded",
    "rate_limit_exceeded_handler",
    "parse_rate_limit",
    "get_remote_address",
    "limiter",
    "get_login_rate_limit",
    "get_register_rate_limit",
    "get_photo_analysis_rate_limit",
    "rate_limit_login",
    "rate_limit_register",
    "rate_limit_photo_analysis",
]
