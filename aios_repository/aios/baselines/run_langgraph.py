#!/usr/bin/env python3
"""LangGraph baseline benchmark runner."""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
from rich.console import Console

from baselines.langgraph_baseline import LangGraphBaseline
from evaluation.metrics import RQSJudge
from scripts.run_benchmark import _load_tasks, _get_git_hash

app = typer.Typer()
console = Console()

@app.command()
def main(
    domain: str = typer.Option("ALL"),
    limit: int = typer.Option(60),
    seeds: str = typer.Option("42,123,456"),
    temperature: float = typer.Option(0.0),
    enable_rqs: bool = typer.Option(False),
    output: str = typer.Option("evaluation/results/langgraph_multiseed.json"),
):
    asyncio.run(_run(domain, limit, [int(s) for s in seeds.split(",")], temperature, enable_rqs, output))

async def _run(domain, limit, seeds, temperature, enable_rqs, output):
    import random
    from src.models import TaskDomain
    
    judge = RQSJudge() if enable_rqs else None
    all_seed_results = {}

    for seed in seeds:
        random.seed(seed)
        console.print(f"\n[cyan]LangGraph | Seed {seed}[/cyan]")
        agent = LangGraphBaseline()
        
        domains = (
            [TaskDomain.RESEARCH_SYNTHESIS, TaskDomain.SOFTWARE_DEVELOPMENT, TaskDomain.ANALYTICAL_DECISION]
            if domain == "ALL" else [TaskDomain(domain)]
        )
        seed_results = []
        for d in domains:
            tasks = _load_tasks(d, limit)
            domain_tcrs, domain_atls = [], []
            for task_obj in tasks:
                objective = task_obj.get("objective", "")
                result = await agent.execute(objective, domain=d)
                rqs = None
                if enable_rqs and result["completed"] and judge:
                    rqs, _ = await judge.score(objective, result["output"])
                domain_tcrs.append(1.0 if result["completed"] else 0.0)
                domain_atls.append(result["execution_time_seconds"])

            seed_results.append({
                "domain": d.value,
                "TCR (%)": round(sum(domain_tcrs) / len(domain_tcrs) * 100, 1) if domain_tcrs else 0,
                "ATL (s)": round(sum(domain_atls) / len(domain_atls), 1) if domain_atls else 0,
                "MUE": 0.0,
                "RQS": 0.0,
                "Throughput (t/h)": 0.0,
            })
        all_seed_results[seed] = seed_results

    final = {
        "metadata": {
            "system": "LangGraph",
            "seeds": seeds,
            "temperature": temperature,
            "git_commit": _get_git_hash(),
        },
        "per_seed_results": {str(k): v for k, v in all_seed_results.items()},
    }
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(final, f, indent=2)
    console.print(f"[green]LangGraph results saved to {output}[/green]")

if __name__ == "__main__":
    app()
