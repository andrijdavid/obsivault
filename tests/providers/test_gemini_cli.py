from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.models import BlockKind
from obsivault.core.provider import ParseOpts
from obsivault.providers.gemini_cli import GeminiCLIProvider


@pytest.fixture(scope="module")
def gemini_cli_root() -> Path:
    root = Path.home() / ".gemini"
    if not root.is_dir() or not list(root.rglob("session-*.json")):
        pytest.skip("No local gemini-cli sessions present")
    return root


def test_discover(gemini_cli_root: Path):
    assert GeminiCLIProvider.discover(gemini_cli_root)


def test_parses_sessions(gemini_cli_root: Path):
    convs = list(GeminiCLIProvider.parse(gemini_cli_root, opts=ParseOpts()))
    assert convs
    first = convs[0]
    assert first.provider == "gemini-cli"
    assert first.id.startswith("gemini-cli-")
    assert first.messages
    assert first.messages[0].role.value in {"user", "assistant"}


def test_thoughts_become_thinking_blocks(gemini_cli_root: Path):
    convs = list(GeminiCLIProvider.parse(gemini_cli_root, opts=ParseOpts()))
    found = any(b.kind == BlockKind.thinking for c in convs for m in c.messages for b in m.blocks)
    assert found
