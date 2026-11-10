"""Classe de base pour les repositories par domaine de VitalTrack."""

from typing import Any, Optional


class BaseRepository:
    """Classe de base fournissant l'accès à la connexion et aux métadonnées du moteur."""

    def __init__(self, db: Any):
        self.db = db

    @property
    def is_postgres(self) -> bool:
        return bool(self.db.is_postgres)

    def get_connection(self, user_id: Optional[int] = None):
        return self.db.get_connection(user_id=user_id)

    def _pg_bool_true(self):
        return self.db._pg_bool_true()
