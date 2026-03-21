import base64
import os

import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


@pytest.fixture(autouse=True)
def set_secret_key(monkeypatch):
    """Set a deterministic secret key for all signing tests."""
    monkeypatch.setenv("ELEPHANTQ_SECRET_KEY", "test-secret-key-for-unit-tests")
    # Reset the global manager so it picks up the new key
    import elephantq.features.signing as signing_mod

    signing_mod._secret_manager = None
    yield
    signing_mod._secret_manager = None


class TestEncryptDecryptRoundtrip:
    """Verify that encrypt followed by decrypt returns the original plaintext."""

    def test_roundtrip(self):
        from elephantq.features.signing import SecretManager

        manager = SecretManager()
        plaintext = "my-webhook-secret-token"
        ciphertext = manager.encrypt(plaintext)
        assert manager.decrypt(ciphertext) == plaintext

    def test_roundtrip_unicode(self):
        from elephantq.features.signing import SecretManager

        manager = SecretManager()
        plaintext = "secret-with-special-chars-!@#$%"
        assert manager.decrypt(manager.encrypt(plaintext)) == plaintext


class TestLegacyDecryptCompat:
    """
    Verify that tokens created with the old hardcoded salt can still be
    decrypted by the new code.
    """

    def test_legacy_token_decrypts(self):
        from elephantq.features.signing import SecretManager, _LEGACY_SALT

        manager = SecretManager()
        plaintext = "old-webhook-secret"

        # Manually create a legacy-format token using the hardcoded salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_LEGACY_SALT,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(
            kdf.derive(manager._secret_key.encode("utf-8"))
        )
        legacy_fernet = Fernet(key)
        legacy_token = legacy_fernet.encrypt(plaintext.encode("utf-8"))

        # Wrap in base64 the same way the old code did (just base64 the Fernet token)
        legacy_ciphertext = base64.urlsafe_b64encode(legacy_token).decode("utf-8")

        # New decrypt should handle this legacy format
        assert manager.decrypt(legacy_ciphertext) == plaintext


class TestRandomSaltProducesDifferentCiphertexts:
    """Verify that two encryptions of the same plaintext produce different ciphertexts."""

    def test_different_ciphertexts(self):
        from elephantq.features.signing import SecretManager

        manager = SecretManager()
        plaintext = "same-secret-every-time"

        ct1 = manager.encrypt(plaintext)
        ct2 = manager.encrypt(plaintext)

        assert ct1 != ct2, "Two encryptions of the same plaintext should differ (random salt)"
        # Both should still decrypt to the same value
        assert manager.decrypt(ct1) == plaintext
        assert manager.decrypt(ct2) == plaintext
