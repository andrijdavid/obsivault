from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.models import BlockKind
from obsivault.core.provider import ParseOpts
from obsivault.providers.opencode import OpenCodeProvider


@pytest.fixture(scope="module")
def opencode_db() -> Path:
    candidate = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
    if not candidate.exists():
        pytest.skip("No local opencode.db present")
    return candidate


def test_discover_file(opencode_db: Path):
    assert OpenCodeProvider.discover(opencode_db)
    assert OpenCodeProvider.discover(opencode_db.parent)


def test_parses_sessions(opencode_db: Path):
    convs = list(OpenCodeProvider.parse(opencode_db, opts=ParseOpts()))
    assert convs
    first = convs[0]
    assert first.provider == "opencode"
    assert first.id.startswith("opencode-")
    assert first.messages


def test_tool_parts_split_into_call_and_result(opencode_db: Path):
    convs = list(OpenCodeProvider.parse(opencode_db, opts=ParseOpts()))
    kinds = {b.kind for c in convs for m in c.messages for b in m.blocks}
    assert BlockKind.tool_use in kinds
    assert BlockKind.tool_result in kinds
