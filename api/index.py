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

from src.app import app

# Export pour Vercel (détection native ASGI FastAPI)
handler = app


