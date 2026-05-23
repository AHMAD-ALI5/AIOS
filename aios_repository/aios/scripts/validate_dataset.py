#!/usr/bin/env python3
"""Validate all task files against the schema and check for duplicates."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

def main():
    schema_path = Path("data/tasks/schema.json")
    if not schema_path.exists():
        print("ERROR: data/tasks/schema.json not found")
        sys.exit(1)
    
    with open(schema_path) as f:
        schema = json.load(f)
    
    task_dirs = [
        Path("data/tasks/research_synthesis"),
        Path("data/tasks/software_dev"),
        Path("data/tasks/analytical_ds"),
    ]
    
    all_objectives = []
    errors = []
    counts = {}
    
    for task_dir in task_dirs:
        if not task_dir.exists():
            errors.append(f"Directory missing: {task_dir}")
            continue
        
        files = sorted(task_dir.glob("*.json"))
        domain = task_dir.name
        counts[domain] = len(files)
        
        for f in files:
            try:
                with open(f) as fp:
                    task = json.load(fp)
                if HAS_JSONSCHEMA:
                    jsonschema.validate(task, schema)
                all_objectives.append(task.get("objective", ""))
            except Exception as exc:
                errors.append(f"{f}: {exc}")
    
    # Check for near-duplicate objectives (exact match)
    seen = set()
    for obj in all_objectives:
        if obj in seen:
            errors.append(f"Duplicate objective: {obj[:80]}...")
        seen.add(obj)
    
    print("Dataset Validation Report")
    print("=" * 40)
    for domain, count in counts.items():
        status = "OK" if count >= 60 else f"WARNING (need {60 - count} more)"
        print(f"  {domain}: {count} tasks {status}")
    print(f"  Total: {sum(counts.values())} tasks")
    
    if errors:
        print(f"\nERROR: {len(errors)} errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\nOK: All task files valid")

if __name__ == "__main__":
    main()
