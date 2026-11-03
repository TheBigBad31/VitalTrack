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
from src.crypto import decrypt_credentials
from src.db import Database


def run_daily_sync(db: Optional[Database] = None) -> bool:
    """Exécute la synchronisation automatique pour chaque utilisateur ayant des capteurs configurés."""
    print("=" * 60)
    print("[VitalTrack] Demarrage du script de synchronisation quotidienne multi-utilisateurs")
    print("=" * 60)

    if db is None:
        db = Database()
    today = date.today()
    start_date = today - timedelta(days=2)
    error_count = 0

    all_users = db.get_all_users()
    if not all_users:
        print("[Info] Aucun utilisateur enregistre dans la base. Synchronisation sur l'environnement par defaut...")
        success = _sync_user_default_env(db, user_id=1, start_date=start_date, today=today)
        if not success:
            error_count += 1
        return error_count == 0

    print(f"[Info] {len(all_users)} utilisateur(s) trouve(s).")

    for user in all_users:
        u_id = user["id"]
        u_email = user.get("email", f"user_{u_id}")
        print(f"\n---> Traitement de l'utilisateur #{u_id} ({u_email})")

        devices = db.get_user_devices(user_id=u_id, reveal_secrets=True)
        if not devices:
            print(f"  -> Aucun appareil associe pour #{u_id}.")
            continue

        for dev in devices:
            dev_id = dev["device_id"]
            if not dev.get("is_active", True):
                print(f"  -> Appareil {dev_id} ignore (inactif).")
                continue

            print(f"  -> Synchronisation appareil : {dev.get('name', dev_id)} (Type: {dev_id})")

            custom_cfg = {}
            if dev.get("encrypted_credentials"):
                custom_cfg = decrypt_credentials(dev["encrypted_credentials"]) or {}
            elif dev.get("api_key"):
                custom_cfg["api_key"] = dev["api_key"]
                custom_cfg["personal_access_token"] = dev["api_key"]

            if dev.get("account_email"):
                custom_cfg["account_email"] = dev["account_email"]

            try:
                connector = get_connector(dev_id, custom_config=custom_cfg)
            except Exception as e:
                print(f"     [Erreur] Impossible d'instancier le connecteur '{dev_id}' : {e}")
                error_count += 1
                continue

            # Synchronisation des pesées
            if hasattr(connector, "sync_weights"):
                try:
                    weights = connector.sync_weights(start_date=start_date, end_date=today)
                    print(f"     Pesees recuperees : {len(weights)}")
                    valid_weights = []
                    for entry in weights:
                        if entry.source in ("simulation", "demo") and getattr(connector, "is_production", False):
                            print(f"       -> Ignore (simulation non autorisee en production) : {entry.date}")
                            continue
                        valid_weights.append(entry)
                    if valid_weights:
                        if hasattr(db, "batch_insert_weights"):
                            db.batch_insert_weights(valid_weights, user_id=u_id)
                        else:
                            for entry in valid_weights:
                                db.insert_weight(entry, user_id=u_id)
                        print(f"       -> {len(valid_weights)} pesee(s) enregistree(s) pour #{u_id}")
                        try:
                            from src.app import invalidate_dashboard_cache
                            invalidate_dashboard_cache(u_id)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"     [Avertissement] Echec sync pesee pour {dev_id} : {e}")
                    error_count += 1

            # Synchronisation des activités
            if hasattr(connector, "sync_activities"):
                try:
                    activities = connector.sync_activities(start_date=start_date, end_date=today)
                    print(f"     Activites recuperees : {len(activities)}")
                    valid_acts = []
                    for act in activities:
                        if act.source in ("simulation", "demo") and getattr(connector, "is_production", False):
                            print(f"       -> Ignore (simulation non autorisee en production) : {act.date}")
                            continue
                        valid_acts.append(act)
                    if valid_acts:
                        if hasattr(db, "batch_insert_activities"):
                            db.batch_insert_activities(valid_acts, user_id=u_id)
                        else:
                            for act in valid_acts:
                                db.insert_activity(act, user_id=u_id)
                        print(f"       -> {len(valid_acts)} activite(s) enregistree(s) pour #{u_id}")
                        try:
                            from src.app import invalidate_dashboard_cache
                            invalidate_dashboard_cache(u_id)
                        except Exception:
                            pass
                except Exception as e:
                    print(f"     [Avertissement] Echec sync activite pour {dev_id} : {e}")
                    error_count += 1

            # Mettre à jour l'horodatage de synchronisation de l'appareil
            db.update_device_sync_status(dev_id, sync_status="connected", user_id=u_id)

    print("\n" + "=" * 60)
    if error_count > 0:
        print(f"[VitalTrack] Synchronisation terminee avec {error_count} erreur(s) ({db.db_path})")
        print("=" * 60)
        return False
    else:
        print(f"[VitalTrack] Synchronisation multi-utilisateurs terminee avec succes ({db.db_path})")
        print("=" * 60)
        return True


def _sync_user_default_env(db: Database, user_id: int, start_date: date, today: date) -> bool:
    """Synchronisation fallback basée sur les variables d'environnement globales."""
    has_errors = False
    withings_connector = WithingsScaleConnector()
    if withings_connector.is_configured:
        print(f"  -> Synchronisation Withings Scale (Global Env / API Live)")
        try:
            weights = withings_connector.sync_weights(start_date=start_date, end_date=today)
            print(f"     Pesees recuperees : {len(weights)}")
            if hasattr(db, "batch_insert_weights"):
                db.batch_insert_weights(weights, user_id=user_id)
            else:
                for entry in weights:
                    db.insert_weight(entry, user_id=user_id)
        except Exception as e:
            print(f"     [Erreur] Sync Withings : {e}")
            has_errors = True
    else:
        print("  -> Withings : Non configure via variables d'environnement")

    oura_connector = OuraRingConnector()
    if oura_connector.is_configured:
        print(f"  -> Synchronisation Oura Ring (Global Env / API Live)")
        try:
            activities = oura_connector.sync_activities(start_date=start_date, end_date=today)
            print(f"     Activites recuperees : {len(activities)}")
            if hasattr(db, "batch_insert_activities"):
                db.batch_insert_activities(activities, user_id=user_id)
            else:
                for act in activities:
                    db.insert_activity(act, user_id=user_id)
        except Exception as e:
            print(f"     [Erreur] Sync Oura : {e}")
            has_errors = True
    else:
        print("  -> Oura Ring : Non configure via variables d'environnement")

    return not has_errors


if __name__ == "__main__":
    success = run_daily_sync()
    if not success:
        sys.exit(1)
