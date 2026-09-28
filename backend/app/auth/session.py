"""Secure session-token utilities for DealFlow."""

import hashlib
import secrets


SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    """Generate a cryptographically secure opaque session token."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """Return the SHA-256 hash of a session token."""
    if not token:
        raise ValueError("Session token cannot be empty.")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_session_token(token: str, token_hash: str) -> bool:
    """Verify a session token against its stored SHA-256 hash."""
    if not token or not token_hash:
        return False

    return secrets.compare_digest(
        hash_session_token(token),
        token_hash,
    )