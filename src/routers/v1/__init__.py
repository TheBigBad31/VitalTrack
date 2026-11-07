"""Factory pour cloner ou monter les routeurs sous le préfixe /api/v1.

Gère la réécriture de préfixe pour exposer explicitement /api/v1/...
à partir des routeurs modulaires de base.
"""

from fastapi import APIRouter
from fastapi.routing import APIRoute

def create_v1_router(source_router: APIRouter) -> APIRouter:
    """Crée un router v1 dérivé en réécrivant les préfixes /api vers /api/v1."""
    v1_router = APIRouter()
    for route in source_router.routes:
        if isinstance(route, APIRoute):
            original_path = route.path
            if original_path.startswith("/api/"):
                new_path = "/api/v1" + original_path[4:]
            elif original_path == "/api":
                new_path = "/api/v1"
            else:
                new_path = "/api/v1" + ("" if original_path.startswith("/") else "/") + original_path

            v1_router.add_api_route(
                new_path,
                route.endpoint,
                methods=route.methods,
                response_model=route.response_model,
                status_code=route.status_code,
                tags=route.tags or ["v1"],
                dependencies=route.dependencies,
                summary=route.summary,
                description=route.description,
                response_description=route.response_description,
                responses=route.responses,
                deprecated=route.deprecated,
                name=route.name,
            )
    return v1_router
