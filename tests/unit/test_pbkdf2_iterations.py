"""
Tests that PBKDF2 iterations meet NIST 2023 recommendation.

Written to verify MED-07: iterations should be >= 310,000.
"""

import pytest


class TestPBKDF2Iterations:
    def test_iterations_at_least_310k(self):
        from elephantq.features.signing import _PBKDF2_ITERATIONS

        assert _PBKDF2_ITERATIONS >= 310000, (
            f"PBKDF2 iterations ({_PBKDF2_ITERATIONS}) below NIST 2023 recommendation (310,000)"
        )

    def test_legacy_iterations_preserved(self):
        from elephantq.features.signing import _LEGACY_PBKDF2_ITERATIONS

        assert _LEGACY_PBKDF2_ITERATIONS == 100000

    def test_encrypt_decrypt_roundtrip_with_new_iterations(self):
        import os

        os.environ.setdefault("ELEPHANTQ_SECRET_KEY", "test-key-for-310k")

        from elephantq.features.signing import SecretManager

        mgr = SecretManager()
        plaintext = "sensitive-webhook-secret-value"
        encrypted = mgr.encrypt(plaintext)
        decrypted = mgr.decrypt(encrypted)
        assert decrypted == plaintext
