from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth.rate_limit import LOGIN_MAX_ATTEMPTS, consume_login_attempt
from app.db.base import Base
from app.db.models.auth_login_rate_limit import AuthLoginRateLimit


def test_login_limit_is_shared_per_client_and_stores_only_hashed_key(
    monkeypatch,
) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(
        "app.auth.rate_limit.get_settings",
        lambda: SimpleNamespace(
            sso_dealsflo_client_secret=SecretStr("test-only-pepper")
        ),
    )

    with Session(engine) as db:
        for _ in range(LOGIN_MAX_ATTEMPTS):
            assert consume_login_attempt(db, client_key="login:203.0.113.10")[0]

        allowed, retry_after = consume_login_attempt(
            db,
            client_key="login:203.0.113.10",
        )
        assert not allowed
        assert retry_after > 0
        assert consume_login_attempt(db, client_key="login:203.0.113.11")[0]

        stored_key = db.scalar(select(AuthLoginRateLimit.key_hash))
        assert stored_key is not None
        assert stored_key != "login:203.0.113.10"

    Base.metadata.drop_all(engine)
    engine.dispose()
