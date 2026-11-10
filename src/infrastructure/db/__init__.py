"""Infrastructure Database - Neon / SQLite Persistence."""
from src.db import Database, DatabaseConnectionWrapper, DatabaseCursorWrapper

def get_db() -> Database:
    """Helper factory retournant l'instance Database singleton."""
    return Database()

__all__ = ["Database", "DatabaseConnectionWrapper", "DatabaseCursorWrapper", "get_db"]
