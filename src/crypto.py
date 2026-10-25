"""Module de chiffrement cryptographique des clés d'API et secrets VitalTrack.

Fournit :
- Chiffrement symétrique fort basé sur Fernet (AES-128-CBC avec HMAC-SHA256)
- Dérivation de clé sécurisée SHA-256 / HKDF à partir de DATA_ENCRYPTION_KEY ou SECRET_KEY
- Validation fail-closed au démarrage en environnement de production (interdiction de clé par défaut)
- Support pour chiffrer / déchiffrer des dictionnaires de credentials complets (JSON) ou chaînes simples
- Tolérance et rétrocompatibilité (si une valeur était en clair ou non chiffrée, déchiffrement transparent)
- Logging des erreurs de déchiffrement pour audit et rotation de clés
"""

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, Optional, Union
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("vitaltrack.crypto")


class MissingEncryptionKeyError(RuntimeError):
    """Exception levée en production si aucune clé de chiffrement valide n'est configurée."""
    pass


def _is_production() -> bool:
    """Détecte si l'application tourne en environnement de production ou cloud."""
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    env_name = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV") or ""
    return env_name.lower() in ("production", "prod", "staging")


def _resolve_key_seed() -> str:
    """Résout la clé de chiffrement ou échoue strictement en production."""
    key_seed = os.getenv("DATA_ENCRYPTION_KEY") or os.getenv("SECRET_KEY")
    if not key_seed:
        if _is_production():
            raise MissingEncryptionKeyError(
                "[VitalTrack Security Error] DATA_ENCRYPTION_KEY ou SECRET_KEY doit obligatoirement être configurée en production. "
                "Le fallback de clé en clair est strictement interdit."
            )
        # Clé réservée uniquement pour le développement local et les tests unitaires
        key_seed = "vitaltrack-dev-local-only-insecure-key-2026"
    return key_seed


def _get_fernet_key(seed: str) -> bytes:
    """Dérive une clé Fernet valide 32-octets base64 urlsafe à partir d'un secret arbitraire."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


_FERNET_INSTANCE = Fernet(_get_fernet_key(_resolve_key_seed()))


def encrypt_data(data: Union[str, Dict[str, Any], None]) -> Optional[str]:
    """Chiffre une chaîne ou un dictionnaire JSON avec Fernet.
    
    Retourne la chaîne chiffrée préfixée par 'enc::'.
    Si data est None ou vide, retourne None.
    """
    if data is None:
        return None
    
    if isinstance(data, (dict, list)):
        raw_text = json.dumps(data)
    else:
        raw_text = str(data)
        if not raw_text.strip():
            return None

    encrypted_bytes = _FERNET_INSTANCE.encrypt(raw_text.encode("utf-8"))
    return f"enc::{encrypted_bytes.decode('utf-8')}"


def decrypt_data(encrypted_str: Optional[str]) -> Optional[str]:
    """Déchiffre une chaîne préalablement chiffrée.
    
    Si la chaîne n'est pas chiffrée (sans préfixe 'enc::'), la retourne telle quelle
    pour assurer une rétrocompatibilité parfaite.
    """
    if not encrypted_str:
        return None
    
    if not encrypted_str.startswith("enc::"):
        # Valeur en clair préexistante
        return encrypted_str
    
    token = encrypted_str[len("enc::"):]
    try:
        decrypted_bytes = _FERNET_INSTANCE.decrypt(token.encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as e:
        logger.error(f"[VitalTrack Crypto Error] Échec de déchiffrement Fernet (InvalidToken) : rotation de clé ou corruption du token. Détail: {e}")
        return None
    except Exception as e:
        logger.error(f"[VitalTrack Crypto Error] Erreur inattendue lors du déchiffrement : {e}")
        return None


def encrypt_credentials(credentials: Optional[Dict[str, Any]]) -> Optional[str]:
    """Chiffre un objet dictionnaire de credentials (ex: api_key, access_token, refresh_token)."""
    if not credentials:
        return None
    return encrypt_data(credentials)


def decrypt_credentials(encrypted_str: Optional[str]) -> Dict[str, Any]:
    """Déchiffre un dictionnaire de credentials chiffré.
    
    Retourne un dict vide si aucune donnée ou si la désérialisation échoue.
    Gère aussi le cas où la valeur originale était simplement une chaîne api_key.
    """
    if not encrypted_str:
        return {}
    
    raw = decrypt_data(encrypted_str)
    if not raw:
        return {}
    
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"api_key": str(parsed)}
    except json.JSONDecodeError:
        return {"api_key": raw}
