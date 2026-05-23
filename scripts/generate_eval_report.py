#!/usr/bin/env python3
"""Generate docs/results.md from evaluation/results/comparison_table.json."""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
app = typer.Typer()

@app.command()
def main(
    input_file: str = typer.Option("evaluation/results/comparison_table.json"),
    output_file: str = typer.Option("docs/results.md"),
):
    with open(input_file) as f:
        data = json.load(f)
    
    systems = data.get("systems", {})
    comps = data.get("comparisons", {})
    
    lines = [
        "# AIOS Evaluation Results\n",
        f"**Generated from:** `{input_file}`  ",
        f"**Dataset:** See `data/tasks/dataset_hash.json`\n",
        "## Primary Results\n",
        "| System | TCR mean | TCR 95% CI | n |",
        "|--------|----------|------------|---|",
    ]
    for sys_name, stats in systems.items():
        ci = f"[{stats.get('ci_lower', 0)*100:.1f}%–{stats.get('ci_upper', 0)*100:.1f}%]"
        lines.append(f"| {sys_name} | {stats.get('mean', 0)*100:.1f}% | {ci} | {stats.get('n', 0)} |")
    
    lines += [
        "\n## Statistical Tests\n",
        "| Comparison | t | p-value | Cohen's d | Significant? |",
        "|------------|---|---------|-----------|--------------|",
    ]
    for comp_name, comp in comps.items():
        sig = "Yes (p<0.05)" if comp.get("significant") else "No"
        lines.append(
            f"| {comp_name} | {comp.get('t', 0):.2f} | "
            f"{comp.get('p', 1):.3f} | {comp.get('cohens_d', 0):.2f} | {sig} |"
        )
    
    Path(output_file).write_text("\n".join(lines) + "\n")
    print(f"Results report written to {output_file}")

if __name__ == "__main__":
    app()
