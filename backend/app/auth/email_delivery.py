"""Email delivery boundary for account verification."""

from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

from app.config import get_settings


def build_verification_url(token: str) -> str:
    """Build the frontend URL used to verify an email address."""
    settings = get_settings()
    base_url = settings.email_verification_base_url.rstrip("/")
    query = urlencode({"token": token})
    return f"{base_url}/verify-email?{query}"


def send_verification_email(*, recipient: str, token: str) -> None:
    """Save a verification email to the private development outbox.

    This adapter does not send real email. Production delivery requires
    an explicitly configured email provider.
    """
    settings = get_settings()

    if settings.email_verification_delivery_mode != "development":
        raise RuntimeError(
            "No production email provider is configured."
        )

    outbox: Path = settings.email_verification_outbox_dir
    outbox.mkdir(parents=True, exist_ok=True)

    message = EmailMessage()
    message["Subject"] = "Verify your DealFlow email address"
    message["From"] = "no-reply@dealflow.local"
    message["To"] = recipient
    message.set_content(
        "Welcome to DealFlow.\n\n"
        "Verify your email address using this link:\n"
        f"{build_verification_url(token)}\n\n"
        "This link expires according to the verification policy. "
        "If you did not create this account, you can ignore this email."
    )

    message_path = outbox / f"{uuid4().hex}.eml"
    with message_path.open("xb") as email_file:
        email_file.write(message.as_bytes())
