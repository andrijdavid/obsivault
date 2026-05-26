from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

import ijson

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
from obsivault.providers._common import build_main_path


@register
class ClaudeProvider:
    name: ClassVar[str] = "claude"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return (
            _resolve_conversations_json(source) is not None
            or _resolve_projects_dir(source) is not None
        )

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        path = _resolve_conversations_json(source)
        if path is not None:
            with path.open("rb") as f:
                for raw in ijson.items(f, "item"):
                    yield _convert(raw, source_path=path)

        projects = _resolve_projects_dir(source)
        if projects is not None:
            yield from _parse_projects(projects)


def _resolve_conversations_json(source: Path) -> Path | None:
    if source.is_file() and source.name == "conversations.json":
        return source
    if source.is_dir():
        candidate = source / "conversations.json"
        if candidate.exists():
            return candidate
    return None


def _resolve_projects_dir(source: Path) -> Path | None:
    if source.is_dir():
        candidate = source / "projects"
        if candidate.is_dir() and any(candidate.glob("*.json")):
            return candidate
    return None


def _parse_projects(projects_dir: Path) -> Iterator[Conversation]:
    for path in sorted(projects_dir.glob("*.json")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        yield from _project_to_conversations(raw, source_path=path)


def _project_to_conversations(raw: dict[str, Any], *, source_path: Path) -> Iterator[Conversation]:
    project_uuid = str(raw.get("uuid") or source_path.stem)
    project_name = raw.get("name") or "Untitled project"
    project_desc = raw.get("description") or ""
    prompt_template = raw.get("prompt_template") or ""
    docs = raw.get("docs", []) or []
    if not docs:
        return

    for doc in docs:
        doc_uuid = str(doc.get("uuid") or doc.get("filename") or "doc")
        filename = doc.get("filename") or "document.md"
        content = doc.get("content") or ""
        created_at = parse_any(doc.get("created_at")) or parse_any(raw.get("created_at"))
        title = f"{project_name} . {filename}"

        body_parts: list[str] = []
        if project_desc:
            body_parts.append(f"> {project_desc}")
            body_parts.append("")
        if prompt_template:
            body_parts.append("**Project prompt template**")
            body_parts.append("")
            body_parts.append(prompt_template)
            body_parts.append("")
            body_parts.append("---")
            body_parts.append("")
        body_parts.append(content)
        body = "\n".join(body_parts).strip()

        message = Message(
            id=f"doc-{doc_uuid}",
            role=Role.assistant,
            created_at=created_at,
            blocks=[ContentBlock(kind=BlockKind.text, text=body)],
        )
        yield Conversation(
            id=f"project-{project_uuid}-{doc_uuid}",
            title=title,
            summary=project_desc or None,
            created_at=created_at,
            updated_at=parse_any(raw.get("updated_at")),
            provider="claude",
            source_path=source_path,
            messages=[message],
            extra={"kind": "project_doc", "project_name": project_name},
        )


def _convert(raw: dict[str, Any], *, source_path: Path) -> Conversation:
    messages = [_to_message(m) for m in raw.get("chat_messages", [])]
    main_path = build_main_path(messages)
    return Conversation(
        id=raw["uuid"],
        title=raw.get("name") or None,
        summary=raw.get("summary") or None,
        created_at=parse_any(raw.get("created_at")),
        updated_at=parse_any(raw.get("updated_at")),
        provider="claude",
        source_path=source_path,
        messages=messages,
        main_path=main_path,
    )


def _to_message(raw: dict[str, Any]) -> Message:
    sender = raw.get("sender", "")
    role = Role.user if sender == "human" else Role.assistant
    blocks: list[ContentBlock] = []
    for b in raw.get("content", []) or []:
        block = _to_block(b)
        if block is not None:
            blocks.append(block)
    if not blocks and raw.get("text"):
        blocks.append(ContentBlock(kind=BlockKind.text, text=raw["text"]))
    attachments = [_to_attachment(a) for a in raw.get("attachments", []) or []]
    attachments += [_to_file_attachment(a) for a in raw.get("files", []) or []]
    return Message(
        id=raw["uuid"],
        parent_id=raw.get("parent_message_uuid") or None,
        role=role,
        created_at=parse_any(raw.get("created_at")),
        blocks=blocks,
        attachments=[a for a in attachments if a is not None],
    )


def _to_block(raw: dict[str, Any]) -> ContentBlock | None:
    t = raw.get("type")
    match t:
        case "text":
            text = raw.get("text") or ""
            return ContentBlock(kind=BlockKind.text, text=text)
        case "thinking":
            text = raw.get("thinking") or raw.get("text")
            return ContentBlock(kind=BlockKind.thinking, text=text)
        case "tool_use":
            return ContentBlock(
                kind=BlockKind.tool_use,
                tool_name=raw.get("name"),
                tool_input=raw.get("input"),
            )
        case "tool_result":
            return ContentBlock(
                kind=BlockKind.tool_result,
                tool_output=raw.get("content"),
            )
        case "token_budget":
            return None
        case _:
            return ContentBlock(kind=BlockKind.text, text=raw.get("text") or "", raw=raw)


def _to_attachment(raw: dict[str, Any]) -> Attachment | None:
    file_name = raw.get("file_name") or raw.get("name")
    if not file_name:
        return None
    return Attachment(
        id=str(raw.get("id") or raw.get("file_uuid") or file_name),
        filename=str(file_name),
        mime=raw.get("file_type") or raw.get("media_type"),
        size=raw.get("file_size"),
        inline_text=raw.get("extracted_content"),
    )


def _to_file_attachment(raw: dict[str, Any]) -> Attachment | None:
    file_name = raw.get("file_name") or raw.get("name")
    if not file_name:
        return None
    return Attachment(
        id=str(raw.get("file_uuid") or raw.get("id") or file_name),
        filename=str(file_name),
        mime=raw.get("file_kind") or raw.get("media_type"),
    )
