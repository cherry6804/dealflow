"""DFR1-050: every database table has exactly one privacy disposition. Nothing is silently excluded.

These tests read the SQLAlchemy metadata, so a new table fails until someone decides how it is treated.
"""

from __future__ import annotations

from app.db.base import Base
from app.governance.data_classification import CATEGORY_BY_KEY
from app.governance.table_inventory import (
    DISPOSITION_EXPORTED,
    DISPOSITIONS,
    TABLE_INVENTORY,
)


def test_every_table_in_the_database_has_a_disposition() -> None:
    tables = set(Base.metadata.tables)
    missing = sorted(tables - set(TABLE_INVENTORY))
    assert missing == [], f"Tables without a privacy disposition: {missing}"


def test_every_entry_names_a_real_table() -> None:
    stale = sorted(set(TABLE_INVENTORY) - set(Base.metadata.tables))
    assert stale == [], f"Inventory entries for tables that do not exist: {stale}"


def test_every_disposition_is_a_known_value() -> None:
    unknown = sorted(name for name, entry in TABLE_INVENTORY.items() if entry.disposition not in DISPOSITIONS)
    assert unknown == []


def test_exported_tables_name_a_category_that_exists_and_has_a_producer() -> None:
    for name, entry in TABLE_INVENTORY.items():
        if entry.disposition != DISPOSITION_EXPORTED:
            continue
        assert entry.category in CATEGORY_BY_KEY, f"{name} points at an unknown category {entry.category}"
        assert CATEGORY_BY_KEY[entry.category].producer_exists, f"{name} is exported under a category with no producer"


def test_not_covered_tables_always_say_why() -> None:
    for name, entry in TABLE_INVENTORY.items():
        if entry.disposition == "not_covered":
            assert entry.reason, f"{name} is not covered but gives no reason"


def test_provider_secrets_are_never_exported() -> None:
    assert TABLE_INVENTORY["provider_connections"].disposition == "never_exported"
    assert TABLE_INVENTORY["auth_sessions"].disposition == "never_exported"
