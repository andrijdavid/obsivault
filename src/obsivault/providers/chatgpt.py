from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import ijson

from obsivault.core.models import Attachment, BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any

_ROLE_MAP = {
    "user": Role.user,
    "assistant": Role.assistant,
    "system": Role.system,
    "tool": Role.tool,
}


@register
class ChatGPTProvider:
    name: ClassVar[str] = "chatgpt"

    @classmethod
    def discover(cls, source: Path) -> bool:
        path = _resolve(source)
        if path is None:
            return False
        try:
            with path.open("rb") as f:
                for raw in ijson.items(f, "item"):
                    return isinstance(raw, dict) and "mapping" in raw and "current_node" in raw
        except (OSError, ijson.JSONError):
            return False
        return False

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        path = _resolve(source)
        if path is None:
            return
        with path.open("rb") as f:
            for raw in ijson.items(f, "item"):
                yield _convert(raw, source_path=path)


def _resolve(source: Path) -> Path | None:
    if source.is_file() and source.name == "conversations.json":
        return source
    if source.is_dir():
        candidate = source / "conversations.json"
        if candidate.exists():
            return candidate
    return None


def _convert(raw: dict[str, Any], *, source_path: Path) -> Conversation:
    mapping = raw.get("mapping", {}) or {}
    messages: list[Message] = []
    for node_id, node in mapping.items():
        msg = _node_to_message(node_id, node)
        if msg is not None:
            messages.append(msg)
    main_path = _walk_main(mapping, raw.get("current_node"))
    title = raw.get("title") or None
    model = _dominant_model(messages)
    return Conversation(
        id=str(raw.get("conversation_id") or raw.get("id") or _slug_fallback(title)),
        title=title,
        created_at=parse_any(raw.get("create_time")),
        updated_at=parse_any(raw.get("update_time")),
        provider="chatgpt",
        model=model,
        source_path=source_path,
        messages=messages,
        main_path=main_path,
    )


def _node_to_message(node_id: str, node: dict[str, Any]) -> Message | None:
    message = node.get("message")
    if not message:
        return None
    author = (message.get("author") or {}).get("role", "user")
    role = _ROLE_MAP.get(author, Role.user)
    content = message.get("content") or {}
    blocks = _content_to_blocks(content)
    metadata = message.get("metadata") or {}
    attachments = [
        Attachment(
            id=str(a.get("id") or a.get("name")),
            filename=str(a.get("name") or a.get("id")),
            mime=a.get("mime_type") or a.get("mimeType"),
            size=a.get("size"),
        )
        for a in metadata.get("attachments", []) or []
        if a.get("name") or a.get("id")
    ]
    return Message(
        id=node_id,
        parent_id=node.get("parent"),
        role=role,
        created_at=parse_any(message.get("create_time")),
        model=metadata.get("model_slug"),
        blocks=blocks,
        attachments=attachments,
    )


def _content_to_blocks(content: dict[str, Any]) -> list[ContentBlock]:
    ctype = content.get("content_type", "text")
    if ctype == "text":
        parts = content.get("parts") or []
        text = "\n\n".join(str(p) for p in parts if p)
        return [ContentBlock(kind=BlockKind.text, text=text)] if text else []
    if ctype == "code":
        text = content.get("text") or ""
        lang = content.get("language") or ""
        return [ContentBlock(kind=BlockKind.text, text=f"```{lang}\n{text}\n```")]
    if ctype == "multimodal_text":
        blocks: list[ContentBlock] = []
        for part in content.get("parts") or []:
            if isinstance(part, str):
                if part:
                    blocks.append(ContentBlock(kind=BlockKind.text, text=part))
            elif isinstance(part, dict):
                if part.get("content_type") in {"image_asset_pointer", "audio_asset_pointer"}:
                    asset = part.get("asset_pointer") or ""
                    blocks.append(
                        ContentBlock(
                            kind=BlockKind.image,
                            attachment_id=asset,
                            raw=part,
                        )
                    )
                else:
                    blocks.append(ContentBlock(kind=BlockKind.text, text=str(part)))
        return blocks
    return [ContentBlock(kind=BlockKind.text, text=str(content))]


def _walk_main(mapping: dict[str, Any], current: str | None) -> list[str] | None:
    if not current or current not in mapping:
        return None
    chain: list[str] = []
    seen: set[str] = set()
    node_id: str | None = current
    while node_id and node_id in mapping and node_id not in seen:
        node = mapping[node_id]
        if node.get("message"):
            chain.append(node_id)
        seen.add(node_id)
        node_id = node.get("parent")
    chain.reverse()
    return chain or None


def _dominant_model(messages: list[Message]) -> str | None:
    for m in messages:
        if m.model:
            return m.model
    return None


def _slug_fallback(title: str | None) -> str:
    return title or "chatgpt-conversation"
