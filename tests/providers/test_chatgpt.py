from __future__ import annotations

import json
from pathlib import Path

from obsivault.core.provider import ParseOpts
from obsivault.providers.chatgpt import ChatGPTProvider


def _write_fixture(dest: Path) -> None:
    payload = [
        {
            "title": "demo",
            "create_time": 1700000000.0,
            "update_time": 1700000100.0,
            "conversation_id": "conv-1",
            "current_node": "n3",
            "mapping": {
                "root": {"id": "root", "parent": None, "children": ["n1"], "message": None},
                "n1": {
                    "id": "n1",
                    "parent": "root",
                    "children": ["n2"],
                    "message": {
                        "id": "n1",
                        "author": {"role": "user"},
                        "create_time": 1700000010.0,
                        "content": {"content_type": "text", "parts": ["hi"]},
                        "metadata": {},
                    },
                },
                "n2": {
                    "id": "n2",
                    "parent": "n1",
                    "children": ["n3"],
                    "message": {
                        "id": "n2",
                        "author": {"role": "assistant"},
                        "create_time": 1700000020.0,
                        "content": {"content_type": "text", "parts": ["hello back"]},
                        "metadata": {"model_slug": "gpt-5"},
                    },
                },
                "n3": {
                    "id": "n3",
                    "parent": "n2",
                    "children": [],
                    "message": {
                        "id": "n3",
                        "author": {"role": "user"},
                        "create_time": 1700000030.0,
                        "content": {"content_type": "text", "parts": ["thanks"]},
                        "metadata": {},
                    },
                },
            },
        }
    ]
    dest.write_text(json.dumps(payload), encoding="utf-8")


def test_discover_and_parse(tmp_path: Path):
    src = tmp_path / "conversations.json"
    _write_fixture(src)
    assert ChatGPTProvider.discover(tmp_path)
    convs = list(ChatGPTProvider.parse(tmp_path, opts=ParseOpts()))
    assert len(convs) == 1
    c = convs[0]
    assert c.title == "demo"
    assert c.model == "gpt-5"
    assert c.main_path == ["n1", "n2", "n3"]
    assert [m.role.value for m in c.iter_main()] == ["user", "assistant", "user"]
