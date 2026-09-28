"""Password hashing and verification utilities for DealFlow."""

from pwdlib import PasswordHash


_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Hash a plaintext password using the recommended password hashing scheme."""
    if not password:
        raise ValueError("Password cannot be empty.")

    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored password hash."""
    if not password or not password_hash:
        return False

    return _password_hash.verify(password, password_hash)