from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any
from obsivault.providers._common import (
    clip_title,
    first_user_text,
    iter_files,
    iter_jsonl,
    role_from,
)

_ROLE_EXTRAS = {"developer": Role.system}

_INJECTED_PREFIXES = (
    "<environment_context",
    "<permissions instructions",
    "<user_instructions",
    "<system_instructions",
)


@register
class CodexProvider:
    name: ClassVar[str] = "codex"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return next(_rollouts(source), None) is not None

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        for path in _rollouts(source):
            conv = _convert(path)
            if conv is not None:
                yield conv


def _rollouts(source: Path) -> Iterator[Path]:
    yield from iter_files(source, "rollout-*.jsonl")


def _convert(path: Path) -> Conversation | None:
    meta: dict[str, Any] = {}
    messages: list[Message] = []
    cwd: str | None = None
    model: str | None = None
    idx = 0
    for rec in iter_jsonl(path):
        rec_type = rec.get("type")
        payload = rec.get("payload") or {}
        ts = parse_any(rec.get("timestamp"))
        if rec_type == "session_meta":
            meta = payload
            cwd = payload.get("cwd")
            model = payload.get("model")
        elif rec_type == "turn_context" and not model:
            model = payload.get("model")
        elif rec_type == "response_item":
            msg = _response_item_to_message(payload, ts, idx)
            if msg is not None:
                messages.append(msg)
                idx += 1

    if not messages:
        return None

    session_id = str(meta.get("id") or path.stem)
    title_text = first_user_text(messages)
    started = parse_any(meta.get("timestamp")) or messages[0].created_at
    return Conversation(
        id=f"codex-{session_id}",
        title=clip_title(title_text) if title_text else session_id,
        created_at=started,
        updated_at=messages[-1].created_at if messages else started,
        provider="codex",
        model=model,
        source_path=path,
        messages=messages,
        extra={"cwd": cwd} if cwd else {},
    )


def _response_item_to_message(payload: dict[str, Any], ts: Any, idx: int) -> Message | None:
    item_type = payload.get("type")
    if item_type == "message":
        role = role_from(payload.get("role"), extras=_ROLE_EXTRAS)
        blocks = _content_to_blocks(payload.get("content") or [])
        if role == Role.system or not blocks:
            return None
        if role == Role.user and _is_injected_user_text(blocks):
            return None
        return Message(id=f"msg-{idx}", role=role, created_at=ts, blocks=blocks)
    if item_type == "reasoning":
        text = _flatten_reasoning(payload)
        if not text:
            return None
        return Message(
            id=f"msg-{idx}",
            role=Role.assistant,
            created_at=ts,
            blocks=[ContentBlock(kind=BlockKind.thinking, text=text)],
        )
    if item_type == "function_call":
        return Message(
            id=f"msg-{idx}",
            role=Role.assistant,
            created_at=ts,
            blocks=[
                ContentBlock(
                    kind=BlockKind.tool_use,
                    tool_name=payload.get("name"),
                    tool_input=_maybe_json(payload.get("arguments")),
                )
            ],
        )
    if item_type == "function_call_output":
        return Message(
            id=f"msg-{idx}",
            role=Role.tool,
            created_at=ts,
            blocks=[
                ContentBlock(
                    kind=BlockKind.tool_result,
                    tool_output=_maybe_json(payload.get("output")),
                )
            ],
        )
    return None


def _is_injected_user_text(blocks: list[ContentBlock]) -> bool:
    for b in blocks:
        if b.kind == BlockKind.text and b.text:
            return b.text.lstrip().startswith(_INJECTED_PREFIXES)
    return False


def _content_to_blocks(content: list[Any]) -> list[ContentBlock]:
    blocks: list[ContentBlock] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype in {"input_text", "output_text", "text"}:
            text = part.get("text") or ""
            if text:
                blocks.append(ContentBlock(kind=BlockKind.text, text=text))
        elif ptype == "input_image":
            blocks.append(
                ContentBlock(
                    kind=BlockKind.image,
                    url=part.get("image_url"),
                    raw=part,
                )
            )
    return blocks


def _flatten_reasoning(payload: dict[str, Any]) -> str:
    chunks: list[str] = []
    for s in payload.get("summary") or []:
        if isinstance(s, dict) and s.get("text"):
            chunks.append(str(s["text"]))
    for c in payload.get("content") or []:
        if isinstance(c, dict) and c.get("text"):
            chunks.append(str(c["text"]))
    return "\n\n".join(chunks).strip()


def _maybe_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return value
    return value
