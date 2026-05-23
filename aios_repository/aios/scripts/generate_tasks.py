#!/usr/bin/env python3
"""
Generate evaluation task files for AIOS benchmark.
Human review is required before committing generated tasks.
Usage: python scripts/generate_tasks.py --domain RS --count 60 --output data/tasks/research_synthesis/
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import typer
from openai import AsyncOpenAI

app = typer.Typer()

_TASK_GEN_PROMPT = """Generate {n} diverse evaluation tasks for the {domain} domain.

Domain descriptions:
- RS (Research Synthesis): Summarizing papers, reviewing literature, synthesizing findings
- SD (Software Development): Writing code, debugging, designing systems, writing tests
- ADS (Analytical Decision Support): Analyzing data, comparing options, decision frameworks

Difficulty distribution: {easy} easy, {medium} medium, {hard} hard tasks.

Return a JSON array of task objects:
[
  {{
    "id": "{domain_lower}_{seq:03d}",
    "objective": "...",
    "domain": "{domain}",
    "difficulty": "easy|medium|hard",
    "expected_agent_types": ["research", "writer", ...]
  }}
]

Rules:
- Objectives must be specific, actionable, and completable by an LLM
- No tasks requiring real-time data, login credentials, or file system access
- Hard tasks require multi-step reasoning or synthesis of multiple sources
- Each task must be distinct — no near-duplicates
"""


@app.command()
def main(
    domain: str = typer.Option("RS", help="Domain: RS, SD, ADS"),
    count: int = typer.Option(60, help="Number of tasks to generate"),
    start_seq: int = typer.Option(2, help="Starting sequence number (existing files have 001)"),
    output: str = typer.Option("", help="Output directory"),
):
    asyncio.run(_generate(domain, count, start_seq, output))


async def _generate(domain: str, count: int, start_seq: int, output_dir: str):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = AsyncOpenAI(api_key=api_key)
    
    easy = count // 3
    medium = count // 3
    hard = count - easy - medium
    domain_lower = domain.lower()
    if domain == "RS": domain_lower = "rs"
    elif domain == "SD": domain_lower = "sd"
    elif domain == "ADS": domain_lower = "ads"

    prompt = _TASK_GEN_PROMPT.format(
        n=count, domain=domain, domain_lower=domain_lower,
        easy=easy, medium=medium, hard=hard, seq=start_seq
    )
    
    resp = await client.chat.completions.create(
        model="gpt-4o-2024-05-13",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        response_format={"type": "json_object"},
        max_tokens=8000,
    )
    
    import re
    raw = resp.choices[0].message.content
    # Extract array from response
    match = re.search(r'\[.*\]', raw, re.DOTALL)
    if not match:
        print("ERROR: No JSON array found in response")
        return
    
    tasks = json.loads(match.group())
    
    if not output_dir:
        domain_dirs = {"RS": "data/tasks/research_synthesis", "SD": "data/tasks/software_dev", "ADS": "data/tasks/analytical_ds"}
        output_dir = domain_dirs[domain]
    
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    for i, task in enumerate(tasks):
        # Re-sequence IDs
        task["id"] = f"{domain_lower}_{start_seq + i:03d}"
        fname = Path(output_dir) / f"{task['id']}.json"
        with open(fname, "w") as f:
            json.dump(task, f, indent=2)
        print(f"  Created: {fname}")
    
    print(f"\n✅ Generated {len(tasks)} tasks in {output_dir}")
    print("⚠️  HUMAN REVIEW REQUIRED before committing these tasks.")


if __name__ == "__main__":
    app()
