"""
Filename: tests/test_constraints.py
Description: Tests for constraint margins and feasibility aggregation
    (app/planning/constraints.py, docs/metrics.md section 4).
"""

import pytest

from app.metrics.core import MetricResult
from app.planning.constraints import (
    Constraint,
    evaluate_constraint,
    evaluate_constraints,
    feasibility_status,
)

DARKNESS_LIMIT = Constraint("max_continuous_darkness_hours", "<=", 24.0)
SUN_MINIMUM = Constraint("sun_visible_fraction", ">=", 0.6)


def result(value, coverage=1.0):
    return MetricResult(value=value, units="x", coverage=coverage)


def test_upper_limit_margin_and_pass():
    outcome = evaluate_constraint(DARKNESS_LIMIT, result(20.0))

    assert outcome.margin == 4.0
    assert outcome.passed is True


def test_upper_limit_fail_has_negative_margin():
    outcome = evaluate_constraint(DARKNESS_LIMIT, result(30.0))

    assert outcome.margin == -6.0
    assert outcome.passed is False


def test_lower_limit_margin_sign():
    assert evaluate_constraint(SUN_MINIMUM, result(0.7)).margin == pytest.approx(0.1)
    assert evaluate_constraint(SUN_MINIMUM, result(0.5)).passed is False


def test_exactly_at_limit_passes():
    assert evaluate_constraint(DARKNESS_LIMIT, result(24.0)).passed is True


def test_uncomputable_value_is_unknown():
    outcome = evaluate_constraint(DARKNESS_LIMIT, result(None, coverage=0.0))

    assert outcome.passed is None
    assert outcome.margin is None


def test_incomplete_coverage_is_unknown_but_keeps_margin():
    outcome = evaluate_constraint(DARKNESS_LIMIT, result(20.0, coverage=0.9))

    assert outcome.passed is None
    assert outcome.margin == 4.0
    assert "coverage" in outcome.reason


def test_constraint_on_uncomputed_metric_is_an_error():
    with pytest.raises(KeyError, match="max_continuous_darkness_hours"):
        evaluate_constraints({}, [DARKNESS_LIMIT])


def test_feasibility_aggregation():
    passing = evaluate_constraint(DARKNESS_LIMIT, result(20.0))
    failing = evaluate_constraint(DARKNESS_LIMIT, result(30.0))
    unknown = evaluate_constraint(DARKNESS_LIMIT, result(None, coverage=0.0))

    assert feasibility_status([passing, passing]) == "feasible"
    assert feasibility_status([passing, unknown]) == "unknown"
    assert feasibility_status([unknown, failing]) == "infeasible"
