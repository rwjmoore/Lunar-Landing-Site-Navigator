"""
Filename: app/metrics/core.py
Description: Core types of the reusable metric framework.

    A metric reads named time series from an EvaluationContext and returns a
    MetricResult. Metrics never compute physics; the physics layer produces the
    series (e.g. sun_visible) and places them in the context.

    Definitions and review status: docs/metrics.md.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

# Visibility states stored in visibility series (int8 arrays).
VISIBLE = 1
OBSTRUCTED = 0
UNKNOWN = -1
_VALID_STATES = (VISIBLE, OBSTRUCTED, UNKNOWN)


@dataclass(frozen=True)
class EvaluationContext:
    """Mission time grid plus the named time series that metrics read.

    Attributes:
        offsets_s: Sample times in seconds from mission start, shape (N,).
        weights_s: Seconds of mission time each sample represents, shape (N,).
            See docs/metrics.md section 3.1 for how these are derived.
        series: Name -> 1-D array of length N (e.g. "sun_visible").
    """

    offsets_s: np.ndarray
    weights_s: np.ndarray
    series: Mapping[str, np.ndarray] = field(default_factory=dict)

    def __post_init__(self) -> None:
        n = len(self.offsets_s)
        if len(self.weights_s) != n:
            raise ValueError("offsets_s and weights_s must have the same length")
        for name, values in self.series.items():
            if np.ndim(values) != 1 or len(values) != n:
                raise ValueError(f"series '{name}' must be 1-D with {n} samples")

    @classmethod
    def from_window(
        cls, duration_s: float, step_s: float, series: Mapping[str, np.ndarray] | None = None
    ) -> "EvaluationContext":
        """Build the sample grid for a mission of `duration_s` sampled every `step_s`.

        N = floor(duration / step) + 1 samples at k * step. Each sample covers
        [t_k, t_k + step), truncated at mission end (SCIENCE_CONVENTIONS.md section 2).
        """
        if duration_s <= 0 or step_s <= 0:
            raise ValueError("duration_s and step_s must be positive")
        n = int(np.floor(duration_s / step_s)) + 1
        offsets = np.arange(n, dtype=np.float64) * step_s
        weights = np.clip(duration_s - offsets, 0.0, step_s)
        return cls(offsets_s=offsets, weights_s=weights, series=dict(series or {}))

    @property
    def total_s(self) -> float:
        """Total mission time represented by the samples, in seconds."""
        return float(self.weights_s.sum())

    def require(self, name: str) -> np.ndarray:
        """Return series `name`, raising KeyError with a clear message if absent."""
        try:
            return self.series[name]
        except KeyError:
            raise KeyError(f"series '{name}' is not in the evaluation context") from None


@dataclass(frozen=True)
class Interval:
    """A contiguous run of samples, e.g. the worst outage.

    Indices are inclusive. `end_offset_s` is the end of the last sample's
    weighted interval. `boundary_truncated` is True if the run touches the
    first or last sample, so it may extend beyond the mission window.
    """

    start_index: int
    end_index: int
    start_offset_s: float
    end_offset_s: float
    boundary_truncated: bool


@dataclass(frozen=True)
class MetricResult:
    """Output of one metric.

    Attributes:
        value: The metric value in `units`, or None if it cannot be computed.
        units: Units of `value` (e.g. "fraction", "h").
        coverage: Fraction of mission time whose input data was known, in [0, 1].
        worst_interval: The interval responsible for the value, if meaningful.
        notes: Human-readable caveats (e.g. incomplete coverage).
    """

    value: float | None
    units: str
    coverage: float
    worst_interval: Interval | None = None
    notes: tuple[str, ...] = ()


class Metric(Protocol):
    """Interface every metric implements. See docs/metrics.md, 'Adding a metric'."""

    id: str
    label: str
    units: str

    @property
    def requires(self) -> tuple[str, ...]:
        """Names of the series this metric reads."""
        ...

    def compute(self, context: EvaluationContext) -> MetricResult:
        """Compute the metric from the context's series."""
        ...


def compute_metrics(
    context: EvaluationContext, metrics: Iterable[Metric]
) -> dict[str, MetricResult]:
    """Run each metric and return results keyed by metric id.

    Fails before computing anything if ids are duplicated or required series
    are missing, so a misconfigured registry never yields partial results.
    """
    metrics = tuple(metrics)
    ids = [m.id for m in metrics]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate metric ids: {duplicates}")

    missing = sorted({s for m in metrics for s in m.requires if s not in context.series})
    if missing:
        raise KeyError(f"evaluation context is missing required series: {missing}")

    return {m.id: m.compute(context) for m in metrics}


def validate_visibility_states(values: np.ndarray, name: str) -> None:
    """Raise ValueError if a visibility series holds anything but VISIBLE/OBSTRUCTED/UNKNOWN."""
    if not np.isin(values, _VALID_STATES).all():
        raise ValueError(f"series '{name}' must contain only {_VALID_STATES}")
