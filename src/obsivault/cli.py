from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

import obsivault.providers  # noqa: F401
from obsivault import __version__
from obsivault.core.provider import ParseOpts, all_providers, autodetect, get
from obsivault.core.render import MarkdownRenderer, RenderOpts
from obsivault.core.writer import VaultWriter

app = typer.Typer(add_completion=False, help="Convert AI chat exports into an Obsidian vault.")
console = Console()


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def providers() -> None:
    table = Table(title="Registered providers")
    table.add_column("name")
    table.add_column("class")
    for p in all_providers():
        table.add_row(p.name, f"{p.__module__}.{p.__qualname__}")
    console.print(table)


@app.command()
def convert(
    source: Annotated[Path, typer.Argument(exists=True, readable=True)],
    vault: Annotated[Path, typer.Argument()],
    provider: Annotated[str, typer.Option(help="Provider name or 'auto' to detect.")] = "auto",
    include_tools: Annotated[bool, typer.Option("--include-tools/--no-include-tools")] = False,
    include_thinking: Annotated[
        bool, typer.Option("--include-thinking/--no-include-thinking")
    ] = False,
    branches: Annotated[bool, typer.Option("--branches/--no-branches")] = False,
    copy_attachments: Annotated[
        bool, typer.Option("--copy-attachments/--no-copy-attachments")
    ] = True,
    strip_grok_render: Annotated[bool, typer.Option("--strip-grok-render")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    force: Annotated[bool, typer.Option("--force")] = False,
    verbose: Annotated[int, typer.Option("-v", count=True)] = 0,
) -> None:
    cls = _select_provider(source, provider)
    if verbose:
        console.log(f"provider: {cls.name}")
        console.log(f"source:   {source}")
        console.log(f"vault:    {vault}")

    parse_opts = ParseOpts(
        include_tools=include_tools,
        include_thinking=include_thinking,
        branches=branches,
        copy_attachments=copy_attachments,
        strip_grok_render=strip_grok_render,
    )
    render_opts = RenderOpts(
        include_tools=include_tools,
        include_thinking=include_thinking,
        branches=branches,
        strip_grok_render=strip_grok_render,
    )

    vault.mkdir(parents=True, exist_ok=True)
    written = skipped = errors = att_copies = 0
    with VaultWriter(vault, dry_run=dry_run, force=force) as writer:
        for conv in cls.parse(source, opts=parse_opts):
            try:
                doc = MarkdownRenderer(conv, render_opts).render()
                result = writer.write(conv, doc)
                if result.skipped:
                    skipped += 1
                elif result.written:
                    written += 1
                att_copies += result.attachments_copied
                if verbose >= 2:
                    action = "skip" if result.skipped else ("plan" if dry_run else "write")
                    console.log(f"{action}: {result.path}")
            except Exception as exc:
                errors += 1
                console.log(f"[red]error[/red] {conv.id}: {exc}")

    summary = f"written={written} skipped={skipped} errors={errors}"
    if copy_attachments:
        summary += f" attachments_copied={att_copies}"
    console.log(summary)
    if errors:
        raise typer.Exit(code=1)


def _select_provider(source: Path, name: str):
    if name == "auto":
        matches = autodetect(source)
        if not matches:
            raise typer.BadParameter(f"No provider matched {source}")
        if len(matches) > 1:
            names = ", ".join(p.name for p in matches)
            raise typer.BadParameter(
                f"Ambiguous source {source}: matched {names}. Pass --provider to disambiguate."
            )
        return matches[0]
    try:
        return get(name)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc


if __name__ == "__main__":
    app()
