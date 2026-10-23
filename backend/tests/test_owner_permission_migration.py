
"""Tests for the owner permission catalog migration."""

import importlib.util
from pathlib import Path
import uuid

import sqlalchemy as sa


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "a6c1e9d42b70_bootstrap_owner_permission_catalog.py"
)

SPEC = importlib.util.spec_from_file_location(
    "owner_permission_catalog_migration",
    MIGRATION_PATH,
)
assert SPEC is not None and SPEC.loader is not None
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


def create_schema():
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()

    roles = sa.Table(
        "roles",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    permissions = sa.Table(
        "permissions",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(150), nullable=False, unique=True),
        sa.Column("description", sa.Text()),
        sa.Column("is_active", sa.Boolean(), nullable=False),
    )
    role_permissions = sa.Table(
        "role_permissions",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.UniqueConstraint("role_id", "permission_id"),
    )
    metadata.create_all(engine)

    return engine, roles, permissions, role_permissions


def run_migration(monkeypatch, connection):
    monkeypatch.setattr(
        MIGRATION.op,
        "get_bind",
        lambda: connection,
    )
    MIGRATION.upgrade()


def test_migration_bootstraps_owner_and_catalog(monkeypatch):
    engine, roles, permissions, assignments = create_schema()

    with engine.begin() as connection:
        run_migration(monkeypatch, connection)

        owner = connection.execute(
            sa.select(roles).where(roles.c.name == "DealFlow Owner")
        ).one()

        permission_rows = connection.execute(
            sa.select(permissions)
        ).all()

        assignment_rows = connection.execute(
            sa.select(assignments)
        ).all()

        assert owner.is_active is True
        assert len(permission_rows) == len(MIGRATION.PERMISSIONS)
        assert len(assignment_rows) == len(MIGRATION.PERMISSIONS)

    engine.dispose()


def test_migration_preserves_existing_permission_and_assignment(
    monkeypatch,
):
    engine, roles, permissions, assignments = create_schema()

    owner_id = uuid.uuid4()
    existing_permission_id = uuid.uuid4()
    existing_assignment_id = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(
            roles.insert().values(
                id=owner_id,
                name="DealFlow Owner",
                description="Existing description",
                is_active=True,
            )
        )

        connection.execute(
            permissions.insert().values(
                id=existing_permission_id,
                key="contacts.read",
                description="Keep this description",
                is_active=True,
            )
        )

        connection.execute(
            assignments.insert().values(
                id=existing_assignment_id,
                role_id=owner_id,
                permission_id=existing_permission_id,
            )
        )

        run_migration(monkeypatch, connection)

        permission = connection.execute(
            sa.select(permissions).where(
                permissions.c.key == "contacts.read"
            )
        ).one()

        existing_assignment_count = connection.execute(
            sa.select(sa.func.count())
            .select_from(assignments)
            .where(
                assignments.c.role_id == owner_id,
                assignments.c.permission_id == existing_permission_id,
            )
        ).scalar_one()

        assert permission.id == existing_permission_id
        assert permission.description == "Keep this description"
        assert existing_assignment_count == 1

        assert connection.execute(
            sa.select(roles.c.description).where(roles.c.id == owner_id)
        ).scalar_one() == "Existing description"

    engine.dispose()


def test_migration_does_not_grant_disabled_permissions(monkeypatch):
    engine, roles, permissions, assignments = create_schema()

    owner_id = uuid.uuid4()
    disabled_permission_id = uuid.uuid4()

    with engine.begin() as connection:
        connection.execute(
            roles.insert().values(
                id=owner_id,
                name="DealFlow Owner",
                description="Existing owner",
                is_active=True,
            )
        )

        connection.execute(
            permissions.insert().values(
                id=disabled_permission_id,
                key="contacts.read",
                description="Disabled permission",
                is_active=False,
            )
        )

        run_migration(monkeypatch, connection)

        disabled_assignment = connection.execute(
            sa.select(assignments.c.id).where(
                assignments.c.role_id == owner_id,
                assignments.c.permission_id == disabled_permission_id,
            )
        ).first()

        assert disabled_assignment is None

    engine.dispose()


def test_migration_is_repeat_safe(monkeypatch):
    engine, roles, permissions, assignments = create_schema()

    with engine.begin() as connection:
        run_migration(monkeypatch, connection)

        permission_count_before = connection.execute(
            sa.select(sa.func.count()).select_from(permissions)
        ).scalar_one()

        assignment_count_before = connection.execute(
            sa.select(sa.func.count()).select_from(assignments)
        ).scalar_one()

        run_migration(monkeypatch, connection)

        permission_count_after = connection.execute(
            sa.select(sa.func.count()).select_from(permissions)
        ).scalar_one()

        assignment_count_after = connection.execute(
            sa.select(sa.func.count()).select_from(assignments)
        ).scalar_one()

        assert permission_count_after == permission_count_before
        assert assignment_count_after == assignment_count_before

    engine.dispose()
