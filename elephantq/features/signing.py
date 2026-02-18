"""
ElephantQ Security Module.
Provides encryption utilities for sensitive data like webhook secrets.
"""

import base64
import os
import secrets
from typing import Optional, Union

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class SecretManager:
    """
    Manages encryption and decryption of sensitive data like webhook secrets.

    Uses Fernet (symmetric encryption) with a key derived from ELEPHANTQ_SECRET_KEY
    environment variable or auto-generated key.
    """

    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._initialize_encryption()

    def _initialize_encryption(self):
        """Initialize Fernet encryption with environment key or generated key"""
        secret_key = os.environ.get("ELEPHANTQ_SECRET_KEY")

        if not secret_key:
            # Generate a random key and warn user
            secret_key = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(
                "utf-8"
            )
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                "No ELEPHANTQ_SECRET_KEY environment variable found. "
                "Using auto-generated key. For production, set ELEPHANTQ_SECRET_KEY. "
                f"Generated key: {secret_key}"
            )

        # Derive encryption key from secret
        key = self._derive_key(secret_key)
        self._fernet = Fernet(key)

    def _derive_key(self, password: str) -> bytes:
        """Derive encryption key from password using PBKDF2"""
        # Use a fixed salt for deterministic key derivation
        # In production, consider storing salt separately
        salt = b"elephantq_security_salt_v1"

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
        return key

    def encrypt(self, plaintext: str) -> str:
        """
        Encrypt a plaintext string and return base64-encoded ciphertext.

        Args:
            plaintext: The string to encrypt

        Returns:
            Base64-encoded encrypted string
        """
        if not plaintext:
            return plaintext

        encrypted_bytes = self._fernet.encrypt(plaintext.encode("utf-8"))
        return base64.urlsafe_b64encode(encrypted_bytes).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt a base64-encoded ciphertext string.

        Args:
            ciphertext: Base64-encoded encrypted string

        Returns:
            Decrypted plaintext string

        Raises:
            ValueError: If decryption fails (invalid ciphertext or wrong key)
        """
        if not ciphertext:
            return ciphertext

        try:
            encrypted_bytes = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
            decrypted_bytes = self._fernet.decrypt(encrypted_bytes)
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            raise ValueError(f"Failed to decrypt secret: {e}")

    def is_encrypted(self, value: str) -> bool:
        """
        Check if a string appears to be encrypted (basic heuristic).

        This is not foolproof but helps with migration from plaintext.
        """
        if not value:
            return False

        # Encrypted values should be base64 and much longer than typical secrets
        try:
            decoded = base64.urlsafe_b64decode(value.encode("utf-8"))
            # Fernet tokens have specific length requirements
            return len(decoded) >= 73  # Minimum Fernet token length
        except Exception:
            return False


# Global secret manager instance
_secret_manager: Optional[SecretManager] = None


def get_secret_manager() -> SecretManager:
    """Get or create the global secret manager instance"""
    global _secret_manager
    if _secret_manager is None:
        _secret_manager = SecretManager()
    return _secret_manager


def encrypt_secret(plaintext: str) -> str:
    """Convenience function to encrypt a secret"""
    return get_secret_manager().encrypt(plaintext)


def decrypt_secret(ciphertext: str) -> str:
    """Convenience function to decrypt a secret"""
    return get_secret_manager().decrypt(ciphertext)


def is_secret_encrypted(value: str) -> bool:
    """Convenience function to check if a value is encrypted"""
    return get_secret_manager().is_encrypted(value)


class SecureWebhookSecret:
    """
    Secure wrapper for webhook secrets that automatically handles encryption/decryption.
    """

    def __init__(self, secret: Union[str, None]):
        self._encrypted_secret: Optional[str] = None
        self._plaintext_secret: Optional[str] = None

        if secret:
            if is_secret_encrypted(secret):
                # Already encrypted
                self._encrypted_secret = secret
            else:
                # Plaintext - encrypt it
                self._plaintext_secret = secret
                self._encrypted_secret = encrypt_secret(secret)

    @property
    def encrypted(self) -> Optional[str]:
        """Get the encrypted version (safe to store in database)"""
        return self._encrypted_secret

    @property
    def plaintext(self) -> Optional[str]:
        """Get the plaintext version (use for signing/verification)"""
        if self._plaintext_secret is None and self._encrypted_secret:
            self._plaintext_secret = decrypt_secret(self._encrypted_secret)
        return self._plaintext_secret

    def __str__(self) -> str:
        """String representation (encrypted for safety)"""
        return self._encrypted_secret or ""

    def __bool__(self) -> bool:
        """Boolean check"""
        return bool(self._encrypted_secret)
