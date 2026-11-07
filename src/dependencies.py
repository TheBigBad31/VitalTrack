"""Dépendances partagées FastAPI pour VitalTrack.

Ce module centralise les accesseurs et factories d'injection de dépendances
afin de découpler les routeurs du module central `src.app` et éliminer
tout risque d'import circulaire.
"""

from typing import Optional
from src.db import Database

# Instance globale partagée
_db_instance: Optional[Database] = None


def set_db(db: Database) -> None:
    """Enregistre l'instance Database courante."""
    global _db_instance
    _db_instance = db


def get_db() -> Database:
    """Factory de dépendance retournant l'instance Database active.

    Garantit la compatibilité ascendante avec les monkeypatches de tests sur `src.app.db`.
    """
    import sys
    app_module = sys.modules.get("src.app")
    if app_module and hasattr(app_module, "db") and app_module.db is not None:
        return app_module.db

    global _db_instance
    if _db_instance is not None:
        return _db_instance

    _db_instance = Database()
    return _db_instance
