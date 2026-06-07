from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar

from obsivault.core.models import Attachment, BlockKind, ContentBlock, Conversation, Message
from obsivault.core.provider import ParseOpts, register
from obsivault.core.timeutil import parse_any
from obsivault.providers._common import clip_title, first_user_text, role_from


@register
class OpenCodeProvider:
    name: ClassVar[str] = "opencode"

    @classmethod
    def discover(cls, source: Path) -> bool:
        return _resolve_db(source) is not None

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]:
        db = _resolve_db(source)
        if db is None:
            return
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            conn.row_factory = sqlite3.Row
            projects = _load_projects(conn)
            sessions = conn.execute(
                "SELECT id, project_id, title, time_created, time_updated,"
                " agent, model FROM session ORDER BY time_created"
            ).fetchall()
            for row in sessions:
                conv = _convert_session(conn, row, projects, source_path=db)
                if conv is not None:
                    yield conv
        finally:
            conn.close()


def _resolve_db(source: Path) -> Path | None:
    if source.is_file() and source.suffix == ".db":
        return source
    if source.is_dir():
        candidate = source / "opencode.db"
        if candidate.is_file():
            return candidate
    return None


def _load_projects(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = conn.execute("SELECT id, worktree, name FROM project").fetchall()
    return {r["id"]: dict(r) for r in rows}


def _convert_session(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    projects: dict[str, dict[str, Any]],
    *,
    source_path: Path,
) -> Conversation | None:
    session_id = row["id"]
    project = projects.get(row["project_id"]) or {}
    model = _decode_model(row["model"])
    messages = list(_session_messages(conn, session_id))
    if not messages:
        return None
    title = (row["title"] or "").strip() or first_user_text(messages) or session_id
    extras: dict[str, Any] = {}
    if project.get("worktree"):
        extras["cwd"] = project["worktree"]
    if project.get("name"):
        extras["project"] = project["name"]
    if row["agent"]:
        extras["agent"] = row["agent"]
    return Conversation(
        id=f"opencode-{session_id}",
        title=clip_title(title),
        created_at=parse_any(row["time_created"]),
        updated_at=parse_any(row["time_updated"]),
        provider="opencode",
        model=model,
        source_path=source_path,
        messages=messages,
        extra=extras,
    )


def _session_messages(conn: sqlite3.Connection, session_id: str) -> Iterator[Message]:
    msg_rows = conn.execute(
        "SELECT id, time_created, data FROM message WHERE session_id=? ORDER BY time_created",
        (session_id,),
    ).fetchall()
    if not msg_rows:
        return
    parts_by_message: dict[str, list[dict[str, Any]]] = {}
    for prow in conn.execute(
        "SELECT message_id, data FROM part WHERE session_id=? ORDER BY time_created",
        (session_id,),
    ):
        try:
            parts_by_message.setdefault(prow["message_id"], []).append(json.loads(prow["data"]))
        except json.JSONDecodeError:
            continue
    for mrow in msg_rows:
        try:
            mdata = json.loads(mrow["data"])
        except json.JSONDecodeError:
            continue
        blocks: list[ContentBlock] = []
        attachments: list[Attachment] = []
        for pdata in parts_by_message.get(mrow["id"], []):
            _absorb_part(pdata, blocks, attachments)
        if not blocks and not attachments:
            continue
        yield Message(
            id=str(mrow["id"]),
            parent_id=mdata.get("parentID"),
            role=role_from(mdata.get("role")),
            created_at=parse_any(mrow["time_created"]),
            model=mdata.get("modelID"),
            blocks=blocks,
            attachments=attachments,
        )


def _absorb_part(
    pdata: dict[str, Any],
    blocks: list[ContentBlock],
    attachments: list[Attachment],
) -> None:
    ptype = pdata.get("type")
    if ptype == "text":
        text = pdata.get("text") or ""
        if text.strip():
            blocks.append(ContentBlock(kind=BlockKind.text, text=text))
    elif ptype == "reasoning":
        text = pdata.get("text") or ""
        if text.strip():
            blocks.append(ContentBlock(kind=BlockKind.thinking, text=text))
    elif ptype == "tool":
        state = pdata.get("state") or {}
        blocks.append(
            ContentBlock(
                kind=BlockKind.tool_use,
                tool_name=pdata.get("tool"),
                tool_input=state.get("input"),
            )
        )
        output = state.get("output")
        if output is not None:
            blocks.append(ContentBlock(kind=BlockKind.tool_result, tool_output=output))
    elif ptype == "file":
        url = pdata.get("url") or ""
        filename = pdata.get("filename") or Path(url).name or "file"
        source = Path(url[len("file://") :]) if url.startswith("file://") else None
        attachments.append(
            Attachment(
                id=str(pdata.get("id") or filename),
                filename=filename,
                mime=pdata.get("mime"),
                source_path=source,
            )
        )
    elif ptype == "patch":
        files = pdata.get("files") or []
        if files:
            summary = "\n".join(f"- {_patch_label(f)}" for f in files)
            blocks.append(
                ContentBlock(
                    kind=BlockKind.text,
                    text=f"**Patch applied to:**\n{summary}",
                )
            )


def _patch_label(entry: Any) -> str:
    if isinstance(entry, dict):
        return str(entry.get("path") or entry.get("name") or entry)
    return str(entry)


def _decode_model(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("{"):
            try:
                obj = json.loads(text)
                return obj.get("id") or obj.get("modelID")
            except json.JSONDecodeError:
                return text or None
        return text or None
    if isinstance(raw, dict):
        return raw.get("id") or raw.get("modelID")
    return None
