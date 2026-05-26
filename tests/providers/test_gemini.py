from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.provider import ParseOpts
from obsivault.providers.gemini import GeminiProvider, _parse_myactivity_date


@pytest.fixture(scope="module")
def gemini_dir(data_dir: Path) -> Path:
    p = data_dir / "google"
    if not list(p.rglob("conversation_*.txt")):
        pytest.skip("Gemini sample data not present")
    return p


def test_discover(gemini_dir: Path):
    assert GeminiProvider.discover(gemini_dir)


def test_parses_all_sub_sources(gemini_dir: Path):
    convs = list(GeminiProvider.parse(gemini_dir, opts=ParseOpts()))
    kinds: dict[str, int] = {}
    for c in convs:
        key = c.extra.get("kind") or "workspace"
        kinds[key] = kinds.get(key, 0) + 1
    assert kinds.get("workspace") == 10
    assert kinds.get("myactivity", 0) > 100
    assert kinds.get("notebooklm", 0) > 10


def test_workspace_conversation_shape(gemini_dir: Path):
    workspace = [
        c
        for c in GeminiProvider.parse(gemini_dir, opts=ParseOpts())
        if (c.extra.get("kind") or "workspace") == "workspace"
    ]
    first = workspace[0]
    assert first.title
    assert first.messages
    assert first.messages[0].role.value == "user"


def test_myactivity_date_with_tz():
    dt = _parse_myactivity_date("May 24, 2026, 9:27:13 PM CEST")
    assert dt is not None
    assert dt.hour == 19
    assert dt.tzinfo is not None


def test_myactivity_date_pst():
    dt = _parse_myactivity_date("Dec 31, 2025, 11:30:00 PM PST")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 1 and dt.day == 1
    assert dt.hour == 7
