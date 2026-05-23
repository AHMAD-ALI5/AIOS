# AIOS Evaluation Results

> **Status:** Results pending full benchmark execution.  
> This document will be populated after completing Phase 10–11 of the remediation plan.

## Planned Content

- Full benchmark table (TCR, RQS, MUE, ATL, WMS, Throughput) across all 3 domains
- Baseline comparison methodology
- Statistical significance analysis
- Per-domain breakdown
- Ablation study results

## Preliminary Notes

All evaluation runs require:
- `OPENAI_API_KEY` in `.env`
- Redis and ChromaDB running (`make docker-up`)
- At least 60 task files per domain in `data/tasks/`

To run the benchmark:
```bash
make eval-all
```

See `scripts/run_benchmark.py` for implementation details.
