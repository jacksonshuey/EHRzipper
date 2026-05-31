"""
Shared pytest fixtures.

Provides:
    db_storage  — SQLiteStorage backed by an in-memory SQLite database, schema
                  pre-applied (all 5 tables + seed data).
    fake_router — HaikuRouter backed by a fake Anthropic client. The fake
                  client accepts a HaikuRoutingVerdict and returns it verbatim
                  as a tool_use block — zero real network calls, no API key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ehrzipper.haiku_router import HaikuRouter
from ehrzipper.storage_sqlite import SQLiteStorage
from ehrzipper.types import HaikuRoutingVerdict

# Path to the SQLite migration SQL
_MIGRATION_SQL = (
    Path(__file__).parent.parent
    / "ehrzipper"
    / "migrations"
    / "001_zippering_tables.sql"
)


# ---------------------------------------------------------------------------
# SQLiteStorage fixture (in-memory)
# ---------------------------------------------------------------------------


@pytest.fixture
def db_storage() -> SQLiteStorage:
    """Fresh in-memory SQLite database with the full Zippering schema applied."""
    storage = SQLiteStorage(":memory:")
    storage.apply_migration(_MIGRATION_SQL.read_text())
    return storage


# ---------------------------------------------------------------------------
# Fake Anthropic client helpers
# ---------------------------------------------------------------------------


def make_fake_anthropic_client(verdict: HaikuRoutingVerdict) -> Any:
    """
    Build a minimal fake Anthropic client that returns a hard-coded tool_use
    block containing ``verdict`` whenever messages.create is called.

    Mirrors the TS helper makeFakeClient() in zippering-haiku.test.ts.
    Only messages.create is stubbed — all other SDK surfaces are unused.
    """
    fake_block = MagicMock()
    fake_block.type = "tool_use"
    fake_block.name = "zippering_routing_verdict"
    fake_block.input = verdict.model_dump()

    fake_message = MagicMock()
    fake_message.content = [fake_block]

    client = MagicMock()
    client.messages = MagicMock()
    client.messages.create = AsyncMock(return_value=fake_message)
    return client


def make_fake_router(verdict: HaikuRoutingVerdict) -> HaikuRouter:
    """Return a HaikuRouter whose underlying client always returns ``verdict``."""
    return HaikuRouter(client=make_fake_anthropic_client(verdict))
