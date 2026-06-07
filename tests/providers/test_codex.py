from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.provider import ParseOpts
from obsivault.providers.codex import CodexProvider


@pytest.fixture(scope="module")
def codex_root() -> Path:
    root = Path.home() / ".codex" / "sessions"
    if not root.is_dir() or not any(root.rglob("rollout-*.jsonl")):
        pytest.skip("No local Codex rollouts present")
    return root


def test_discover(codex_root: Path):
    assert CodexProvider.discover(codex_root)
    assert CodexProvider.discover(codex_root.parent)


def test_parses_rollouts(codex_root: Path):
    convs = list(CodexProvider.parse(codex_root, opts=ParseOpts()))
    assert convs
    first = convs[0]
    assert first.provider == "codex"
    assert first.id.startswith("codex-")
    assert first.messages


def test_drops_injected_user_messages(codex_root: Path):
    convs = list(CodexProvider.parse(codex_root, opts=ParseOpts()))
    for c in convs:
        for m in c.messages:
            for b in m.blocks:
                assert not (b.text or "").lstrip().startswith("<environment_context")
