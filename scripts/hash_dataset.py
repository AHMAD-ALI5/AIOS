#!/usr/bin/env python3
"""Generate SHA256 hash of the complete task dataset for integrity verification."""

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def main():
    task_dirs = [
        "data/tasks/research_synthesis",
        "data/tasks/software_dev",
        "data/tasks/analytical_ds",
    ]
    h = hashlib.sha256()
    total = 0
    for d in sorted(task_dirs):
        for f in sorted(Path(d).glob("*.json")):
            h.update(f.read_bytes())
            total += 1
    
    digest = h.hexdigest()
    print(f"Dataset hash (SHA256): {digest}")
    print(f"Total files: {total}")
    
    with open("data/tasks/dataset_hash.json", "w") as f:
        json.dump({"sha256": digest, "n_files": total}, f, indent=2)
    print("Saved to data/tasks/dataset_hash.json")

if __name__ == "__main__":
    main()
