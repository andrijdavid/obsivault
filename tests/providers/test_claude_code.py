from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.provider import ParseOpts
from obsivault.providers.claude_code import ClaudeCodeProvider


@pytest.fixture(scope="module")
def claude_code_root() -> Path:
    root = Path.home() / ".claude" / "projects"
    if not root.is_dir() or not any(root.rglob("*.jsonl")):
        pytest.skip("No local Claude Code sessions present")
    return root


def test_discover(claude_code_root: Path):
    assert ClaudeCodeProvider.discover(claude_code_root)
    assert ClaudeCodeProvider.discover(claude_code_root.parent)


def test_parses_sessions(claude_code_root: Path):
    convs = list(ClaudeCodeProvider.parse(claude_code_root, opts=ParseOpts()))
    assert convs
    first = convs[0]
    assert first.provider == "claude-code"
    assert first.messages
    assert first.main_path is not None
    assert first.id.startswith("claude-code-")


def test_session_has_cwd(claude_code_root: Path):
    convs = list(ClaudeCodeProvider.parse(claude_code_root, opts=ParseOpts()))
    with_cwd = [c for c in convs if c.extra.get("cwd")]
    assert with_cwd
