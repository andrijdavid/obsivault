from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any
from obsivault.providers._common import clip_title, first_user_text, iter_files


@register
class GeminiCLIProvider:
    name: ClassVar[str] = "gemini-cli"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return next(_session_files(source), None) is not None

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        for path in _session_files(source):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            conv = _convert(raw, source_path=path)
            if conv is not None:
                yield conv


def _session_files(source: Path) -> Iterator[Path]:
    yield from iter_files(source, "session-*.json")


def _convert(raw: dict[str, Any], *, source_path: Path) -> Conversation | None:
    messages_raw = raw.get("messages") or []
    if not messages_raw:
        return None
    messages: list[Message] = []
    dominant_model: str | None = None
    for entry in messages_raw:
        msg = _to_message(entry)
        if msg is None:
            continue
        if dominant_model is None and msg.model:
            dominant_model = msg.model
        messages.append(msg)
    if not messages:
        return None
    session_id = str(raw.get("sessionId") or source_path.stem)
    title_text = first_user_text(messages)
    return Conversation(
        id=f"gemini-cli-{session_id}",
        title=clip_title(title_text) if title_text else session_id,
        created_at=parse_any(raw.get("startTime")),
        updated_at=parse_any(raw.get("lastUpdated")),
        provider="gemini-cli",
        model=dominant_model,
        source_path=source_path,
        messages=messages,
        extra={"project_hash": raw.get("projectHash")} if raw.get("projectHash") else {},
    )


def _to_message(raw: dict[str, Any]) -> Message | None:
    mtype = raw.get("type")
    if mtype not in {"user", "gemini"}:
        return None
    role = Role.user if mtype == "user" else Role.assistant
    blocks: list[ContentBlock] = []
    if mtype == "gemini":
        for thought in raw.get("thoughts") or []:
            text = _thought_text(thought)
            if text:
                blocks.append(ContentBlock(kind=BlockKind.thinking, text=text))
    content = raw.get("content")
    if isinstance(content, str) and content.strip():
        blocks.append(ContentBlock(kind=BlockKind.text, text=content))
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, str) and part.strip():
                blocks.append(ContentBlock(kind=BlockKind.text, text=part))
            elif isinstance(part, dict) and part.get("text"):
                blocks.append(ContentBlock(kind=BlockKind.text, text=str(part["text"])))
    if not blocks:
        return None
    return Message(
        id=str(raw.get("id") or ""),
        role=role,
        created_at=parse_any(raw.get("timestamp")),
        model=raw.get("model"),
        blocks=blocks,
    )


def _thought_text(thought: Any) -> str | None:
    if isinstance(thought, str):
        return thought.strip() or None
    if isinstance(thought, dict):
        subject = thought.get("subject") or ""
        description = thought.get("description") or thought.get("text") or ""
        if subject and description:
            return f"**{subject}**\n\n{description}"
        return (subject or description) or None
    return None
