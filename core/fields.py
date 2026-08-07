"""
core/fields.py — Encrypted Model Fields
Provides transparent Fernet symmetric encryption for sensitive fields stored in
the database (API keys, tokens, credentials).

Usage:
    from core.fields import EncryptedCharField

    class MyModel(models.Model):
        api_key = EncryptedCharField(max_length=500, blank=True, default="")

The plaintext value is encrypted before saving and decrypted after loading.
Stored ciphertext is always a ``gAA…`` base64 string; an empty string stays
empty (no-op) so blank/default semantics are preserved.
"""

import base64
import hashlib
import logging

from django.conf import settings
from django.db import models

logger = logging.getLogger(__name__)


def _get_fernet():
    """
    Derive a 32-byte Fernet key from Django's SECRET_KEY and return a Fernet
    instance.  Importing cryptography is deferred so the module doesn't crash
    if the package is absent.
    """
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise ImportError(
            "The 'cryptography' package is required for EncryptedCharField. "
            "Run: pip install cryptography"
        ) from exc

    raw_key = settings.SECRET_KEY.encode("utf-8")
    # SHA-256 gives us exactly 32 bytes; Fernet needs URL-safe base64 of 32 bytes.
    digest = hashlib.sha256(raw_key).digest()
    fernet_key = base64.urlsafe_b64encode(digest)
    return Fernet(fernet_key)


def encrypt_value(plaintext: str) -> str:
    """Encrypt *plaintext* and return the ciphertext as a UTF-8 string."""
    if not plaintext:
        return plaintext
    fernet = _get_fernet()
    return fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_value(ciphertext: str) -> str:
    """Decrypt *ciphertext* and return the plaintext as a UTF-8 string.

    Returns the ciphertext unchanged if it does not look like a Fernet token
    (e.g. plain-text values that were stored before encryption was enabled).
    """
    if not ciphertext:
        return ciphertext
    # Fernet tokens always start with 'gAA'
    if not ciphertext.startswith("gAA"):
        return ciphertext
    try:
        fernet = _get_fernet()
        return fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception:
        logger.warning("EncryptedCharField: failed to decrypt value — returning as-is.")
        return ciphertext


class EncryptedCharField(models.CharField):
    """
    A CharField that encrypts values at rest using Fernet symmetric encryption.

    * ``max_length`` should be large enough to hold the *ciphertext* (which is
      roughly ``len(plaintext) * 1.5 + 100`` bytes).  A safe default is 500.
    * Blank values (empty string) are stored as-is without encryption.
    * Existing plain-text values in the database are returned as-is (graceful
      migration path — just re-save to encrypt them).
    """

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value) if value else value

    def to_python(self, value):
        value = super().to_python(value)
        return decrypt_value(value) if value else value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value) if value else value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Return the base CharField path so migrations don't depend on
        # core.fields being importable in a future project.
        path = "django.db.models.CharField"
        return name, path, args, kwargs
