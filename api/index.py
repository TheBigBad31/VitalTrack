"""Point d'entrée Serverless Vercel pour VitalTrack.

Expose l'instance FastAPI `app` définie dans `src.app`.
Garantit que la base de données est initialisée et résout les chemins dynamiques
réécrits par Vercel Serverless (?__path=...).
"""

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode

# S'assurer que la racine du projet est dans sys.path
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from src.app import app as raw_app


class VercelPathResolver:
    """Middleware ASGI qui restaure le chemin d'API réel lors d'une exécution Vercel Serverless."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            raw_query = scope.get("query_string", b"").decode("utf-8", errors="ignore")
            params = parse_qs(raw_query, keep_blank_values=True)
            current_path = scope.get("path", "")

            # 1. Si Vercel a injecté __path via la règle de rewrite vercel.json
            if "__path" in params:
                subpath = params["__path"][0].lstrip("/")
                scope["path"] = f"/api/{subpath}" if subpath else "/api"

                # Nettoyer __path de la query_string pour ne pas polluer FastAPI
                del params["__path"]
                flat_params = [(k, v) for k, vs in params.items() for v in vs]
                scope["query_string"] = urlencode(flat_params).encode("utf-8")

            # 2. Si le chemin reçu est le fichier physique /api/index.py ou /api/index
            elif current_path in ("/api/index.py", "/api/index", "/api"):
                # Vérifier si Vercel a envoyé le header interne x-matched-path
                headers = dict(scope.get("headers", []))
                matched = headers.get(b"x-matched-path", b"").decode("utf-8", errors="ignore")
                if matched and matched != current_path:
                    scope["path"] = matched
                else:
                    scope["path"] = "/api/health"

            # 3. Si le chemin reçu ne commence pas par /api mais est une route backend connue
            elif not current_path.startswith("/api") and current_path not in ("/", "/docs", "/openapi.json", "/static"):
                scope["path"] = f"/api{current_path}"

        await self.asgi_app(scope, receive, send)


app = VercelPathResolver(raw_app)
handler = app

