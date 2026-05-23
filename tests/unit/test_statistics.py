"""Unit tests for AIOS statistical analysis functions."""

from __future__ import annotations
import pytest
from evaluation.statistical_analysis import (
    MetricStats, welch_t_test, cohens_d, effect_size_label, compare_systems
)


class TestMetricStats:
    def test_single_value_no_ci(self):
        s = MetricStats("x", [0.9])
        assert s.mean == 0.9
        assert s.std == 0.0

    def test_three_values_ci(self):
        s = MetricStats("TCR", [0.91, 0.92, 0.90])
        assert abs(s.mean - 0.9100) < 1e-4
        assert s.ci_lower < s.mean < s.ci_upper

    def test_empty_values(self):
        s = MetricStats("x", [])
        assert s.mean == 0.0
        assert s.n == 0


class TestWelchTTest:
    def test_identical_groups_not_significant(self):
        a = [0.9, 0.9, 0.9]
        b = [0.9, 0.9, 0.9]
        t, p = welch_t_test(a, b)
        assert p > 0.05

    def test_clearly_different_groups(self):
        a = [0.91, 0.92, 0.90]
        b = [0.74, 0.75, 0.73]
        t, p = welch_t_test(a, b)
        assert t > 0
        assert p <= 0.05


class TestCohensD:
    def test_no_difference(self):
        d = cohens_d([1.0, 1.0, 1.0], [1.0, 1.0, 1.0])
        assert d == 0.0

    def test_large_effect(self):
        d = cohens_d([0.91, 0.92, 0.90], [0.74, 0.75, 0.73])
        assert abs(d) > 0.8  # large effect
        assert effect_size_label(d) == "large"
