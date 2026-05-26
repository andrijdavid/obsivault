from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

import yaml

from obsivault.core.models import Attachment, BlockKind, ContentBlock, Conversation, Message


@dataclass(frozen=True)
class RenderOpts:
    include_tools: bool = False
    include_thinking: bool = False
    branches: bool = False
    strip_grok_render: bool = False


@dataclass
class RenderedDoc:
    text: str
    attachments: list[Attachment] = field(default_factory=list)


class MarkdownRenderer:
    def __init__(self, conv: Conversation, opts: RenderOpts) -> None:
        self.conv = conv
        self.opts = opts
        self._footnotes: list[str] = []
        self._attachments: list[Attachment] = []
        self._att_seen: set[str] = set()

    def render(self) -> RenderedDoc:
        parts: list[str] = []
        parts.append(self._frontmatter())
        parts.append("")
        title = self.conv.title or self.conv.id
        parts.append(f"# {title}")
        if self.conv.summary:
            parts.append("")
            parts.append("> " + self.conv.summary.replace("\n", "\n> "))
        parts.append("")

        for msg in self.conv.iter_main():
            parts.append(self._render_message(msg))

        if self.opts.branches:
            main_ids = set(self.conv.main_path or [m.id for m in self.conv.messages])
            for msg in self.conv.messages:
                if msg.id in main_ids:
                    continue
                parts.append(self._render_alternate(msg))

        if self._footnotes:
            parts.append("")
            parts.append("---")
            parts.extend(self._footnotes)

        text = "\n".join(parts).rstrip() + "\n"
        return RenderedDoc(text=text, attachments=self._attachments)

    def _frontmatter(self) -> str:
        data: dict[str, object] = {
            "source": self.conv.provider,
            "conversation_id": self.conv.id,
            "title": self.conv.title or "",
            "message_count": len(self.conv.messages),
        }
        if self.conv.model:
            data["model"] = self.conv.model
        if self.conv.created_at:
            data["created_at"] = _iso(self.conv.created_at)
        if self.conv.updated_at:
            data["updated_at"] = _iso(self.conv.updated_at)
        tags = ["ai-chat", f"provider:{self.conv.provider}"]
        if self.conv.model:
            tags.append(f"model:{self.conv.model}")
        data["tags"] = tags
        body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
        return f"---\n{body}\n---"

    def _render_message(self, msg: Message) -> str:
        ts = ""
        if msg.created_at:
            ts = " . " + msg.created_at.strftime("%Y-%m-%d %H:%M UTC")
        header = f"## {msg.role.value}{ts}"
        body_parts = [self._render_block(b) for b in msg.blocks]
        body = "\n\n".join(p for p in body_parts if p)
        atts = self._render_attachments(msg.attachments)
        chunks = [header]
        if body:
            chunks.append(body)
        if atts:
            chunks.append(atts)
        return "\n\n".join(chunks) + "\n"

    def _render_alternate(self, msg: Message) -> str:
        body_parts = [self._render_block(b) for b in msg.blocks]
        body = "\n".join(p for p in body_parts if p) or "(empty)"
        body = body.replace("\n", "\n> ")
        return f"> [!example]- Alternate branch ({msg.id[:8]} - {msg.role.value})\n> {body}\n"

    def _render_block(self, block: ContentBlock) -> str:
        match block.kind:
            case BlockKind.text:
                return (block.text or "").strip()
            case BlockKind.thinking:
                if not self.opts.include_thinking:
                    return ""
                return _callout("tip", "Thinking", block.text or "", collapsed_open=True)
            case BlockKind.tool_use:
                if not self.opts.include_tools:
                    return ""
                payload = _json_block(block.tool_input)
                return _callout(
                    "note", f"Tool: {block.tool_name or 'unknown'}", payload, collapsed_open=True
                )
            case BlockKind.tool_result:
                if not self.opts.include_tools:
                    return ""
                payload = _json_block(block.tool_output)
                return _callout("note", "Tool result", payload, collapsed_open=False)
            case BlockKind.image:
                name = self._track_attachment(block)
                return f"![[{name}]]" if name else ""
            case BlockKind.file:
                name = self._track_attachment(block)
                return f"[[{name}]]" if name else ""
            case BlockKind.citation:
                n = len(self._footnotes) + 1
                target = block.url or block.text or ""
                self._footnotes.append(f"[^{n}]: {target}")
                return f"[^{n}]"
        return ""

    def _render_attachments(self, atts: list[Attachment]) -> str:
        if not atts:
            return ""
        lines: list[str] = []
        for a in atts:
            self._remember_attachment(a)
            link = f"_attachments/{self.conv.provider}/{self.conv.id}/{a.filename}"
            if _is_image(a.filename):
                lines.append(f"![[{link}]]")
            else:
                lines.append(f"[[{link}|{a.filename}]]")
            if a.inline_text:
                snippet = a.inline_text.strip()
                if len(snippet) > 2000:
                    snippet = snippet[:2000] + "..."
                lines.append("")
                lines.append("```")
                lines.append(snippet)
                lines.append("```")
        return "\n".join(lines)

    def _track_attachment(self, block: ContentBlock) -> str | None:
        aid = block.attachment_id
        if not aid:
            return None
        for a in self._attachments:
            if a.id == aid:
                return f"_attachments/{self.conv.provider}/{self.conv.id}/{a.filename}"
        return None

    def _remember_attachment(self, a: Attachment) -> None:
        if a.id in self._att_seen:
            return
        self._att_seen.add(a.id)
        self._attachments.append(a)


def _callout(kind: str, title: str, body: str, *, collapsed_open: bool) -> str:
    marker = "+" if collapsed_open else "-"
    head = f"> [!{kind}]{marker} {title}"
    body = body.strip()
    if not body:
        return head
    quoted = "\n".join(f"> {line}" if line else ">" for line in body.split("\n"))
    return f"{head}\n{quoted}"


def _json_block(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return f"```\n{value}\n```"
    try:
        text = json.dumps(value, indent=2, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(value)
    return f"```json\n{text}\n```"


def _iso(dt: datetime) -> str:
    return dt.isoformat()


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".heic"}


def _is_image(filename: str) -> bool:
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in _IMAGE_EXTS)
