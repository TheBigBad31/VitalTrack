"""Tests de non-régression pour BALI-324 :
- Déchiffrement legacy / clé manquante dans DevicesRepository._format_device_row
- Extraction api_key_hash dans la migration 0011_fix_friendships_rls_and_api_key_hash
"""

import importlib.util
from pathlib import Path
import pytest

from src.crypto import MissingEncryptionKeyError
from src.repositories import devices as devices_module
from src.repositories.devices import DevicesRepository


def test_format_device_row_legacy_decrypt_error_no_crash(monkeypatch):
    repo = DevicesRepository(db=None)

    def _raise_value_error(_val):
        raise ValueError("legacy unencrypted value")

    monkeypatch.setattr(devices_module, "decrypt_data", _raise_value_error)

    row = {
        "user_id": 1,
        "device_id": "health_connect",
        "connected": 1,
        "api_key": "legacy-plaintext-token-1234",
        "encrypted_credentials": None,
    }
    formatted = repo._format_device_row(row, reveal_secrets=False)
    assert formatted is not None
    assert formatted["has_credentials"] is True
    assert formatted["api_key_masked"] is None
    assert "api_key" not in formatted


def test_format_device_row_missing_key_no_crash_when_reveal_false(monkeypatch):
    repo = DevicesRepository(db=None)

    def _raise_missing_key(_val):
        raise MissingEncryptionKeyError("DATA_ENCRYPTION_KEY missing")

    monkeypatch.setattr(devices_module, "decrypt_credentials", _raise_missing_key)

    row = {
        "user_id": 1,
        "device_id": "withings",
        "connected": 1,
        "api_key": None,
        "encrypted_credentials": "enc::v1:deadbeef",
    }
    formatted = repo._format_device_row(row, reveal_secrets=False)
    assert formatted is not None
    assert formatted["has_credentials"] is True
    assert formatted["api_key_masked"] is None
    assert "encrypted_credentials" not in formatted


def test_format_device_row_reveal_secrets_true_remains_fail_closed(monkeypatch):
    repo = DevicesRepository(db=None)

    def _raise_missing_key(_val):
        raise MissingEncryptionKeyError("DATA_ENCRYPTION_KEY missing")

    monkeypatch.setattr(devices_module, "decrypt_credentials", _raise_missing_key)

    row = {
        "user_id": 1,
        "device_id": "withings",
        "connected": 1,
        "api_key": None,
        "encrypted_credentials": "enc::v1:deadbeef",
    }
    with pytest.raises(MissingEncryptionKeyError):
        repo._format_device_row(row, reveal_secrets=True)


def test_migration_0011_extract_token_from_plaintext_api_key():
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0011_fix_friendships_rls_and_api_key_hash.py"
    spec = importlib.util.spec_from_file_location("mig_0011", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod._extract_token(None, "  raw-api-key-xyz  ") == "raw-api-key-xyz"
    assert mod._extract_token(None, None) is None
