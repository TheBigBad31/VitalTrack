"""Script d'exécution autonome pour la synchronisation quotidienne des capteurs santé.

Appelé par le workflow GitHub Actions .github/workflows/daily-sync.yml
pour interroger les balances connectées (Withings) et bagues de santé (Oura Ring)
et persister les nouvelles mesures dans la base SQLite de VitalTrack.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Fix pour encodage Windows stdout
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ajouter la racine du projet dans sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from src.connectors.withings import WithingsScaleConnector
from src.connectors.oura import OuraRingConnector
from src.db import Database


def run_daily_sync():
    """Exécute la synchronisation automatique des capteurs Withings et Oura."""
    print("=" * 60)
    print("[VitalTrack] Demarrage du script de synchronisation quotidienne")
    print("=" * 60)

    db = Database()
    # Script batch sans contexte utilisateur : cible explicitement le compte principal
    user_id = db._ensure_default_user()["id"]
    today = date.today()
    start_date = today - timedelta(days=2)  # Fenêtre de synchronisation sur 48h
    
    print(f"[VitalTrack] Periode de synchronisation : du {start_date} au {today}")

    # 1. Synchronisation Withings (Pesées, composition corporelle)
    print("\n--- Synchronisation Withings Scale ---")
    withings_connector = WithingsScaleConnector()
    print(f"Statut Withings : {'Configure (API Live)' if withings_connector.is_configured else 'Mode Demo/Simulation'}")
    
    weights = withings_connector.sync_weights(start_date=start_date, end_date=today)
    print(f"Pesees recuperees : {len(weights)}")
    for entry in weights:
        db.insert_weight(entry, user_id=user_id)
        print(f"  -> Enregistre : {entry.date} - {entry.weight_kg} kg (MG: {entry.body_fat_pct}%, MM: {entry.muscle_mass_kg} kg)")

    # 2. Synchronisation Oura Ring (Sommeil, HRV, pas, calories actives)
    print("\n--- Synchronisation Oura Ring ---")
    oura_connector = OuraRingConnector()
    print(f"Statut Oura : {'Configure (API Live)' if oura_connector.is_configured else 'Mode Demo/Simulation'}")

    activities = oura_connector.sync_activities(start_date=start_date, end_date=today)
    print(f"Activites recuperees : {len(activities)}")
    for act in activities:
        db.insert_activity(act, user_id=user_id)
        print(f"  -> Enregistre : {act.date} - {act.steps} pas, {act.active_calories_kcal} kcal actives, HRV: {act.hrv_ms} ms, Sommeil: {act.sleep_score}/100")

    print("\n" + "=" * 60)
    print(f"[VitalTrack] Synchronisation terminee avec succes ({db.db_path})")
    print("=" * 60)


if __name__ == "__main__":
    run_daily_sync()
