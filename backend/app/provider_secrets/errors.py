"""Errors for provider credential handling. Messages never contain secret or ciphertext values."""


class ProviderSecretsConfigurationError(RuntimeError):
    """Provider credential encryption is not configured for this environment."""


class ProviderSecretsDecryptionError(RuntimeError):
    """A stored provider credential could not be decrypted or authenticated."""
