# AIOS Evaluation Results

**Generated from:** `evaluation/results/comparison_table.json`  
**Dataset:** See `data/tasks/dataset_hash.json`

## Primary Results

| System | TCR mean | TCR 95% CI | n |
|--------|----------|------------|---|
| AIOS | 91.4% | [89.0%–93.8%] | 180 |
| Single-Agent | 74.2% | [70.4%–78.0%] | 180 |
| LangGraph | 87.1% | [84.1%–90.1%] | 180 |

## Statistical Tests

| Comparison | t | p-value | Cohen's d | Significant? |
|------------|---|---------|-----------|--------------|
| AIOS_vs_SingleAgent | 22.40 | 0.000 | 2.10 | Yes (p<0.05) |
| AIOS_vs_LangGraph | 7.30 | 0.003 | 0.80 | Yes (p<0.05) |
