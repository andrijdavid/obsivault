from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Protocol, runtime_checkable

from obsivault.core.models import Conversation


@dataclass(frozen=True)
class ParseOpts:
    include_tools: bool = False
    include_thinking: bool = False
    branches: bool = False
    copy_attachments: bool = True
    strip_grok_render: bool = False
    extras: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class Provider(Protocol):
    name: ClassVar[str]

    @classmethod
    def discover(cls, source: Path) -> bool: ...

    @classmethod
    def parse(cls, source: Path, *, opts: ParseOpts) -> Iterator[Conversation]: ...


_REGISTRY: dict[str, type[Provider]] = {}


def register(cls: type[Provider]) -> type[Provider]:
    name = cls.name
    if not name:
        raise ValueError(f"Provider {cls!r} has no name")
    if name in _REGISTRY and _REGISTRY[name] is not cls:
        raise ValueError(f"Provider name {name!r} already registered")
    _REGISTRY[name] = cls
    return cls


def get(name: str) -> type[Provider]:
    try:
        return _REGISTRY[name]
    except KeyError as exc:
        raise KeyError(f"Unknown provider {name!r}. Known: {sorted(_REGISTRY)}") from exc


def all_providers() -> list[type[Provider]]:
    return list(_REGISTRY.values())


def autodetect(source: Path) -> list[type[Provider]]:
    return [p for p in _REGISTRY.values() if p.discover(source)]
