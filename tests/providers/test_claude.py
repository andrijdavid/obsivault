from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.provider import ParseOpts
from obsivault.providers.claude import ClaudeProvider


@pytest.fixture(scope="module")
def claude_dir(data_dir: Path) -> Path:
    p = data_dir / "claude"
    if not (p / "conversations.json").exists():
        pytest.skip("Claude sample data not present")
    return p


def test_discover(claude_dir: Path):
    assert ClaudeProvider.discover(claude_dir)
    assert not ClaudeProvider.discover(claude_dir.parent.parent)  # repo root


def test_parses_expected_count(claude_dir: Path):
    convs = list(ClaudeProvider.parse(claude_dir, opts=ParseOpts()))
    chats = [c for c in convs if c.extra.get("kind") != "project_doc"]
    project_docs = [c for c in convs if c.extra.get("kind") == "project_doc"]
    assert len(chats) == 179
    assert len(project_docs) == 2
    first = chats[0]
    assert first.provider == "claude"
    assert first.messages
    assert first.main_path is not None


def test_project_doc_shape(claude_dir: Path):
    docs = [
        c
        for c in ClaudeProvider.parse(claude_dir, opts=ParseOpts())
        if c.extra.get("kind") == "project_doc"
    ]
    assert docs
    d = docs[0]
    assert d.extra.get("project_name")
    assert d.messages and d.messages[0].blocks
    assert d.title and "." in d.title
