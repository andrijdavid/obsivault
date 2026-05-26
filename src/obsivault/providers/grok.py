from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import ijson

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any

_BACKEND_NAME = "prod-grok-backend.json"
_GROK_RENDER = re.compile(r"<grok:render[^>]*>.*?</grok:render>", re.DOTALL)


@register
class GrokProvider:
    name: ClassVar[str] = "grok"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return _find_backend(source) is not None

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        path = _find_backend(source)
        if path is None:
            return
        with path.open("rb") as f:
            for raw in ijson.items(f, "conversations.item"):
                yield _convert(raw, source_path=path, opts=opts)


def _find_backend(source: Path) -> Path | None:
    if source.is_file() and source.name == _BACKEND_NAME:
        return source
    if source.is_dir():
        direct = source / _BACKEND_NAME
        if direct.exists():
            return direct
        for candidate in source.rglob(_BACKEND_NAME):
            return candidate
    return None


def _convert(raw: dict[str, Any], *, source_path: Path, opts: ParseOpts) -> Conversation:
    conv = raw.get("conversation", {})
    responses = raw.get("responses", []) or []
    messages: list[Message] = []
    models: list[str] = []
    for resp_wrapper in responses:
        r = resp_wrapper.get("response", {})
        if not r:
            continue
        text = r.get("message") or ""
        if opts.strip_grok_render:
            text = _GROK_RENDER.sub("", text).strip()
        sender = (r.get("sender") or "").lower()
        role = Role.user if sender == "human" else Role.assistant
        model = r.get("model") or None
        if model:
            models.append(model)
        messages.append(
            Message(
                id=str(r.get("_id")),
                role=role,
                created_at=parse_any(r.get("create_time")),
                model=model,
                blocks=[ContentBlock(kind=BlockKind.text, text=text)],
            )
        )
    conv_model = Counter(models).most_common(1)[0][0] if models else None
    return Conversation(
        id=str(conv.get("id")),
        title=conv.get("title") or None,
        summary=conv.get("summary") or None,
        created_at=parse_any(conv.get("create_time")),
        updated_at=parse_any(conv.get("modify_time")),
        provider="grok",
        model=conv_model,
        source_path=source_path,
        messages=messages,
    )
