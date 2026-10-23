"""Script d'exécution autonome pour la synchronisation quotidienne des capteurs santé.

Appelé par le workflow GitHub Actions .github/workflows/daily-sync.yml
pour interroger les balances connectées (Withings) et bagues de santé (Oura Ring)
et persister les nouvelles mesures dans la base SQLite de VitalTrack.
"""

import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

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
from src.connectors.registry import get_connector
from src.db import Database


def run_daily_sync(db: Optional[Database] = None):
    """Exécute la synchronisation automatique pour chaque utilisateur ayant des capteurs configurés."""
    print("=" * 60)
    print("[VitalTrack] Demarrage du script de synchronisation quotidienne multi-utilisateurs")
    print("=" * 60)

    if db is None:
        db = Database()
    today = date.today()
    start_date = today - timedelta(days=2)  # Fenêtre de synchronisation sur 48h

    print(f"[VitalTrack] Periode de synchronisation : du {start_date} au {today}")
    if db.is_postgres:
        print("[VitalTrack] Mode Base de donnees : PostgreSQL (Serverless)")
    else:
        print(f"[VitalTrack] Mode Base de donnees : SQLite local ({db.db_path})")

    users = db.get_all_users()
    if not users:
        print("[VitalTrack] Aucun utilisateur trouve en base. Initialisation de l'utilisateur par defaut.")
        db._ensure_default_user()
        users = db.get_all_users()

    print(f"[VitalTrack] Nombre d'utilisateurs a synchroniser : {len(users)}")

    for user in users:
        u_id = user["id"]
        u_email = user.get("email", f"user_{u_id}")
        u_name = user.get("name", u_email)
        print(f"\n>>> Traitement Utilisateur #{u_id} : {u_name} ({u_email})")

        user_devices = db.get_user_devices(user_id=u_id, reveal_secrets=True)
        active_devices = [d for d in user_devices if d.get("is_active") and d.get("connected")]

        if not active_devices:
            print(f"  [Info] Aucun appareil connecte et actif pour cet utilisateur.")
            # Si aucun appareil n'est configure dans user_devices pour cet utilisateur,
            # et que des variables d'environnement globales sont presentes (compatibilite CI / compte par defaut #1)
            if u_id == 1:
                _sync_user_default_env(db, u_id, start_date, today)
            continue

        for dev in active_devices:
            dev_id = dev["device_id"]
            dev_name = dev.get("name", dev_id)
            print(f"  -> Synchronisation appareil : {dev_name} ({dev_id})")

            # Construire la configuration avec les identifiants chiffrés déchiffrés
            custom_cfg = {}
            if dev.get("credentials"):
                custom_cfg.update(dev["credentials"])
            if dev.get("api_key"):
                custom_cfg["api_key"] = dev["api_key"]
            if dev.get("account_email"):
                custom_cfg["account_email"] = dev["account_email"]

            try:
                connector = get_connector(dev_id, custom_config=custom_cfg)
            except Exception as e:
                print(f"     [Erreur] Impossible d'instancier le connecteur '{dev_id}' : {e}")
                continue

            # Synchronisation des pesées
            if hasattr(connector, "sync_weights"):
                try:
                    weights = connector.sync_weights(start_date=start_date, end_date=today)
                    print(f"     Pesees recuperees : {len(weights)}")
                    for entry in weights:
                        db.insert_weight(entry, user_id=u_id)
                        print(f"       -> Pesee enregistree pour #{u_id} : {entry.date} - {entry.weight_kg} kg (MG: {entry.body_fat_pct}%)")
                except Exception as e:
                    print(f"     [Avertissement] Echec sync pesee pour {dev_id} : {e}")

            # Synchronisation des activités
            if hasattr(connector, "sync_activities"):
                try:
                    activities = connector.sync_activities(start_date=start_date, end_date=today)
                    print(f"     Activites recuperees : {len(activities)}")
                    for act in activities:
                        db.insert_activity(act, user_id=u_id)
                        print(f"       -> Activite enregistree pour #{u_id} : {act.date} - {act.steps} pas, {act.active_calories_kcal} kcal actives")
                except Exception as e:
                    print(f"     [Avertissement] Echec sync activite pour {dev_id} : {e}")

            # Mettre à jour l'horodatage de synchronisation de l'appareil
            db.update_device_sync_status(dev_id, sync_status="connected", user_id=u_id)

    print("\n" + "=" * 60)
    print(f"[VitalTrack] Synchronisation multi-utilisateurs terminee avec succes ({db.db_path})")
    print("=" * 60)


def _sync_user_default_env(db: Database, user_id: int, start_date: date, today: date):
    """Synchronisation fallback basée sur les variables d'environnement globales."""
    withings_connector = WithingsScaleConnector()
    if withings_connector.is_configured:
        print(f"  -> Synchronisation Withings Scale (Global Env / API Live)")
        weights = withings_connector.sync_weights(start_date=start_date, end_date=today)
        print(f"     Pesees recuperees : {len(weights)}")
        for entry in weights:
            db.insert_weight(entry, user_id=user_id)
            print(f"       -> Pesee enregistree pour #{user_id} : {entry.date} - {entry.weight_kg} kg")
    else:
        print("  -> Withings : Non configure via variables d'environnement")

    oura_connector = OuraRingConnector()
    if oura_connector.is_configured:
        print(f"  -> Synchronisation Oura Ring (Global Env / API Live)")
        activities = oura_connector.sync_activities(start_date=start_date, end_date=today)
        print(f"     Activites recuperees : {len(activities)}")
        for act in activities:
            db.insert_activity(act, user_id=user_id)
            print(f"       -> Activite enregistree pour #{user_id} : {act.date} - {act.steps} pas")
    else:
        print("  -> Oura Ring : Non configure via variables d'environnement")


if __name__ == "__main__":
    run_daily_sync()
