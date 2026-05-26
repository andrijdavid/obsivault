from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.render import MarkdownRenderer, RenderOpts


def _conv_with_tool() -> Conversation:
    return Conversation(
        id="x",
        title="t",
        provider="claude",
        source_path=Path("/dev/null"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        messages=[
            Message(
                id="m1",
                role=Role.assistant,
                blocks=[
                    ContentBlock(kind=BlockKind.thinking, text="quietly thinking"),
                    ContentBlock(
                        kind=BlockKind.tool_use,
                        tool_name="search",
                        tool_input={"q": "foo"},
                    ),
                    ContentBlock(kind=BlockKind.text, text="here is the answer"),
                ],
            )
        ],
    )


def test_thinking_hidden_by_default():
    out = MarkdownRenderer(_conv_with_tool(), RenderOpts()).render()
    assert "quietly thinking" not in out.text
    assert "Tool: search" not in out.text
    assert "here is the answer" in out.text


def test_thinking_callout_when_enabled():
    out = MarkdownRenderer(
        _conv_with_tool(),
        RenderOpts(include_thinking=True, include_tools=True),
    ).render()
    assert "> [!tip]+ Thinking" in out.text
    assert "> [!note]+ Tool: search" in out.text
    assert '"q": "foo"' in out.text


def test_frontmatter_contains_required_keys():
    out = MarkdownRenderer(_conv_with_tool(), RenderOpts()).render()
    assert out.text.startswith("---\n")
    for key in ("source:", "conversation_id:", "title:", "message_count:", "tags:"):
        assert key in out.text
