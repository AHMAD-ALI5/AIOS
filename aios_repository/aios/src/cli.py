"""
AIOS Command-Line Interface
Usage: aios [command] [options]
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

app = typer.Typer(
    name="aios",
    help="AIOS — Agentic AI Operating System CLI",
    no_args_is_help=True,
)
console = Console()


@app.command()
def run(
    host: str = typer.Option("0.0.0.0", help="Gateway host"),
    port: int = typer.Option(8000, help="Gateway port"),
    workers: int = typer.Option(4, help="Number of workers"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload (dev mode)"),
    log_level: str = typer.Option("info", help="Log level"),
):
    """Start the AIOS Gateway server."""
    import uvicorn
    console.print(Panel.fit(
        "[bold green]AIOS Gateway[/bold green]\n"
        f"Host: {host}:{port} | Workers: {workers}",
        border_style="green"
    ))
    uvicorn.run(
        "src.gateway.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_level=log_level,
    )


@app.command()
def execute(
    objective: str = typer.Argument(..., help="Task objective"),
    domain: str = typer.Option("GENERAL", help="Task domain: RS, SD, ADS, GENERAL"),
    timeout: int = typer.Option(300, help="Timeout in seconds"),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
):
    """Execute a task objective directly (without HTTP gateway)."""
    from src.logging_config import setup_logging
    from src.models import TaskDomain
    from src.runtime import AIOSRuntime

    setup_logging(level="WARNING")

    try:
        task_domain = TaskDomain(domain)
    except ValueError:
        console.print(f"[red]Invalid domain: {domain}[/red]")
        raise typer.Exit(1)

    async def _run():
        runtime = AIOSRuntime()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            prog_task = progress.add_task("Running AIOS workflow...", total=None)
            await runtime.start()
            try:
                result = await runtime.execute(
                    objective=objective,
                    domain=task_domain,
                    timeout_seconds=timeout,
                )
            finally:
                await runtime.stop()
        return result

    result = asyncio.run(_run())

    if output_json:
        console.print_json(result.model_dump_json())
    else:
        console.print(Panel(
            result.result or "[dim]No output[/dim]",
            title=f"[bold]Result[/bold] | Status: {result.status.value} | "
                  f"Time: {result.total_execution_time_seconds:.1f}s",
            border_style="blue",
        ))


@app.command()
def health(
    host: str = typer.Option("localhost", help="Gateway host"),
    port: int = typer.Option(8000, help="Gateway port"),
):
    """Check gateway health."""
    import urllib.request
    import urllib.error
    url = f"http://{host}:{port}/v1/health"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            console.print(f"[green]✓ Gateway healthy[/green] — {data}")
    except Exception as exc:
        console.print(f"[red]✗ Gateway unreachable[/red]: {exc}")
        raise typer.Exit(1)


@app.command()
def version():
    """Show AIOS version."""
    from src import __version__
    console.print(f"AIOS v{__version__}")


if __name__ == "__main__":
    app()
