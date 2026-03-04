"""CLI for the web clipper."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from browser_demo.clipper import ClipError, clip_url
from browser_demo.store import ClipStore

app = typer.Typer(
    name="remora-clip",
    help="Playwright-based web clipper — fetch, convert to markdown, store locally.",
    no_args_is_help=True,
)
console = Console()

DEFAULT_CLIPS_DIR = Path(".clips")


def _get_store(clips_dir: Path) -> ClipStore:
    return ClipStore(clips_dir)


@app.command()
def clip(
    url: Annotated[str, typer.Argument(help="URL to clip")],
    tag: Annotated[Optional[list[str]], typer.Option("--tag", "-t", help="Add a tag (repeatable)")] = None,
    selector: Annotated[
        Optional[str], typer.Option("--select", "-s", help="CSS selector to extract specific content")
    ] = None,
    strip_images: Annotated[bool, typer.Option("--strip-images", help="Remove images from output")] = False,
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    no_headless: Annotated[bool, typer.Option("--no-headless", help="Show browser window")] = False,
) -> None:
    """Clip a URL: fetch via Playwright, convert to markdown, save locally."""
    try:
        record = asyncio.run(
            clip_url(
                url,
                clips_dir=clips_dir,
                tags=tag or [],
                selector=selector,
                strip_images=strip_images,
                headless=not no_headless,
            )
        )
        console.print(f"[green]Clipped:[/green] {record.title}")
        console.print(f"  ID: {record.clip_id}")
        console.print(f"  URL: {record.url}")
        console.print(f"  Tags: {', '.join(record.tags) if record.tags else '(none)'}")
        console.print(f"  File: {clips_dir / record.filename()}")
    except ClipError as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(code=1) from e


@app.command(name="list")
def list_clips(
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 50,
) -> None:
    """List all saved clips."""
    store = _get_store(clips_dir)
    try:
        clips = store.list_all(limit=limit)
        if not clips:
            console.print("[dim]No clips found.[/dim]")
            return

        table = Table(title=f"Clips ({store.count()} total)")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("Tags", style="green")
        table.add_column("Date", style="dim")

        for meta in clips:
            table.add_row(
                meta.clip_id,
                meta.title[:60] + ("..." if len(meta.title) > 60 else ""),
                ", ".join(meta.tags) if meta.tags else "",
                meta.clipped_at.strftime("%Y-%m-%d %H:%M"),
            )
        console.print(table)
    finally:
        store.close()


@app.command()
def show(
    clip_id: Annotated[str, typer.Argument(help="Clip ID to show")],
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    metadata_only: Annotated[bool, typer.Option("--meta", "-m", help="Show only metadata")] = False,
) -> None:
    """Show a clip's content."""
    store = _get_store(clips_dir)
    try:
        record = store.get(clip_id)
        if record is None:
            console.print(f"[red]Clip not found:[/red] {clip_id}")
            raise typer.Exit(code=1)

        console.print(f"[cyan]ID:[/cyan] {record.clip_id}")
        console.print(f"[cyan]URL:[/cyan] {record.url}")
        console.print(f"[cyan]Title:[/cyan] {record.title}")
        console.print(f"[cyan]Tags:[/cyan] {', '.join(record.tags) if record.tags else '(none)'}")
        console.print(f"[cyan]Clipped:[/cyan] {record.metadata.clipped_at.strftime('%Y-%m-%d %H:%M:%S')}")
        console.print(f"[cyan]Hash:[/cyan] {record.metadata.content_hash}")

        if not metadata_only:
            console.print()
            console.print(record.content)
    finally:
        store.close()


@app.command()
def search(
    query: Annotated[str, typer.Argument(help="Search query (full-text)")],
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    limit: Annotated[int, typer.Option("--limit", "-n", help="Max results")] = 20,
) -> None:
    """Search clips by title, content, or tags."""
    store = _get_store(clips_dir)
    try:
        results = store.search(query, limit=limit)
        if not results:
            console.print(f"[dim]No results for '{query}'[/dim]")
            return

        table = Table(title=f"Search: {query}")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Title", style="white")
        table.add_column("Tags", style="green")
        table.add_column("URL", style="dim")

        for meta in results:
            table.add_row(
                meta.clip_id,
                meta.title[:50] + ("..." if len(meta.title) > 50 else ""),
                ", ".join(meta.tags) if meta.tags else "",
                meta.url[:40] + ("..." if len(meta.url) > 40 else ""),
            )
        console.print(table)
    finally:
        store.close()


@app.command()
def delete(
    clip_id: Annotated[str, typer.Argument(help="Clip ID to delete")],
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    force: Annotated[bool, typer.Option("--force", "-f", help="Skip confirmation")] = False,
) -> None:
    """Delete a clip."""
    store = _get_store(clips_dir)
    try:
        if not force:
            record = store.get(clip_id)
            if record is None:
                console.print(f"[red]Clip not found:[/red] {clip_id}")
                raise typer.Exit(code=1)
            confirm = typer.confirm(f"Delete clip '{record.title}' ({clip_id})?")
            if not confirm:
                console.print("[dim]Cancelled.[/dim]")
                return

        if store.delete(clip_id):
            console.print(f"[green]Deleted:[/green] {clip_id}")
        else:
            console.print(f"[red]Clip not found:[/red] {clip_id}")
            raise typer.Exit(code=1)
    finally:
        store.close()


@app.command()
def export(
    clip_id: Annotated[str, typer.Argument(help="Clip ID to export")],
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
    with_frontmatter: Annotated[bool, typer.Option("--frontmatter", help="Include YAML frontmatter")] = False,
) -> None:
    """Export a clip's markdown to stdout."""
    store = _get_store(clips_dir)
    try:
        record = store.get(clip_id)
        if record is None:
            console.print(f"[red]Clip not found:[/red] {clip_id}", stderr=True)
            raise typer.Exit(code=1)

        if with_frontmatter:
            typer.echo(record.to_frontmatter_markdown())
        else:
            typer.echo(record.content)
    finally:
        store.close()


@app.command()
def tags(
    clips_dir: Annotated[Path, typer.Option("--dir", "-d", help="Clips directory")] = DEFAULT_CLIPS_DIR,
) -> None:
    """List all tags with clip counts."""
    store = _get_store(clips_dir)
    try:
        all_clips = store.list_all(limit=10000)
        tag_counts: dict[str, int] = {}
        for meta in all_clips:
            for t in meta.tags:
                tag_counts[t] = tag_counts.get(t, 0) + 1

        if not tag_counts:
            console.print("[dim]No tags found.[/dim]")
            return

        table = Table(title="Tags")
        table.add_column("Tag", style="green")
        table.add_column("Clips", style="cyan", justify="right")

        for tag_name, count in sorted(tag_counts.items()):
            table.add_row(tag_name, str(count))
        console.print(table)
    finally:
        store.close()


if __name__ == "__main__":
    app()
