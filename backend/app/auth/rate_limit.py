"""Database-backed authentication request throttling."""

import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models.auth_login_rate_limit import AuthLoginRateLimit

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_RETENTION = timedelta(days=30)
LOGIN_MAX_ATTEMPTS = 20


def consume_login_attempt(db: Session, *, client_key: str) -> tuple[bool, int]:
    """Atomically consume a shared client login budget.

    The key is HMACed before persistence and PostgreSQL/SQLite upserts make the
    counter consistent across application workers.
    """
    settings = get_settings()
    secret = settings.sso_dealsflo_client_secret
    key_material = (
        secret.get_secret_value().encode("utf-8")
        if secret is not None
        else b"dealflow-local-rate-limit-key"
    )
    key_hash = hmac.new(
        key_material,
        client_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    now = datetime.now(UTC)
    cutoff = now - LOGIN_WINDOW
    db.execute(
        delete(AuthLoginRateLimit).where(
            AuthLoginRateLimit.window_started_at < now - LOGIN_RETENTION
        )
    )
    table = AuthLoginRateLimit.__table__
    values = {
        "key_hash": key_hash,
        "window_started_at": now,
        "attempts": 1,
    }
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        statement = pg_insert(table).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(table).values(**values)
    else:
        raise RuntimeError("Login rate limiting requires PostgreSQL or SQLite.")

    expired_window = table.c.window_started_at <= cutoff
    statement = statement.on_conflict_do_update(
        index_elements=[table.c.key_hash],
        set_={
            "window_started_at": case(
                (expired_window, now),
                else_=table.c.window_started_at,
            ),
            "attempts": case(
                (expired_window, 1),
                else_=table.c.attempts + 1,
            ),
        },
    ).returning(table.c.attempts, table.c.window_started_at)

    attempts, window_started_at = db.execute(statement).one()
    db.commit()
    if attempts <= LOGIN_MAX_ATTEMPTS:
        return True, 0
    if window_started_at.tzinfo is None:
        window_started_at = window_started_at.replace(tzinfo=UTC)
    seconds_left = int((window_started_at + LOGIN_WINDOW - now).total_seconds())
    return False, max(1, seconds_left)
