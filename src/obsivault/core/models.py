from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    user = "user"
    assistant = "assistant"
    system = "system"
    tool = "tool"


class BlockKind(StrEnum):
    text = "text"
    thinking = "thinking"
    tool_use = "tool_use"
    tool_result = "tool_result"
    image = "image"
    file = "file"
    citation = "citation"


class ContentBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kind: BlockKind
    text: str | None = None
    tool_name: str | None = None
    tool_input: Any = None
    tool_output: Any = None
    mime: str | None = None
    attachment_id: str | None = None
    url: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    filename: str
    mime: str | None = None
    size: int | None = None
    source_path: Path | None = None
    inline_text: str | None = None


class Message(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    parent_id: str | None = None
    role: Role
    created_at: datetime | None = None
    model: str | None = None
    blocks: list[ContentBlock] = Field(default_factory=list)
    attachments: list[Attachment] = Field(default_factory=list)


class Conversation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    provider: str
    model: str | None = None
    source_path: Path
    extra: dict[str, Any] = Field(default_factory=dict)
    messages: list[Message] = Field(default_factory=list)
    main_path: list[str] | None = None

    def iter_main(self) -> Iterator[Message]:
        if self.main_path is not None:
            by_id = {m.id: m for m in self.messages}
            for mid in self.main_path:
                msg = by_id.get(mid)
                if msg is not None:
                    yield msg
        else:
            yield from self.messages
