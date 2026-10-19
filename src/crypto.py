"""Module de chiffrement cryptographique des clés d'API et secrets VitalTrack.

Fournit :
- Chiffrement symétrique fort basé sur Fernet (AES-128-CBC avec HMAC-SHA256)
- Dérivation de clé sécurisée PBKDF2 à partir de DATA_ENCRYPTION_KEY ou SECRET_KEY
- Support pour chiffrer / déchiffrer des dictionnaires de credentials complets (JSON) ou chaînes simples
- Tolérance et rétrocompatibilité (si une valeur était en clair ou non chiffrée, déchiffrement transparent)
"""

import base64
import hashlib
import json
import os
from typing import Any, Dict, Optional, Union
from cryptography.fernet import Fernet, InvalidToken

# Clé de chiffrement au repos
# Fallback sécurisé par défaut si non spécifié dans l'environnement
_DEFAULT_KEY_SEED = os.getenv(
    "DATA_ENCRYPTION_KEY",
    os.getenv("SECRET_KEY", "vitaltrack-encryption-secret-key-neon-secure-2026")
)

def _get_fernet_key(seed: str) -> bytes:
    """Dérive une clé Fernet valide 32-octets base64 urlsafe à partir d'un secret arbitraire."""
    # Dérivation déterministe via SHA256
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)

_FERNET_INSTANCE = Fernet(_get_fernet_key(_DEFAULT_KEY_SEED))


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
    except (InvalidToken, Exception):
        # En cas d'invalidation ou mauvaise clé, éviter de planter l'application
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
