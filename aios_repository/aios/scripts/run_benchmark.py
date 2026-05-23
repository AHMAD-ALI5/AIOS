#!/usr/bin/env python3
"""
AIOS Benchmark Runner
Evaluates AIOS across RS, SD, and ADS task domains.
Usage: python scripts/run_benchmark.py --domain RS --limit 5
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer()
console = Console()


@app.command()
def main(
    domain: str = typer.Option("RS", help="Domain: RS, SD, ADS, ALL"),
    limit: int = typer.Option(5, help="Max tasks per domain"),
    enable_rqs: bool = typer.Option(False, help="Enable RQS scoring"),
    judge_model: str = typer.Option(
        "gpt-4o-2024-05-13",
        help="Judge model. Use different family from system model to reduce self-evaluation bias. "
             "E.g., if system uses gpt-4o, set to claude-3-opus-20240229"
    ),
    output: str = typer.Option("evaluation/results/benchmark_results.json", help="Output file"),
):
    """Run AIOS evaluation benchmark."""
    asyncio.run(_run(domain, limit, enable_rqs, judge_model, output))


async def _run(domain: str, limit: int, enable_rqs: bool, judge_model: str, output: str):
    from src.logging_config import setup_logging, get_logger
    from src.models import TaskDomain
    from src.runtime import AIOSRuntime
    from evaluation.metrics import BenchmarkRunner, BenchmarkResult
    from src.config import get_config
    
    logger = get_logger("benchmark")
    cfg = get_config()
    if judge_model != cfg.llm.judge_model:
        cfg.llm.judge_model = judge_model
        logger.info(f"Judge model overridden to: {judge_model}")

    setup_logging(level="WARNING")
    runtime = AIOSRuntime()
    await runtime.start()
    benchmark = BenchmarkRunner(enable_rqs=enable_rqs)

    domains_to_run = (
        [TaskDomain.RESEARCH_SYNTHESIS, TaskDomain.SOFTWARE_DEVELOPMENT, TaskDomain.ANALYTICAL_DECISION]
        if domain == "ALL"
        else [TaskDomain(domain)]
    )

    all_results = []

    for d in domains_to_run:
        tasks = _load_tasks(d, limit)
        if not tasks:
            console.print(f"[yellow]No tasks found for domain {d.value}[/yellow]")
            continue

        console.print(f"\n[bold]Evaluating domain: {d.value} ({len(tasks)} tasks)[/bold]")
        domain_results = []
        benchmark_start = time.time()

        for i, task_obj in enumerate(tasks):
            objective = task_obj.get("objective", task_obj.get("description", ""))
            console.print(f"  [{i+1}/{len(tasks)}] {objective[:60]}...")
            t0 = time.time()
            try:
                wf_result = await runtime.execute(
                    objective=objective, domain=d, timeout_seconds=120
                )
                records = list(runtime.scheduler.get_all_task_records(wf_result.workflow_id).values())
                eval_result = await benchmark.evaluate_workflow(
                    workflow_id=wf_result.workflow_id,
                    objective=objective,
                    task_records=records,
                    final_output=wf_result.result or "",
                    total_seconds=time.time() - t0,
                )
                domain_results.append(eval_result)
            except Exception as exc:
                console.print(f"    [red]Error: {exc}[/red]")

        if domain_results:
            benchmark_wall_seconds = time.time() - benchmark_start
            tasks_completed = sum(1 for r in domain_results for t in r.task_results if t.completed)
            throughput = (tasks_completed / benchmark_wall_seconds) * 3600 if benchmark_wall_seconds > 0 else 0.0

            avg_tcr = sum(r.tcr for r in domain_results) / len(domain_results)
            avg_atl = sum(r.atl for r in domain_results) / len(domain_results)
            memory_stats = await runtime.memory.get_stats()
            bench = BenchmarkResult(
                system_name="AIOS",
                domain=d.value,
                n_tasks=len(domain_results),
                tcr=avg_tcr,
                avg_rqs=sum(r.avg_rqs for r in domain_results) / len(domain_results) if enable_rqs else 0.0,
                mue=memory_stats.get("hit_rate", 0.0),
                atl_seconds=avg_atl,
                throughput_per_hour=round(throughput, 1),
            )
            all_results.append(bench.to_dict())

    await runtime.stop()

    # Print results table
    table = Table(title="AIOS Benchmark Results")
    if all_results:
        for col in all_results[0]:
            table.add_column(str(col), justify="right")
        for row in all_results:
            table.add_row(*[str(v) for v in row.values()])
        console.print(table)

        # Save results
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, "w") as f:
            json.dump(all_results, f, indent=2)
        console.print(f"\n[green]Results saved to {output}[/green]")


def _load_tasks(domain, limit: int) -> list[dict]:
    """Load tasks from the data directory."""
    domain_dirs = {
        "RS": "data/tasks/research_synthesis",
        "SD": "data/tasks/software_dev",
        "ADS": "data/tasks/analytical_ds",
    }
    root = Path(__file__).resolve().parents[1]
    task_dir = root / domain_dirs.get(domain.value, "data/tasks/research_synthesis")
    tasks = []
    for f in sorted(task_dir.glob("*.json"))[:limit]:
        with open(f) as fp:
            tasks.append(json.load(fp))
    # If no task files, return demo tasks
    if not tasks:
        tasks = [
            {"objective": "Briefly explain the attention mechanism in transformers"},
            {"objective": "Write a Python function to compute Fibonacci numbers with memoization"},
            {"objective": "Analyze the trade-offs between Redis and Memcached for session storage"},
        ][:limit]
    return tasks


if __name__ == "__main__":
    app()
