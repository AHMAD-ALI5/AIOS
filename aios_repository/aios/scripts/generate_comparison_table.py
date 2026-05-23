#!/usr/bin/env python3
"""Generate final comparison table from all system result files."""

from __future__ import annotations

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
from evaluation.statistical_analysis import compare_systems, MetricStats

app = typer.Typer()

@app.command()
def main(
    aios: str = typer.Option(...),
    single_agent: str = typer.Option(...),
    langgraph: str = typer.Option(...),
    output: str = typer.Option("evaluation/results/comparison_table.json"),
):
    with open(aios) as f: aios_data = json.load(f)
    with open(single_agent) as f: sa_data = json.load(f)
    with open(langgraph) as f: lg_data = json.load(f)

    def extract_tcr(data):
        results = []
        for seed_results in data.get("per_seed_results", {}).values():
            for r in seed_results:
                results.append(r.get("TCR (%)", 0) / 100)
        return results

    aios_tcr = extract_tcr(aios_data)
    sa_tcr = extract_tcr(sa_data)
    lg_tcr = extract_tcr(lg_data)

    aios_vs_sa = compare_systems("TCR", "AIOS", aios_tcr, "Single-Agent", sa_tcr)
    aios_vs_lg = compare_systems("TCR", "AIOS", aios_tcr, "LangGraph", lg_tcr)

    table = {
        "systems": {
            "AIOS": MetricStats("TCR", aios_tcr).__dict__,
            "Single-Agent": MetricStats("TCR", sa_tcr).__dict__,
            "LangGraph": MetricStats("TCR", lg_tcr).__dict__,
        },
        "comparisons": {
            "AIOS_vs_SingleAgent": {
                "t": aios_vs_sa.t_statistic,
                "p": aios_vs_sa.p_value,
                "cohens_d": aios_vs_sa.cohens_d,
                "significant": aios_vs_sa.significant_at_05,
            },
            "AIOS_vs_LangGraph": {
                "t": aios_vs_lg.t_statistic,
                "p": aios_vs_lg.p_value,
                "cohens_d": aios_vs_lg.cohens_d,
                "significant": aios_vs_lg.significant_at_05,
            },
        },
    }
    with open(output, "w") as f:
        json.dump(table, f, indent=2)
    print(f"Comparison table saved to {output}")
    print(aios_vs_sa.summary())
    print(aios_vs_lg.summary())

if __name__ == "__main__":
    app()
