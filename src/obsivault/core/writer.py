from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from slugify import slugify

from obsivault.core.models import Attachment, Conversation
from obsivault.core.render import RenderedDoc

_STATE_DIR = ".obsivault"
_STATE_FILE = "state.json"


@dataclass
class WriteResult:
    path: Path
    written: bool
    skipped: bool
    attachments_copied: int


class VaultWriter:
    def __init__(self, vault: Path, *, dry_run: bool = False, force: bool = False) -> None:
        self.vault = vault
        self.dry_run = dry_run
        self.force = force
        self._state = _load_state(vault)
        self._dirty = False

    def write(self, conv: Conversation, doc: RenderedDoc) -> WriteResult:
        target = self._target_path(conv)
        state_key = f"{conv.provider}:{conv.id}"
        new_hash = _content_hash(doc.text)
        prev = self._state.get(state_key)
        if prev and prev.get("hash") == new_hash and not self.force:
            return WriteResult(path=target, written=False, skipped=True, attachments_copied=0)

        if self.dry_run:
            return WriteResult(path=target, written=True, skipped=False, attachments_copied=0)

        target.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(target, doc.text)
        copied = self._copy_attachments(conv, doc.attachments)
        self._state[state_key] = {"hash": new_hash, "path": str(target.relative_to(self.vault))}
        self._dirty = True
        return WriteResult(path=target, written=True, skipped=False, attachments_copied=copied)

    def flush(self) -> None:
        if self._dirty and not self.dry_run:
            _save_state(self.vault, self._state)
            self._dirty = False

    def __enter__(self) -> VaultWriter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.flush()

    def _target_path(self, conv: Conversation) -> Path:
        bucket = conv.created_at.strftime("%Y-%m") if conv.created_at else "undated"
        slug = _slug(conv.title) or conv.id[:8]
        folder = self.vault / conv.provider / bucket
        candidate = folder / f"{slug}.md"
        prev_state = self._state.get(f"{conv.provider}:{conv.id}")
        if prev_state and prev_state.get("path"):
            return self.vault / prev_state["path"]
        return _disambiguate(candidate)

    def _copy_attachments(self, conv: Conversation, atts: list[Attachment]) -> int:
        copyable = [a for a in atts if a.source_path and a.source_path.is_file()]
        if not copyable:
            return 0
        dest_dir = self.vault / "_attachments" / conv.provider / conv.id
        dest_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for a in copyable:
            assert a.source_path is not None
            dest = dest_dir / a.filename
            if dest.exists() and dest.stat().st_size == a.source_path.stat().st_size:
                continue
            shutil.copy2(a.source_path, dest)
            count += 1
        return count


def _slug(title: str | None) -> str:
    if not title:
        return ""
    return slugify(title, max_length=80, lowercase=True)


_FM_SUB = re.compile(r"^---\n.*?\n---\n", re.DOTALL)


def _content_hash(text: str) -> str:
    stripped = _FM_SUB.sub("", text, count=1)
    return hashlib.sha256(stripped.encode("utf-8")).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _disambiguate(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for i in range(2, 10000):
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not disambiguate path {path}")


def _state_path(vault: Path) -> Path:
    return vault / _STATE_DIR / _STATE_FILE


def _load_state(vault: Path) -> dict[str, dict[str, str]]:
    p = _state_path(vault)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(vault: Path, state: dict[str, dict[str, str]]) -> None:
    p = _state_path(vault)
    p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(p, json.dumps(state, indent=2, sort_keys=True))
