from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, ClassVar

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify as html_to_md

from obsivault.core.models import BlockKind, ContentBlock, Conversation, Message, Role
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any

_WORKSPACE = "Conversation History"
_MYACTIVITY = "MyActivity.html"
_NOTEBOOKLM = "NotebookLM"
_GEMINI_APPS = "Gemini Apps"


@register
class GeminiProvider:
    name: ClassVar[str] = "gemini"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return any(
            (
                _find_workspace_dir(source),
                _find_myactivity_file(source),
                _find_notebooklm_dir(source),
            )
        )

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        ws = _find_workspace_dir(source)
        if ws is not None:
            yield from _parse_workspace(ws)

        my = _find_myactivity_file(source)
        if my is not None:
            yield from _parse_myactivity(my)

        nb = _find_notebooklm_dir(source)
        if nb is not None:
            yield from _parse_notebooklm(nb)


def _find_workspace_dir(source: Path) -> Path | None:
    if source.is_dir() and source.name == _WORKSPACE:
        return source
    if source.is_dir():
        for candidate in source.rglob(_WORKSPACE):
            if candidate.is_dir() and any(candidate.glob("conversation_*.txt")):
                return candidate
    return None


def _find_myactivity_file(source: Path) -> Path | None:
    if source.is_file() and source.name == _MYACTIVITY:
        return source
    if source.is_dir():
        direct = source / _MYACTIVITY
        if direct.exists():
            return direct
        for candidate in source.rglob(_MYACTIVITY):
            if _GEMINI_APPS in candidate.parts:
                return candidate
    return None


def _find_notebooklm_dir(source: Path) -> Path | None:
    if source.is_dir() and source.name == _NOTEBOOKLM:
        return source
    if source.is_dir():
        for candidate in source.rglob(_NOTEBOOKLM):
            if candidate.is_dir() and any(candidate.iterdir()):
                return candidate
    return None


def _parse_workspace(workspace: Path) -> Iterator[Conversation]:
    for path in sorted(workspace.glob("conversation_*.txt")):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        yield _convert_workspace(raw, source_path=path)


def _convert_workspace(raw: dict[str, Any], *, source_path: Path) -> Conversation:
    turns = raw.get("conversation_turns", []) or []
    messages: list[Message] = []
    for idx, turn in enumerate(turns):
        if "user_turn" in turn:
            u = turn["user_turn"]
            messages.append(
                Message(
                    id=f"{source_path.stem}-u{idx}",
                    role=Role.user,
                    created_at=parse_any(u.get("turn_last_modified")),
                    blocks=[ContentBlock(kind=BlockKind.text, text=u.get("prompt") or "")],
                )
            )
        elif "system_turn" in turn:
            s = turn["system_turn"]
            text_parts: list[str] = []
            citations: list[ContentBlock] = []
            for chunk in s.get("text", []) or []:
                data = chunk.get("data")
                if data:
                    text_parts.append(data)
                for cite in chunk.get("citations", []) or []:
                    url = cite.get("uri") or cite.get("url") or cite.get("display")
                    if url:
                        citations.append(ContentBlock(kind=BlockKind.citation, url=url))
            blocks: list[ContentBlock] = []
            if text_parts:
                blocks.append(ContentBlock(kind=BlockKind.text, text="\n\n".join(text_parts)))
            blocks.extend(citations)
            messages.append(
                Message(
                    id=f"{source_path.stem}-s{idx}",
                    role=Role.assistant,
                    created_at=parse_any(s.get("turn_last_modified")),
                    blocks=blocks,
                )
            )
    return Conversation(
        id=f"workspace-{source_path.stem}",
        title=raw.get("title") or None,
        created_at=parse_any(raw.get("creation_time")),
        updated_at=parse_any(raw.get("last_modification_time")),
        provider="gemini",
        source_path=source_path,
        messages=messages,
    )


_CELL_OPEN = re.compile(rb'<div class="outer-cell ')
_DATE_PATTERNS = [
    "%b %d, %Y, %I:%M:%S %p",
    "%b %d, %Y, %H:%M:%S",
]
_TZ_OFFSETS = {
    "UTC": 0,
    "GMT": 0,
    "BST": 60,
    "WET": 0,
    "WEST": 60,
    "CET": 60,
    "CEST": 120,
    "EET": 120,
    "EEST": 180,
    "MSK": 180,
    "EST": -300,
    "EDT": -240,
    "CST": -360,
    "CDT": -300,
    "MST": -420,
    "MDT": -360,
    "PST": -480,
    "PDT": -420,
    "AKST": -540,
    "AKDT": -480,
    "HST": -600,
    "IST": 330,
    "JST": 540,
    "KST": 540,
    "AEST": 600,
    "AEDT": 660,
    "NZST": 720,
    "NZDT": 780,
}


def _parse_myactivity(path: Path) -> Iterator[Conversation]:
    data = path.read_bytes()
    for cell_html in _iter_cells(data):
        conv = _convert_myactivity_cell(cell_html, source_path=path)
        if conv is not None:
            yield conv


def _iter_cells(data: bytes) -> Iterator[str]:
    starts = [m.start() for m in _CELL_OPEN.finditer(data)]
    starts.append(len(data))
    for i in range(len(starts) - 1):
        chunk = data[starts[i] : starts[i + 1]].decode("utf-8", errors="replace")
        yield chunk


def _convert_myactivity_cell(html: str, *, source_path: Path) -> Conversation | None:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.find("div", class_="content-cell")
    if body is None:
        return None
    if not isinstance(body, Tag):
        return None
    first_text = (body.find(string=True) or "").strip()
    if not first_text.startswith("Prompted"):
        return None

    prompt = first_text[len("Prompted") :].strip()
    timestamp, response_html = _split_after_first_br(body)
    created_at = _parse_myactivity_date(timestamp)
    response_md = html_to_md(response_html, heading_style="ATX").strip() if response_html else ""

    cell_id = _short_hash(html)
    messages = [
        Message(
            id=f"prompt-{cell_id}",
            role=Role.user,
            created_at=created_at,
            blocks=[ContentBlock(kind=BlockKind.text, text=prompt)],
        ),
    ]
    if response_md:
        messages.append(
            Message(
                id=f"response-{cell_id}",
                role=Role.assistant,
                created_at=created_at,
                blocks=[ContentBlock(kind=BlockKind.text, text=response_md)],
            )
        )

    return Conversation(
        id=f"myactivity-{cell_id}",
        title=_title_from_prompt(prompt),
        created_at=created_at,
        provider="gemini",
        source_path=source_path,
        messages=messages,
        extra={"kind": "myactivity"},
    )


def _split_after_first_br(body: Tag) -> tuple[str, str]:
    children = list(body.children)
    timestamp = ""
    rest_index = len(children)
    seen_br = 0
    for idx, child in enumerate(children):
        if getattr(child, "name", None) == "br":
            seen_br += 1
            if seen_br == 1:
                next_text = ""
                for nxt in children[idx + 1 :]:
                    if isinstance(nxt, str) and nxt.strip():
                        next_text = nxt.strip()
                        break
                    if getattr(nxt, "name", None) == "br":
                        break
                timestamp = next_text
            elif seen_br == 2:
                rest_index = idx + 1
                break
    rest_html = "".join(str(c) for c in children[rest_index:] if not _is_metadata_caption(c))
    return timestamp, rest_html


def _is_metadata_caption(node: Any) -> bool:
    if not isinstance(node, Tag):
        return False
    classes = node.get("class") or []
    return "mdl-typography--caption" in classes or "mdl-typography--text-right" in classes


def _parse_myactivity_date(text: str) -> datetime | None:
    if not text:
        return None
    cleaned = text.replace("\u202f", " ").replace("\xa0", " ").strip()
    tz_name = ""
    parts = cleaned.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isalpha() and parts[1].isupper():
        cleaned, tz_name = parts[0].rstrip(), parts[1]
    for fmt in _DATE_PATTERNS:
        try:
            dt = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        offset_minutes = _TZ_OFFSETS.get(tz_name, 0)
        local = dt.replace(tzinfo=timezone(timedelta(minutes=offset_minutes)))
        return local.astimezone(UTC)
    return parse_any(cleaned)


def _title_from_prompt(prompt: str) -> str:
    one_line = " ".join(prompt.split())
    if len(one_line) <= 80:
        return one_line
    return one_line[:77] + "..."


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _parse_notebooklm(root: Path) -> Iterator[Conversation]:
    for notebook in sorted(p for p in root.iterdir() if p.is_dir()):
        conv = _convert_notebook(notebook)
        if conv is not None:
            yield conv


def _convert_notebook(notebook: Path) -> Conversation | None:
    meta = _read_notebook_metadata(notebook)
    title = meta.get("title") or notebook.name
    emoji = meta.get("emoji") or ""
    md = meta.get("metadata") or {}
    created_at = parse_any(md.get("createTime"))
    updated_at = parse_any(md.get("lastViewed"))

    sources = _list_dir(notebook / "Sources")
    artifacts = _list_dir(notebook / "Artifacts")
    notes = _list_dir(notebook / "Notes")
    chat = _list_dir(notebook / "Chat History")

    body_lines: list[str] = []
    if emoji:
        body_lines.append(f"{emoji} **{title}**")
        body_lines.append("")
    if sources:
        body_lines.append("## Sources")
        body_lines.extend(f"- {name}" for name in sources)
        body_lines.append("")
    if notes:
        body_lines.append("## Notes")
        body_lines.extend(f"- {name}" for name in notes)
        body_lines.append("")
    if artifacts:
        body_lines.append("## Artifacts")
        body_lines.extend(f"- {name}" for name in artifacts)
        body_lines.append("")
    if chat:
        body_lines.append("## Chat history files")
        body_lines.extend(f"- {name}" for name in chat)

    body = "\n".join(body_lines).strip()
    if not body:
        return None

    message = Message(
        id=f"notebook-{notebook.name}",
        role=Role.system,
        created_at=created_at,
        blocks=[ContentBlock(kind=BlockKind.text, text=body)],
    )

    return Conversation(
        id=f"notebooklm-{notebook.name}",
        title=title,
        created_at=created_at,
        updated_at=updated_at,
        provider="gemini",
        source_path=notebook,
        messages=[message],
        extra={"kind": "notebooklm"},
    )


def _read_notebook_metadata(notebook: Path) -> dict[str, Any]:
    for candidate in notebook.glob("*metadata.json"):
        try:
            return json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _list_dir(path: Path) -> list[str]:
    if not path.is_dir():
        return []
    return sorted(p.name for p in path.iterdir() if not p.name.startswith("."))
