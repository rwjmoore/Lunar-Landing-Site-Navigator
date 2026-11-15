"""
Filename: app/metrics/visibility.py
Description: Generic metrics over a visibility series (VISIBLE / OBSTRUCTED /
    UNKNOWN per sample). Each class is instantiated once per body, e.g. for
    "sun_visible" and "earth_visible", so Sun and Earth share one implementation.

    Definitions: docs/metrics.md sections 3.2-3.4 (PENDING REVIEW).
"""

from dataclasses import dataclass

import numpy as np

from app.metrics.core import (
    OBSTRUCTED,
    UNKNOWN,
    VISIBLE,
    EvaluationContext,
    Interval,
    MetricResult,
    validate_visibility_states,
)

SECONDS_PER_HOUR = 3600.0
_NO_KNOWN_DATA = "no samples with known visibility in the mission window"


def _coverage(context: EvaluationContext, states: np.ndarray) -> tuple[float, float]:
    """Return (known seconds, coverage fraction) for a visibility series."""
    known_s = float(context.weights_s[states != UNKNOWN].sum())
    total_s = context.total_s
    return known_s, (known_s / total_s if total_s > 0 else 0.0)


@dataclass(frozen=True)
class VisibleFraction:
    """Fraction of known mission time during which the body is visible."""

    id: str
    label: str
    series: str
    units: str = "fraction"

    @property
    def requires(self) -> tuple[str, ...]:
        return (self.series,)

    def compute(self, context: EvaluationContext) -> MetricResult:
        states = context.require(self.series)
        validate_visibility_states(states, self.series)
        known_s, coverage = _coverage(context, states)
        if known_s == 0:
            return MetricResult(None, self.units, coverage, notes=(_NO_KNOWN_DATA,))

        visible_s = float(context.weights_s[states == VISIBLE].sum())
        notes = () if coverage == 1.0 else ("computed over known samples only",)
        return MetricResult(visible_s / known_s, self.units, coverage, notes=notes)


@dataclass(frozen=True)
class LongestOutage:
    """Longest continuous run of obstructed samples, in hours.

    Unknown samples break runs, so with incomplete coverage the true longest
    outage may be longer than reported. Ties resolve to the earliest run.
    """

    id: str
    label: str
    series: str
    units: str = "h"

    @property
    def requires(self) -> tuple[str, ...]:
        return (self.series,)

    def compute(self, context: EvaluationContext) -> MetricResult:
        states = context.require(self.series)
        validate_visibility_states(states, self.series)
        known_s, coverage = _coverage(context, states)
        if known_s == 0:
            return MetricResult(None, self.units, coverage, notes=(_NO_KNOWN_DATA,))

        notes = () if coverage == 1.0 else (
            "unknown samples break outage runs; the true longest outage may be longer",
        )

        # Find runs of OBSTRUCTED: +1 edges mark run starts, -1 edges mark one past run ends.
        blocked = (states == OBSTRUCTED).astype(np.int8)
        edges = np.diff(np.concatenate(([0], blocked, [0])))
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1) - 1  # inclusive
        if len(starts) == 0:
            return MetricResult(0.0, self.units, coverage, notes=notes)

        cumulative = np.concatenate(([0.0], np.cumsum(context.weights_s)))
        durations_s = cumulative[ends + 1] - cumulative[starts]
        worst = int(np.argmax(durations_s))  # argmax returns the first maximum
        start, end = int(starts[worst]), int(ends[worst])
        start_offset = float(context.offsets_s[start])
        interval = Interval(
            start_index=start,
            end_index=end,
            start_offset_s=start_offset,
            end_offset_s=start_offset + float(durations_s[worst]),
            boundary_truncated=start == 0 or end == len(states) - 1,
        )
        if interval.boundary_truncated:
            notes += ("worst outage touches the mission boundary and may extend beyond it",)
        return MetricResult(
            float(durations_s[worst]) / SECONDS_PER_HOUR, self.units, coverage, interval, notes
        )
