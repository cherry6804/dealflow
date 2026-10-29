"""Store SIBVO's access snapshot on SSO-bound sessions.

SIBVO owns subscription, billing, and entitlement state. Each session
revalidation stores the snapshot SIBVO returns so feature checks never read
Dealsflo's legacy subscription tables for SSO sessions. Existing sessions get
NULL, which forces a revalidation on their next request.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f2d4a7e851"
down_revision: str | Sequence[str] | None = "b8e3a1d6c490"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("auth_sessions", sa.Column("sibvo_access", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("auth_sessions", "sibvo_access")
