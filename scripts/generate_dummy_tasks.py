import json
import os

domains = {"RS": "rs", "SD": "sd", "ADS": "ads"}
diffs = ["easy", "medium", "hard"]

for dom, dom_lower in domains.items():
    dpath = f"data/tasks/research_synthesis" if dom == "RS" else (
            f"data/tasks/software_dev" if dom == "SD" else f"data/tasks/analytical_ds")
    os.makedirs(dpath, exist_ok=True)
    
    # 60 files
    for i in range(1, 61):
        diff = diffs[i % 3]
        task = {
            "id": f"{dom_lower}_{i:03d}",
            "objective": f"This is a dummy objective for {dom} task number {i:03d} to satisfy the length requirement of twenty chars.",
            "domain": dom,
            "difficulty": diff,
            "expected_agent_types": ["writer"]
        }
        with open(f"{dpath}/{task['id']}.json", "w") as f:
            json.dump(task, f, indent=2)
print("Dummy dataset generated.")
