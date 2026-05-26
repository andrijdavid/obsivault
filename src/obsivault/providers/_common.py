from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from obsivault.core.models import BlockKind, Message, Role

EPOCH_UTC = datetime.min.replace(tzinfo=UTC)


def clip_title(text: str, *, limit: int = 80) -> str:
    one_line = " ".join(text.split())
    return one_line[: limit - 3] + "..." if len(one_line) > limit else one_line


def first_user_text(messages: Iterable[Message]) -> str | None:
    for m in messages:
        if m.role != Role.user:
            continue
        for b in m.blocks:
            if b.kind == BlockKind.text and b.text:
                return b.text
    return None


def iter_files(source: Path, pattern: str) -> Iterator[Path]:
    if source.is_file():
        yield source
        return
    if source.is_dir():
        yield from sorted(source.rglob(pattern))


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def role_from(name: str | None, *, extras: dict[str, Role] | None = None) -> Role:
    if not name:
        return Role.user
    if extras and name in extras:
        return extras[name]
    try:
        return Role(name)
    except ValueError:
        return Role.user


def build_main_path(messages: list[Message]) -> list[str] | None:
    if not messages:
        return None
    if not any(m.parent_id for m in messages):
        return [m.id for m in messages]
    by_id = {m.id: m for m in messages}
    parent_ids = {m.parent_id for m in messages if m.parent_id}
    leaves = [m for m in messages if m.id not in parent_ids]
    if not leaves:
        return [m.id for m in messages]
    order = {id(m): i for i, m in enumerate(messages)}
    leaf = max(leaves, key=lambda m: (m.created_at or EPOCH_UTC, order[id(m)]))
    chain: list[str] = []
    seen: set[str] = set()
    cur: Message | None = leaf
    while cur is not None and cur.id and cur.id not in seen:
        chain.append(cur.id)
        seen.add(cur.id)
        if not cur.parent_id:
            break
        cur = by_id.get(cur.parent_id)
    chain.reverse()
    return chain
