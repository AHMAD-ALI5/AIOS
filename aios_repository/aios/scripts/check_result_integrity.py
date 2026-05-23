#!/usr/bin/env python3
"""Verify committed evaluation result files contain required metadata fields."""

import json
import sys
from pathlib import Path

REQUIRED_METADATA = ["seeds"]
REQUIRED_RESULT_FIELDS = ["domain"]

def check():
    results_dir = Path("evaluation/results")
    if not results_dir.exists():
        print("evaluation/results/ directory missing")
        sys.exit(1)
    
    json_files = list(results_dir.glob("*.json"))
    if not json_files:
        print("No result JSON files found — run make eval-all first")
        # Not a failure in CI until first eval run is committed
        sys.exit(0)
    
    errors = []
    for f in json_files:
        if f.name == ".gitkeep":
            continue
        try:
            data = json.load(open(f))
        except json.JSONDecodeError as e:
            errors.append(f"{f}: Invalid JSON — {e}")
            continue
        
        # Skip checking the comparison_table.json because it has a different structure
        if f.name == "comparison_table.json":
            continue
            
        meta = data.get("metadata", {})
        for field in REQUIRED_METADATA:
            if field not in meta:
                errors.append(f"{f}: Missing metadata.{field}")
        
        # Assuming aggregated_results are not always present if per_seed_results is used
        # We will check per_seed_results instead.
        for seed_results in data.get("per_seed_results", {}).values():
            for result in seed_results:
                for field in REQUIRED_RESULT_FIELDS:
                    if field not in result:
                        errors.append(f"{f}: Missing per_seed_results[].{field}")
    
    if errors:
        print(f"ERROR: {len(errors)} integrity errors:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print(f"OK: All {len(json_files)} result file(s) pass integrity check")

if __name__ == "__main__":
    check()
