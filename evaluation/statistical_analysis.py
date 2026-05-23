"""
AIOS Statistical Analysis
Confidence intervals, significance tests, and effect sizes for benchmark results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MetricStats:
    """Summary statistics for a single metric across seeds."""
    name: str
    values: list[float]
    mean: float = 0.0
    std: float = 0.0
    ci_lower: float = 0.0    # 95% CI lower bound
    ci_upper: float = 0.0    # 95% CI upper bound
    n: int = 0

    def __post_init__(self):
        self.n = len(self.values)
        if self.n > 0:
            self.mean = sum(self.values) / self.n
        if self.n > 1:
            variance = sum((x - self.mean) ** 2 for x in self.values) / (self.n - 1)
            self.std = math.sqrt(variance)
            # 95% CI using t-distribution (t critical values for small n)
            t_crit = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571,
                      6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228}
            t = t_crit.get(self.n - 1, 1.960)  # fallback to z=1.96
            margin = t * (self.std / math.sqrt(self.n))
            self.ci_lower = self.mean - margin
            self.ci_upper = self.mean + margin

    def format(self) -> str:
        if self.n <= 1:
            return f"{self.mean:.3f} (n=1, no CI)"
        return (f"{self.mean:.3f} ± {self.std:.3f} "
                f"[95% CI: {self.ci_lower:.3f}–{self.ci_upper:.3f}] "
                f"(n={self.n})")


def welch_t_test(a: list[float], b: list[float]) -> tuple[float, float]:
    """
    Welch's t-test (unequal variance) for two independent samples.
    Returns (t_statistic, p_value_approx).
    Uses conservative df approximation.
    """
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0, 1.0
    mean_a = sum(a) / na
    mean_b = sum(b) / nb
    var_a = sum((x - mean_a) ** 2 for x in a) / (na - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(var_a / na + var_b / nb)
    if se == 0:
        return 0.0, 1.0
    t = (mean_a - mean_b) / se
    # Welch-Satterthwaite df
    df_num = (var_a / na + var_b / nb) ** 2
    df_den = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    df = df_num / df_den if df_den > 0 else min(na, nb) - 1
    # Approximate two-tailed p-value (conservative)
    abs_t = abs(t)
    # Simple approximation using t-table lookup
    t_table = {1: (6.314, 12.706), 2: (2.920, 4.303), 3: (2.353, 3.182),
               4: (2.132, 2.776), 5: (2.015, 2.571), 10: (1.812, 2.228),
               20: (1.725, 2.086), 30: (1.697, 2.042), 60: (1.671, 2.000)}
    df_key = min(t_table.keys(), key=lambda k: abs(k - df))
    t05, t01 = t_table[df_key]
    if abs_t > t01:
        p_approx = 0.01
    elif abs_t > t05:
        p_approx = 0.05
    else:
        p_approx = 0.10
    return t, p_approx


def cohens_d(a: list[float], b: list[float]) -> float:
    """Cohen's d effect size between two groups."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return 0.0
    mean_a = sum(a) / na
    mean_b = sum(b) / nb
    var_a = sum((x - mean_a) ** 2 for x in a) / (na - 1)
    var_b = sum((x - mean_b) ** 2 for x in b) / (nb - 1)
    pooled_std = math.sqrt(((na - 1) * var_a + (nb - 1) * var_b) / (na + nb - 2))
    return (mean_a - mean_b) / pooled_std if pooled_std > 0 else 0.0


def effect_size_label(d: float) -> str:
    """Cohen's d interpretation."""
    d = abs(d)
    if d < 0.2: return "negligible"
    if d < 0.5: return "small"
    if d < 0.8: return "medium"
    return "large"


@dataclass
class ComparisonReport:
    """Statistical comparison between two systems on a metric."""
    metric: str
    system_a: str
    system_b: str
    stats_a: MetricStats = field(default_factory=lambda: MetricStats("", []))
    stats_b: MetricStats = field(default_factory=lambda: MetricStats("", []))
    t_statistic: float = 0.0
    p_value: float = 1.0
    cohens_d: float = 0.0
    significant_at_05: bool = False

    def summary(self) -> str:
        sig = "✓ p<0.05" if self.significant_at_05 else "✗ not significant"
        effect = effect_size_label(self.cohens_d)
        return (
            f"{self.metric}: {self.system_a}={self.stats_a.format()} vs "
            f"{self.system_b}={self.stats_b.format()} | "
            f"d={self.cohens_d:.2f} ({effect}) | {sig}"
        )


def compare_systems(
    metric_name: str,
    system_a_name: str,
    system_a_values: list[float],
    system_b_name: str,
    system_b_values: list[float],
) -> ComparisonReport:
    """Run full statistical comparison between two systems on one metric."""
    stats_a = MetricStats(metric_name, system_a_values)
    stats_b = MetricStats(metric_name, system_b_values)
    t, p = welch_t_test(system_a_values, system_b_values)
    d = cohens_d(system_a_values, system_b_values)
    return ComparisonReport(
        metric=metric_name,
        system_a=system_a_name,
        system_b=system_b_name,
        stats_a=stats_a,
        stats_b=stats_b,
        t_statistic=t,
        p_value=p,
        cohens_d=d,
        significant_at_05=(p <= 0.05),
    )
