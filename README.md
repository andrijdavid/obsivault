# obsivault

Convert your AI chat exports into a tidy Obsidian Markdown vault. One note per
conversation, YAML frontmatter, attachments copied into a sibling folder, and
an idempotent state file so re-running only touches what changed.

Supported sources (v0.1):

- **Claude** (Settings -> Privacy -> Export). Reads `conversations.json`.
- **Grok** (Settings -> Data controls -> Export). Reads `prod-grok-backend.json`.
- **Gemini** via Google Takeout (My Activity -> Gemini Apps and Gemini in
  Workspace). Reads the Workspace transcripts and, optionally, NotebookLM.

## Install

```sh
uv sync
```

## Usage

```sh
uv run obsivault providers
uv run obsivault convert ./data/claude  ./vault --provider claude
uv run obsivault convert ./data/grok    ./vault --provider grok
uv run obsivault convert ./data/google  ./vault --provider gemini
```

Useful flags:

- `--include-tools` show tool calls as collapsible callouts
- `--include-thinking` show Claude thinking blocks as collapsible callouts
- `--branches` render alternate branches as `> [!example]-` callouts
- `--no-copy-attachments` skip the attachment copy step
- `--dry-run` plan-only, no writes
- `--force` rewrite even when content hash is unchanged

## Layout

```
vault/
  claude/2026-04/<slug>.md
  grok/2026-05/<slug>.md
  gemini/2026-03/<slug>.md
  _attachments/<provider>/<conv-id>/...
  .obsivault/state.json
```

## Adding a provider

Drop a module under `src/obsivault/providers/<name>.py` with a class that
implements `Provider` and is decorated with `@register`. The CLI auto-detects
sources by calling each provider's `discover()`.

## Licence

AGPL-3.0-or-later. PRs welcome.
