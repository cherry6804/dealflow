
"""SMTP delivery for DealFlow authentication and team invitation emails."""

import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlencode

from app.config import get_settings

logger = logging.getLogger(__name__)


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


def build_team_invitation_url(token: str) -> str:
    """Build the frontend team-invitation acceptance URL."""
    settings = get_settings()
    base_url = settings.email_verification_base_url.rstrip("/")

    return f"{base_url}/accept-invitation?{urlencode({'token': token})}"


def _send_email(
    *,
    recipient: str,
    subject: str,
    body: str,
) -> None:
    """Send an email using the configured SMTP settings."""
    settings = get_settings()

    username = (
        settings.email_smtp_username.get_secret_value().strip()
        if settings.email_smtp_username
        else ""
    )
    password = (
        settings.email_smtp_password.get_secret_value()
        if settings.email_smtp_password
        else ""
    )
    host = settings.email_smtp_host.strip()
    sender = settings.email_from_address.strip()
    recipient = recipient.strip()

    if not all((host, username, password, sender, recipient)):
        raise RuntimeError(
            "SMTP email delivery is not fully configured."
        )

    message = EmailMessage()
    message["From"] = sender
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)

    try:
        with smtplib.SMTP(
            host,
            settings.email_smtp_port,
            timeout=settings.email_smtp_timeout_seconds,
        ) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(username, password)
            server.send_message(message)

    except (OSError, smtplib.SMTPException) as exc:
        # Never log credentials, message contents, or SMTP exception details.
        logger.error(
            "Authentication email delivery failed (%s)",
            type(exc).__name__,
        )
        raise RuntimeError(
            "Authentication email could not be sent."
        ) from None


def send_verification_email(
    *,
    recipient: str,
    token: str,
) -> None:
    """Send an email-verification link."""
    _send_email(
        recipient=recipient,
        subject="Verify your DealFlow email address",
        body=(
            "Welcome to DealFlow.\n\n"
            "Verify your email address using this link:\n"
            f"{build_verification_url(token)}\n\n"
            "If you did not create this account, "
            "you can ignore this email."
        ),
    )


def send_password_reset_email(
    *,
    recipient: str,
    token: str,
) -> None:
    """Send a password-reset link."""
    _send_email(
        recipient=recipient,
        subject="Reset your DealFlow password",
        body=(
            "A password reset was requested for your DealFlow account.\n\n"
            "Choose a new password using this link:\n"
            f"{build_password_reset_url(token)}\n\n"
            "If you did not request this reset, "
            "you can ignore this email."
        ),
    )


def send_team_invitation_email(
    *,
    recipient: str,
    token: str,
) -> None:
    """Send a team invitation using the configured SMTP adapter."""
    _send_email(
        recipient=recipient,
        subject="You're invited to join a DealFlow team",
        body=(
            "You have been invited to join a DealFlow organization.\n\n"
            "Sign in using the invited email address and accept the invitation:\n"
            f"{build_team_invitation_url(token)}\n\n"
            "The invitation expires after seven days. "
            "If you were not expecting this invitation, you can ignore it."
        ),
    )
