
"""Development email delivery boundary for authentication messages."""

from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.config import get_settings


def build_verification_url(token: str) -> str:
    """Build the frontend email-verification URL."""
    settings = get_settings()
    base_url = settings.email_verification_base_url.rstrip("/")
    return f"{base_url}/verify-email?{urlencode({'token': token})}"


def build_password_reset_url(token: str) -> str:
    """Build the frontend password-reset URL."""
    settings = get_settings()
    base_url = settings.email_verification_base_url.rstrip("/")
    return f"{base_url}/reset-password?{urlencode({'token': token})}"


def _save_development_email(
    *,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """Write an email to the private development outbox."""
    settings = get_settings()

    if settings.email_verification_delivery_mode != "development":
        raise RuntimeError("No production email provider is configured.")

    outbox: Path = settings.email_verification_outbox_dir
    outbox.mkdir(parents=True, exist_ok=True)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "no-reply@dealflow.local"
    message["To"] = recipient
    message.set_content(body)

    message_path = outbox / f"{uuid4().hex}.eml"
    with message_path.open("xb") as email_file:
        email_file.write(message.as_bytes())


def send_verification_email(*, recipient: str, token: str) -> None:
    """Save a verification email to the private development outbox."""
    _save_development_email(
        recipient=recipient,
        subject="Verify your DealFlow email address",
        body=(
            "Welcome to DealFlow.\n\n"
            "Verify your email address using this link:\n"
            f"{build_verification_url(token)}\n\n"
            "This link expires according to the verification policy. "
            "If you did not create this account, you can ignore this email."
        ),
    )


def send_password_reset_email(*, recipient: str, token: str) -> None:
    """Save a password-reset email to the private development outbox."""
    _save_development_email(
        recipient=recipient,
        subject="Reset your DealFlow password",
        body=(
            "A password reset was requested for your DealFlow account.\n\n"
            "Choose a new password using this link:\n"
            f"{build_password_reset_url(token)}\n\n"
            "If you did not request this reset, you can ignore this email. "
            "The link expires according to the password-reset policy."
        ),
    )
