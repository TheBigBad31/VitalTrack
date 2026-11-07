"""Middleware et utilitaires pour la gestion de l'API Versioning et des dépréciations (RFC 8594 / RFC 9110).

Headers gérés :
- Deprecation: @<timestamp> ou true (RFC 8594)
- Sunset: <HTTP-date> (RFC 8594)
- Link: <uri>; rel="deprecation" ou rel="successor-version"
- X-API-Version: v1 | v2
"""

from datetime import datetime, timezone
import re
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# Date de Sunset pour la v1 (ex: fin de support planifiée le 31 décembre 2026)
V1_SUNSET_DATE = "Thu, 31 Dec 2026 23:59:59 GMT"
V2_DOCS_URL = "/api/v2/docs"


class APIVersioningMiddleware(BaseHTTPMiddleware):
    """Injecte les headers de versioning et de dépréciation selon la version demandée."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        response: Response = await call_next(request)

        # Détection de la version de l'API
        if path.startswith("/api/v2"):
            response.headers["X-API-Version"] = "v2"
        elif path.startswith("/api/v1"):
            response.headers["X-API-Version"] = "v1"
            # v1 est active et supportée, mais annotée avec les recommandations d'évolution v2
            response.headers["Link"] = f'<{V2_DOCS_URL}>; rel="successor-version"'
        elif path.startswith("/api") and not path.startswith(("/api/docs", "/api/openapi.json")):
            # Endpoints historiques non préfixés (/api/...) : considérés comme v1 dépréciée au profit de /api/v1/ ou /api/v2/
            response.headers["X-API-Version"] = "v1-legacy"
            response.headers["Deprecation"] = "true"
            response.headers["Sunset"] = V1_SUNSET_DATE
            response.headers["Link"] = f'</api/v1{path[4:]}>; rel="alternate", <{V2_DOCS_URL}>; rel="successor-version"'

        return response
