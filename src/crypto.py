"""Module de chiffrement cryptographique des clés d'API et secrets VitalTrack.

Fournit :
- Chiffrement symétrique fort basé sur Fernet / MultiFernet (AES-128-CBC avec HMAC-SHA256)
- Support des clés versionnées et rotation sans perte via DATA_ENCRYPTION_KEYS="v2:...,v1:..."
  (préfixe 'enc:<version>::...') avec rétrocompatibilité intégrale du format mono-clé 'enc::...'
- Mode fail-closed strict en production : aucun chiffrement silencieux avec clé éphémère
  si aucune clé persistante n'est configurée (lève MissingEncryptionKeyError -> HTTP 503)
- Support pour chiffrer / déchiffrer des dictionnaires de credentials complets (JSON) ou chaînes simples
"""

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

logger = logging.getLogger("vitaltrack.crypto")

_ENCRYPTED_VALUE_RE = re.compile(r"^enc:(?:([A-Za-z0-9_-]+):)?:(.+)$")
_VERSION_LABEL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class MissingEncryptionKeyError(RuntimeError):
    """Exception levée en production si aucune clé de chiffrement persistante n'est configurée."""

    pass


@dataclass(frozen=True)
class _KeyringState:
    """État compilé des clés Fernet actives."""

    primary_version: Optional[str]
    fernets_by_version: Dict[str, Fernet]
    ordered_versions: Tuple[str, ...]
    multi_fernet: Optional[MultiFernet]
    is_ephemeral: bool


_KEYRING_LOCK = threading.Lock()
_CACHED_ENV_SIGNATURE: Optional[Tuple[str, str, str, bool]] = None
_CACHED_KEYRING: Optional[_KeyringState] = None
_DEV_EPHEMERAL_SEED: Optional[str] = None


def _is_production() -> bool:
    """Détecte si l'application tourne en environnement de production ou cloud."""
    if os.getenv("VERCEL") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    env_name = os.getenv("ENVIRONMENT") or os.getenv("ENV") or os.getenv("NODE_ENV") or ""
    return env_name.lower() in ("production", "prod", "staging")


def _get_fernet_key(seed: str) -> bytes:
    """Dérive une clé Fernet valide 32-octets base64 urlsafe à partir d'un secret arbitraire."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _parse_versioned_keys(raw_keys: str) -> List[Tuple[str, str]]:
    """Parse DATA_ENCRYPTION_KEYS au format 'v2:secret2,v1:secret1'.

    Retourne une liste ordonnée de couples (version, secret) avec la clé primaire en premier.
    """
    entries: List[Tuple[str, str]] = []
    seen_versions: set[str] = set()
    auto_idx = 1

    for raw_part in raw_keys.split(","):
        part = raw_part.strip()
        if not part:
            continue

        version: Optional[str] = None
        secret: str = part

        if ":" in part:
            candidate_ver, candidate_secret = part.split(":", 1)
            candidate_ver = candidate_ver.strip()
            candidate_secret = candidate_secret.strip()
            if candidate_ver and candidate_secret and _VERSION_LABEL_RE.match(candidate_ver):
                version = candidate_ver
                secret = candidate_secret

        if version is None:
            while f"v{auto_idx}" in seen_versions:
                auto_idx += 1
            version = f"v{auto_idx}"
            auto_idx += 1

        if not secret:
            continue

        if version in seen_versions:
            logger.warning(
                "[VitalTrack Crypto Warning] Version de clé dupliquée ignorée dans DATA_ENCRYPTION_KEYS : %s",
                version,
            )
            continue

        seen_versions.add(version)
        entries.append((version, secret))

    return entries


def _resolve_key_seed() -> str:
    """Résout la graine de clé primaire depuis DATA_ENCRYPTION_KEYS / DATA_ENCRYPTION_KEY / SECRET_KEY.

    Échoue en production (MissingEncryptionKeyError) si aucune clé persistante n'est configurée,
    ou génère une clé aléatoire en développement local.
    """
    raw_multi = (os.getenv("DATA_ENCRYPTION_KEYS") or "").strip()
    if raw_multi:
        parsed = _parse_versioned_keys(raw_multi)
        if parsed:
            return parsed[0][1]

    key_seed = (os.getenv("DATA_ENCRYPTION_KEY") or os.getenv("SECRET_KEY") or "").strip()
    if key_seed:
        return key_seed

    if _is_production():
        raise MissingEncryptionKeyError(
            "[VitalTrack Security Error] DATA_ENCRYPTION_KEY ou DATA_ENCRYPTION_KEYS doit obligatoirement être configurée "
            "en production (VERCEL/ENV=production). Aucune clé éphémère ou par défaut n'est autorisée."
        )
    return secrets.token_urlsafe(32)


def _build_keyring_from_env() -> _KeyringState:
    """Construit l'état du trousseau Fernet/MultiFernet depuis les variables d'environnement courantes."""
    global _DEV_EPHEMERAL_SEED

    raw_multi = (os.getenv("DATA_ENCRYPTION_KEYS") or "").strip()
    legacy_key = (os.getenv("DATA_ENCRYPTION_KEY") or "").strip()
    secret_key = (os.getenv("SECRET_KEY") or "").strip()
    in_prod = _is_production()

    fernets_by_version: Dict[str, Fernet] = {}
    ordered_versions: List[str] = []
    ordered_fernets: List[Fernet] = []
    seen_derived_keys: set[bytes] = set()
    primary_version: Optional[str] = None

    if raw_multi:
        parsed_entries = _parse_versioned_keys(raw_multi)
        for ver, seed in parsed_entries:
            derived = _get_fernet_key(seed)
            fernet = Fernet(derived)
            fernets_by_version[ver] = fernet
            ordered_versions.append(ver)
            if derived not in seen_derived_keys:
                ordered_fernets.append(fernet)
                seen_derived_keys.add(derived)
        if ordered_versions:
            primary_version = ordered_versions[0]

    # Ajouter DATA_ENCRYPTION_KEY (et SECRET_KEY) comme clé primaire si DATA_ENCRYPTION_KEYS est vide,
    # ou comme clé de déchiffrement rétrocompatible si DATA_ENCRYPTION_KEYS est déjà défini.
    for fallback_label, fallback_seed in (("legacy", legacy_key), ("secret_key", secret_key)):
        if not fallback_seed:
            continue
        derived = _get_fernet_key(fallback_seed)
        if derived in seen_derived_keys:
            continue
        fernet = Fernet(derived)
        ordered_fernets.append(fernet)
        seen_derived_keys.add(derived)
        if fallback_label not in fernets_by_version:
            fernets_by_version[fallback_label] = fernet
            ordered_versions.append(fallback_label)

    if ordered_fernets:
        return _KeyringState(
            primary_version=primary_version,
            fernets_by_version=fernets_by_version,
            ordered_versions=tuple(ordered_versions),
            multi_fernet=MultiFernet(ordered_fernets),
            is_ephemeral=False,
        )

    # Aucune clé persistante configurée
    if in_prod:
        return _KeyringState(
            primary_version=None,
            fernets_by_version={},
            ordered_versions=(),
            multi_fernet=None,
            is_ephemeral=False,
        )

    # En développement local uniquement : clé de session aléatoire stable pour la durée du processus
    if _DEV_EPHEMERAL_SEED is None:
        _DEV_EPHEMERAL_SEED = secrets.token_urlsafe(32)
    dev_fernet = Fernet(_get_fernet_key(_DEV_EPHEMERAL_SEED))
    return _KeyringState(
        primary_version=None,
        fernets_by_version={"dev": dev_fernet},
        ordered_versions=("dev",),
        multi_fernet=MultiFernet([dev_fernet]),
        is_ephemeral=True,
    )


def _get_keyring() -> _KeyringState:
    """Retourne le trousseau courant (recalculé automatiquement si les variables d'env changent)."""
    global _CACHED_ENV_SIGNATURE, _CACHED_KEYRING, _FERNET_INSTANCE

    env_sig = (
        (os.getenv("DATA_ENCRYPTION_KEYS") or "").strip(),
        (os.getenv("DATA_ENCRYPTION_KEY") or "").strip(),
        (os.getenv("SECRET_KEY") or "").strip(),
        _is_production(),
    )
    with _KEYRING_LOCK:
        if _CACHED_KEYRING is None or _CACHED_ENV_SIGNATURE != env_sig:
            _CACHED_KEYRING = _build_keyring_from_env()
            _CACHED_ENV_SIGNATURE = env_sig
            _FERNET_INSTANCE = _CACHED_KEYRING.multi_fernet
        return _CACHED_KEYRING


def _require_keyring() -> _KeyringState:
    """Retourne un trousseau opérationnel ou lève MissingEncryptionKeyError en production (fail-closed)."""
    keyring = _get_keyring()
    if keyring.multi_fernet is None:
        raise MissingEncryptionKeyError(
            "[VitalTrack Security Error] Chiffrement refusé (fail-closed) : aucune clé persistante "
            "(DATA_ENCRYPTION_KEYS ou DATA_ENCRYPTION_KEY) n'est configurée en production."
        )
    return keyring


# Initialisation au chargement du module sans substituer de clé éphémère en production.
_FERNET_INSTANCE: Optional[MultiFernet] = None
_initial_keyring = _get_keyring()
if _initial_keyring.multi_fernet is None and _is_production():
    logger.error(
        "[VitalTrack Security Error] DATA_ENCRYPTION_KEY / DATA_ENCRYPTION_KEYS non configurée au démarrage en production. "
        "Mode fail-closed actif : toute opération de chiffrement lèvera MissingEncryptionKeyError."
    )


def is_encrypted_value(value: Optional[str]) -> bool:
    """Indique si la chaîne suit le format chiffré VitalTrack ('enc::...' ou 'enc:<version>::...')."""
    if not value or not isinstance(value, str):
        return False
    return bool(_ENCRYPTED_VALUE_RE.match(value))


def get_active_key_version() -> Optional[str]:
    """Retourne la version de clé primaire active (ex: 'v2') ou None en mode mono-clé hérité."""
    return _get_keyring().primary_version


def get_configured_key_versions() -> List[str]:
    """Retourne les identifiants de versions actuellement chargés dans le trousseau."""
    return list(_get_keyring().ordered_versions)


def encrypt_data(data: Union[str, Dict[str, Any], None]) -> Optional[str]:
    """Chiffre une chaîne ou un dictionnaire JSON avec la clé primaire active.

    - Si DATA_ENCRYPTION_KEYS est configurée (ex: 'v2:...,v1:...'), retourne 'enc:v2::<token>'.
    - Sinon (clé unique DATA_ENCRYPTION_KEY ou dev), retourne 'enc::<token>'.
    - En production sans clé persistante configurée, lève MissingEncryptionKeyError (fail-closed).
    - Si data est None ou vide, retourne None.
    """
    if data is None:
        return None

    if isinstance(data, (dict, list)):
        raw_text = json.dumps(data)
    else:
        raw_text = str(data)
        if not raw_text.strip():
            return None

    keyring = _require_keyring()
    encrypted_bytes = keyring.multi_fernet.encrypt(raw_text.encode("utf-8"))
    token_str = encrypted_bytes.decode("utf-8")

    if keyring.primary_version:
        return f"enc:{keyring.primary_version}::{token_str}"
    return f"enc::{token_str}"


def decrypt_data(encrypted_str: Optional[str]) -> Optional[str]:
    """Déchiffre une chaîne chiffrée ('enc:<version>::...' ou 'enc::...').

    - Refuse les valeurs en clair en production (lève ValueError).
    - En production sans clé configurée, lève MissingEncryptionKeyError.
    - Supporte la rotation transparente via MultiFernet.
    """
    if not encrypted_str:
        return None

    match = _ENCRYPTED_VALUE_RE.match(encrypted_str)
    if not match:
        if _is_production():
            raise ValueError(
                "[VitalTrack Security Error] Credentials non chiffrés refusés en production "
                "(préfixe 'enc::' manquant ou 'enc:<version>::' requis)."
            )
        # Valeur en clair préexistante (tolérée uniquement hors production)
        return encrypted_str

    version_hint, token = match.group(1), match.group(2)
    keyring = _require_keyring()
    token_bytes = token.encode("utf-8")

    try:
        # Voie rapide ciblée si la version annoncée est présente dans le trousseau
        if version_hint and version_hint in keyring.fernets_by_version:
            try:
                return keyring.fernets_by_version[version_hint].decrypt(token_bytes).decode("utf-8")
            except InvalidToken:
                pass
        decrypted_bytes = keyring.multi_fernet.decrypt(token_bytes)
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as e:
        logger.error(
            "[VitalTrack Crypto Error] Échec de déchiffrement Fernet (InvalidToken) : "
            "rotation de clé ou corruption du token. Détail: %s",
            e,
        )
        return None
    except Exception as e:
        logger.error("[VitalTrack Crypto Error] Erreur inattendue lors du déchiffrement : %s", e)
        return None


def rotate_encrypted_data(encrypted_str: Optional[str]) -> Optional[str]:
    """Ré-encrypte un secret chiffré avec la clé primaire active (utile lors d'une rotation v1 -> v2)."""
    if not encrypted_str:
        return None
    plaintext = decrypt_data(encrypted_str)
    if plaintext is None:
        return None
    return encrypt_data(plaintext)


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
