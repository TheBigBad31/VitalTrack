"""Point d'entrée Serverless Vercel pour VitalTrack.

Expose l'instance FastAPI `app` définie dans `src.app`.
Garantit que /tmp/vitaltrack.db est initialisé et prêt lors de chaque invocation lambda.
"""

import sys
from pathlib import Path

# S'assurer que la racine du projet est dans sys.path
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

from src.app import app

# Export pour Vercel
handler = app
