"""Key sources for provider credential encryption.

Local and test environments read a keyring from settings. Production must use a managed key
provider. The managed adapter below is a boundary only and is not implemented, so every
credential operation that needs a key fails closed when it is selected.
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Protocol

from app.config import get_settings
from app.provider_secrets.errors import ProviderSecretsConfigurationError

KEY_BYTES = 32


class KeyProvider(Protocol):
    """Supplies the active encryption key and any key needed to decrypt stored data."""

    def active_key_id(self) -> str: ...

    def key_for(self, key_id: str) -> bytes: ...


class LocalKeyring:
    """Keys held in settings for local development and tests. Never used in production."""

    def __init__(self, *, active_key_id: str, keys: dict[str, bytes]) -> None:
        self._active_key_id = active_key_id
        self._keys = keys

    def active_key_id(self) -> str:
        return self._active_key_id

    def key_for(self, key_id: str) -> bytes:
        key = self._keys.get(key_id)
        if key is None:
            raise ProviderSecretsConfigurationError("Provider secret key is unavailable.")
        return key


class ManagedKmsKeyProvider:
    """Boundary for a managed KMS or secrets-provider adapter. Not implemented yet.

    Selecting this provider makes provider credential operations fail closed. It must not be
    described as production-ready until a real adapter is implemented and tested.
    """

    _MESSAGE = "Managed key provider is not implemented; provider credentials are unavailable."

    def active_key_id(self) -> str:
        raise ProviderSecretsConfigurationError(self._MESSAGE)

    def key_for(self, key_id: str) -> bytes:
        raise ProviderSecretsConfigurationError(self._MESSAGE)


def _decode_key(encoded: str) -> bytes:
    try:
        padded = encoded.encode("ascii") + b"=" * (-len(encoded) % 4)
        key = base64.urlsafe_b64decode(padded)
    except (UnicodeEncodeError, binascii.Error, ValueError):
        raise ProviderSecretsConfigurationError("Provider secrets keyring entry is malformed.") from None
    if len(key) != KEY_BYTES:
        raise ProviderSecretsConfigurationError("Provider secrets keyring entry has the wrong length.")
    return key


def build_key_provider() -> KeyProvider:
    """Return the key source for the current environment, or fail closed."""
    settings = get_settings()

    if settings.provider_secrets_key_provider == "managed_kms":
        return ManagedKmsKeyProvider()

    if settings.app_environment == "production":
        raise ProviderSecretsConfigurationError(
            "Production requires a managed key provider for provider secrets."
        )

    raw_keyring = settings.provider_secrets_keyring
    active_key_id = settings.provider_secrets_active_key_id
    if raw_keyring is None or not raw_keyring.get_secret_value().strip() or not active_key_id:
        raise ProviderSecretsConfigurationError("Provider secrets keyring is not configured.")

    try:
        entries = json.loads(raw_keyring.get_secret_value())
    except ValueError:
        raise ProviderSecretsConfigurationError("Provider secrets keyring is malformed.") from None
    if not isinstance(entries, dict) or not entries:
        raise ProviderSecretsConfigurationError("Provider secrets keyring is malformed.")
    if not all(isinstance(value, str) for value in entries.values()):
        raise ProviderSecretsConfigurationError("Provider secrets keyring is malformed.")

    keys = {str(key_id): _decode_key(value) for key_id, value in entries.items()}
    if active_key_id not in keys:
        raise ProviderSecretsConfigurationError("Active provider secret key is not in the keyring.")

    return LocalKeyring(active_key_id=active_key_id, keys=keys)
