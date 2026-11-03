"""AES-256-GCM encryption for provider credentials, bound to their owning row.

The associated data binds each ciphertext to its organization, provider, credential identifier
and version. A ciphertext copied to another row, organization or version fails authentication.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.provider_secrets.errors import ProviderSecretsDecryptionError
from app.provider_secrets.key_provider import KeyProvider

ALGORITHM = "aes-256-gcm"
NONCE_BYTES = 12


@dataclass(frozen=True)
class EncryptedSecret:
    """Ciphertext plus the metadata needed to decrypt it later."""

    ciphertext: str
    key_id: str
    algorithm: str


def credential_associated_data(
    *,
    organization_id: UUID,
    provider_key: str,
    credential_id: UUID,
    version: int,
) -> bytes:
    """Return the authenticated associated data for one credential version."""
    return f"provider_credential|{organization_id}|{provider_key}|{credential_id}|{version}".encode("ascii")


def encrypt_secret(plaintext: str, *, associated_data: bytes, keys: KeyProvider) -> EncryptedSecret:
    """Encrypt with the active key. Raises a configuration error if no key is available."""
    key_id = keys.active_key_id()
    nonce = os.urandom(NONCE_BYTES)
    sealed = AESGCM(keys.key_for(key_id)).encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return EncryptedSecret(
        ciphertext=base64.b64encode(nonce + sealed).decode("ascii"),
        key_id=key_id,
        algorithm=ALGORITHM,
    )


def decrypt_secret(
    ciphertext: str,
    *,
    key_id: str,
    algorithm: str,
    associated_data: bytes,
    keys: KeyProvider,
) -> str:
    """Decrypt and authenticate. Any tampering or mismatch raises a generic error."""
    if algorithm != ALGORITHM:
        raise ProviderSecretsDecryptionError("Provider credential uses an unsupported algorithm.")
    try:
        raw = base64.b64decode(ciphertext, validate=True)
    except (binascii.Error, ValueError):
        raise ProviderSecretsDecryptionError("Provider credential could not be decrypted.") from None
    if len(raw) <= NONCE_BYTES:
        raise ProviderSecretsDecryptionError("Provider credential could not be decrypted.")

    aesgcm = AESGCM(keys.key_for(key_id))
    try:
        plaintext = aesgcm.decrypt(raw[:NONCE_BYTES], raw[NONCE_BYTES:], associated_data)
        return plaintext.decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError):
        raise ProviderSecretsDecryptionError("Provider credential could not be decrypted.") from None
