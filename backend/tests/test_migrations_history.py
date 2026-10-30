"""Static checks on the Alembic revision graph.

These checks read the migration files and do not touch a database. They fail
if a change introduces a second head, a missing parent, or a cycle.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]


def _script_directory() -> ScriptDirectory:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    return ScriptDirectory.from_config(config)


def test_alembic_history_has_exactly_one_head() -> None:
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"Expected one Alembic head, found {heads}"


def test_outbox_migration_follows_the_previous_head() -> None:
    script = _script_directory()
    revision = script.get_revision("e5a7c1d9b2f0")
    assert revision is not None
    assert revision.down_revision == "c9f2d4a7e851"


def test_every_down_revision_resolves_to_a_known_revision() -> None:
    script = _script_directory()
    known = {revision.revision for revision in script.walk_revisions()}
    for revision in script.walk_revisions():
        parents = revision.down_revision
        if parents is None:
            continue
        parent_list = [parents] if isinstance(parents, str) else list(parents)
        for parent in parent_list:
            assert parent in known, (
                f"{revision.revision} points at unknown parent {parent}"
            )
