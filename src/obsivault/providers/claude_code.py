from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from obsivault.core.models import (
    Attachment,
    BlockKind,
    ContentBlock,
    Conversation,
    Message,
    Role,
)
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any
from obsivault.providers._common import (
    build_main_path,
    clip_title,
    first_user_text,
    iter_files,
    iter_jsonl,
)

_DETECT_MARKERS = (b'"sessionId"', b'"parentUuid"')


@register
class ClaudeCodeProvider:
    name: ClassVar[str] = "claude-code"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return next(_session_files(source, peek=True), None) is not None

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        for path in _session_files(source, peek=False):
            conv = _convert(path)
            if conv is not None:
                yield conv


def _session_files(source: Path, *, peek: bool) -> Iterator[Path]:
    for path in iter_files(source, "*.jsonl"):
        if not peek or _looks_like_claude_code(path):
            yield path


def _looks_like_claude_code(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(4096)
    except OSError:
        return False
    return all(marker in head for marker in _DETECT_MARKERS)


@dataclass
class _SessionState:
    session_id: str | None = None
    title: str | None = None
    cwd: str | None = None
    model: str | None = None
    messages: list[Message] = field(default_factory=list)
    by_uuid: dict[str, Message] = field(default_factory=dict)
    pending: list[tuple[str | None, Attachment]] = field(default_factory=list)


def _convert(path: Path) -> Conversation | None:
    state = _SessionState()
    for rec in iter_jsonl(path):
        _dispatch(rec, state)

    if not state.messages:
        return None

    for parent_uuid, att in state.pending:
        target = state.by_uuid.get(parent_uuid) if parent_uuid else None
        if target is None:
            target = state.messages[-1]
        target.attachments.append(att)

    session_id = state.session_id or path.stem
    title = state.title or first_user_text(state.messages) or session_id
    return Conversation(
        id=f"claude-code-{session_id}",
        title=clip_title(title),
        created_at=state.messages[0].created_at,
        updated_at=state.messages[-1].created_at,
        provider="claude-code",
        model=state.model,
        source_path=path,
        messages=state.messages,
        main_path=build_main_path(state.messages),
        extra={"cwd": state.cwd} if state.cwd else {},
    )


def _dispatch(rec: dict[str, Any], state: _SessionState) -> None:
    rtype = rec.get("type")
    if rtype in {"user", "assistant"}:
        if state.session_id is None:
            state.session_id = rec.get("sessionId")
        if state.cwd is None:
            state.cwd = rec.get("cwd")
        if rec.get("isMeta"):
            return
        msg = _envelope_to_message(rec)
        if msg is None:
            return
        if msg.role == Role.assistant and not state.model:
            anth_msg = rec.get("message") or {}
            state.model = anth_msg.get("model")
        state.messages.append(msg)
        state.by_uuid[msg.id] = msg
    elif rtype == "attachment":
        att = _attachment_record(rec)
        if att is not None:
            state.pending.append((rec.get("parentUuid"), att))
    elif rtype == "custom-title":
        state.title = rec.get("customTitle") or state.title
    elif rtype == "last-prompt" and not state.title:
        state.title = rec.get("lastPrompt") or state.title


def _envelope_to_message(rec: dict[str, Any]) -> Message | None:
    rtype = rec.get("type")
    role = Role.user if rtype == "user" else Role.assistant
    payload = rec.get("message") or {}
    blocks = _content_to_blocks(payload.get("content"))
    if not blocks:
        return None
    return Message(
        id=str(rec.get("uuid") or ""),
        parent_id=rec.get("parentUuid") or None,
        role=role,
        created_at=parse_any(rec.get("timestamp")),
        model=payload.get("model"),
        blocks=blocks,
    )


def _content_to_blocks(content: Any) -> list[ContentBlock]:
    if isinstance(content, str):
        return [ContentBlock(kind=BlockKind.text, text=content)] if content.strip() else []
    if not isinstance(content, list):
        return []
    blocks: list[ContentBlock] = []
    for b in content:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            text = b.get("text") or ""
            if text:
                blocks.append(ContentBlock(kind=BlockKind.text, text=text))
        elif bt == "thinking":
            text = b.get("thinking") or b.get("text") or ""
            if text.strip():
                blocks.append(ContentBlock(kind=BlockKind.thinking, text=text))
        elif bt == "tool_use":
            blocks.append(
                ContentBlock(
                    kind=BlockKind.tool_use,
                    tool_name=b.get("name"),
                    tool_input=b.get("input"),
                )
            )
        elif bt == "tool_result":
            blocks.append(
                ContentBlock(
                    kind=BlockKind.tool_result,
                    tool_output=b.get("content"),
                )
            )
    return blocks


def _attachment_record(rec: dict[str, Any]) -> Attachment | None:
    att = rec.get("attachment") or {}
    filename = att.get("filename") or att.get("name")
    if not filename:
        return None
    inline: str | None = None
    content = att.get("content")
    if isinstance(content, dict):
        inline = (content.get("file") or {}).get("content")
    source = Path(filename) if filename.startswith("/") else None
    return Attachment(
        id=str(rec.get("uuid") or filename),
        filename=Path(filename).name,
        mime=att.get("type"),
        source_path=source,
        inline_text=inline if isinstance(inline, str) else None,
    )
