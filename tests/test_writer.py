from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.render import MarkdownRenderer, RenderOpts
from obsivault.core.writer import VaultWriter


def _make_conv() -> Conversation:
    return Conversation(
        id="abc-123",
        title="A nice title",
        provider="test",
        source_path=Path("/dev/null"),
        created_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        messages=[
            Message(
                id="m1",
                role=Role.user,
                blocks=[ContentBlock(kind=BlockKind.text, text="hello")],
            ),
            Message(
                id="m2",
                role=Role.assistant,
                blocks=[ContentBlock(kind=BlockKind.text, text="hi back")],
            ),
        ],
    )


def test_write_creates_file(out_vault: Path):
    conv = _make_conv()
    doc = MarkdownRenderer(conv, RenderOpts()).render()
    writer = VaultWriter(out_vault)
    result = writer.write(conv, doc)
    assert result.written
    assert result.path.exists()
    assert result.path.read_text().startswith("---\n")
    assert "a-nice-title.md" in str(result.path)
    assert "2026-05" in str(result.path)


def test_idempotent_second_write_skips(out_vault: Path):
    conv = _make_conv()
    doc = MarkdownRenderer(conv, RenderOpts()).render()
    writer = VaultWriter(out_vault)
    first = writer.write(conv, doc)
    assert first.written and not first.skipped
    second = writer.write(conv, doc)
    assert second.skipped and not second.written


def test_dry_run_does_not_write(out_vault: Path):
    conv = _make_conv()
    doc = MarkdownRenderer(conv, RenderOpts()).render()
    writer = VaultWriter(out_vault, dry_run=True)
    result = writer.write(conv, doc)
    assert result.written
    assert not result.path.exists()
