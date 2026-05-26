from __future__ import annotations

from pathlib import Path

import pytest

from obsivault.core.provider import ParseOpts
from obsivault.providers.grok import GrokProvider


@pytest.fixture(scope="module")
def grok_dir(data_dir: Path) -> Path:
    p = data_dir / "grok"
    if not p.exists() or not list(p.rglob("prod-grok-backend.json")):
        pytest.skip("Grok sample data not present")
    return p


def test_discover(grok_dir: Path):
    assert GrokProvider.discover(grok_dir)


def test_parses_messages_and_model(grok_dir: Path):
    convs = list(GrokProvider.parse(grok_dir, opts=ParseOpts()))
    assert len(convs) == 174
    first = convs[0]
    assert first.provider == "grok"
    assert first.title
    assert first.messages
    assert any(m.model and m.model.startswith("grok") for m in first.messages)


def test_strip_grok_render(grok_dir: Path):
    convs = list(GrokProvider.parse(grok_dir, opts=ParseOpts(strip_grok_render=True)))
    joined = "\n".join(b.text or "" for c in convs for m in c.messages for b in m.blocks)
    assert "<grok:render" not in joined
