# ADR-0030: Environment and Configuration Standards

- **Status:** Proposed
- **Date:** 2026-10-30
- **Decision Owners:** DealFlow Engineering (approval pending)
- **Jira:** DFR1-003

## Context

Dealsflo runs in local development, automated test, staging and production environments. Configuration is read from environment variables through `backend/app/config.py`. Secrets must never be committed, and production behaviour must never depend on a development shortcut.

## Decision

1. **Environments.** `APP_ENVIRONMENT` is one of `development`, `test`, `staging` or `production`. Staging is not production, but it must not allow any development-only fallback that affects authorization.
2. **Configuration source.** Settings are read from environment variables and validated by Pydantic. `.env.example` lists variable names and safe defaults only. Real `.env` files are never committed.
3. **Secrets.** Secret values (`SecretStr` fields) come from the environment or a secret manager. They are not printed, logged or returned by the API.
4. **Test isolation.** Tests run only against a database named `dealflow_test` with `APP_ENVIRONMENT=test`. `tests/conftest.py` refuses anything else.
5. **CI secrets.** CI uses a throwaway PostgreSQL service password and a per-run generated encryption key. Neither is a real credential.
6. **Outbox settings.** The `outbox_*` settings are bounded (see `config.py`).
7. **Changes.** A new setting requires a bounded `Field` and an entry in `.env.example`.

The environment and provider matrix is in `docs/product/release-1/E01-environment-and-provider-matrix.md`.

## Alternatives Considered

- **Configuration files per environment in the repository:** rejected for secret values, which would leak. Non-secret defaults stay in code.
- **One shared staging and production environment:** rejected. Staging must be able to diverge safely.

## Consequences

- Operators know what each variable does and whether it is required.
- Misconfigured environments fail at startup where validation can detect it.

## Security Considerations

- No real credentials in CI or the repository.
- Production must reject development-only authorization paths.
- Logs must not contain configuration secrets.

## Operational Considerations

- Staging and production environment owners and the secret manager are not yet provisioned. These are external blockers, recorded in the matrix.

## Compatibility Considerations

Existing variable names are unchanged. The new `outbox_*` variables have defaults.

## Related Decisions

ADR-0027 (staging behaviour), ADR-0026 (outbox settings).
