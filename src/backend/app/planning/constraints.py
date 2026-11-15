"""
Filename: app/planning/constraints.py
Description: Pass/fail mission constraints over metric results.

    A constraint refers to any metric by id, so every metric in the registry can
    become a mission requirement without changing this code.

    Rules: docs/metrics.md section 4 (PENDING REVIEW), notably that incomplete
    data coverage makes a constraint 'unknown' rather than passed or failed.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from app.metrics.core import MetricResult

Comparator = Literal["<=", ">="]
FeasibilityStatus = Literal["feasible", "infeasible", "unknown"]


@dataclass(frozen=True)
class Constraint:
    """Requirement `metric <comparator> limit`, with `limit` in the metric's units."""

    metric_id: str
    comparator: Comparator
    limit: float


@dataclass(frozen=True)
class ConstraintResult:
    """Outcome of one constraint.

    Attributes:
        value: The metric value checked (None if not computable).
        margin: Signed margin in the metric's units; positive means passing.
        passed: True / False, or None when the outcome is not certain.
        reason: Why the outcome is unknown, if it is.
    """

    constraint: Constraint
    value: float | None
    margin: float | None
    passed: bool | None
    reason: str | None = None


def evaluate_constraint(constraint: Constraint, result: MetricResult) -> ConstraintResult:
    """Check one constraint against its metric result."""
    if result.value is None:
        return ConstraintResult(constraint, None, None, None, "metric value not computable")

    if constraint.comparator == "<=":
        margin = constraint.limit - result.value
    elif constraint.comparator == ">=":
        margin = result.value - constraint.limit
    else:
        raise ValueError(f"unsupported comparator: {constraint.comparator!r}")

    if result.coverage < 1.0:
        return ConstraintResult(
            constraint, result.value, margin, None, "incomplete data coverage in mission window"
        )
    return ConstraintResult(constraint, result.value, margin, margin >= 0)


def evaluate_constraints(
    results: Mapping[str, MetricResult], constraints: Iterable[Constraint]
) -> list[ConstraintResult]:
    """Check every constraint. A constraint on an uncomputed metric is an error."""
    outcomes = []
    for constraint in constraints:
        if constraint.metric_id not in results:
            raise KeyError(f"constraint refers to uncomputed metric '{constraint.metric_id}'")
        outcomes.append(evaluate_constraint(constraint, results[constraint.metric_id]))
    return outcomes


def feasibility_status(outcomes: Iterable[ConstraintResult]) -> FeasibilityStatus:
    """Any failure -> infeasible; else any unknown -> unknown; else feasible."""
    passed = [o.passed for o in outcomes]
    if any(p is False for p in passed):
        return "infeasible"
    if any(p is None for p in passed):
        return "unknown"
    return "feasible"
