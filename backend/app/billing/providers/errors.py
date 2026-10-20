
"""Normalized errors raised by billing provider adapters."""


class BillingProviderError(Exception):
    """Base class for safe, provider-independent billing errors."""

    code = "BILLING_PROVIDER_ERROR"
    retryable = False

    def __init__(self, message: str = "The billing provider operation failed."):
        super().__init__(message)


class ProviderConfigurationError(BillingProviderError):
    code = "BILLING_PROVIDER_CONFIGURATION_ERROR"


class ProviderValidationError(BillingProviderError):
    code = "BILLING_PROVIDER_VALIDATION_ERROR"


class ProviderAuthenticationError(BillingProviderError):
    code = "BILLING_PROVIDER_AUTHENTICATION_ERROR"


class ProviderUnavailableError(BillingProviderError):
    code = "BILLING_PROVIDER_UNAVAILABLE"
    retryable = True


class ProviderOperationUnsupportedError(BillingProviderError):
    code = "BILLING_PROVIDER_OPERATION_UNSUPPORTED"


class ProviderConflictError(BillingProviderError):
    """An idempotency key or provider resource conflicts with an earlier request."""

    code = "BILLING_PROVIDER_CONFLICT"
