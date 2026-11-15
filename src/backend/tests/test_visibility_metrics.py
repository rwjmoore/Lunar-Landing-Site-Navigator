"""
Filename: tests/test_visibility_metrics.py
Description: Tests for VisibleFraction and LongestOutage on hand-built
    visibility series (docs/metrics.md sections 3.2-3.4). All cases use hourly
    samples, so N samples with an exact-multiple duration have N-1 hours of time.
"""

import numpy as np
import pytest

from app.metrics.core import OBSTRUCTED as O
from app.metrics.core import UNKNOWN as U
from app.metrics.core import VISIBLE as V
from app.metrics.core import EvaluationContext
from app.metrics.visibility import LongestOutage, VisibleFraction

HOUR = 3600.0
FRACTION = VisibleFraction("f", "Fraction", series="s")
OUTAGE = LongestOutage("o", "Outage", series="s")


def context_for(states: list[int]) -> EvaluationContext:
    """Hourly grid whose duration gives exactly len(states) samples."""
    series = {"s": np.array(states, dtype=np.int8)}
    return EvaluationContext.from_window((len(states) - 1) * HOUR, HOUR, series)


def test_always_visible():
    context = context_for([V, V, V, V, V])

    assert FRACTION.compute(context).value == 1.0
    result = OUTAGE.compute(context)
    assert result.value == 0.0
    assert result.worst_interval is None


def test_never_visible_is_one_boundary_truncated_outage():
    context = context_for([O, O, O, O, O])

    assert FRACTION.compute(context).value == 0.0
    result = OUTAGE.compute(context)
    assert result.value == 4.0  # final sample has zero weight
    assert result.worst_interval.boundary_truncated


def test_interior_outage_duration_and_location():
    # Samples 0..6; obstructed at 2, 3, 4 -> 3 hours starting at hour 2.
    context = context_for([V, V, O, O, O, V, V])

    result = OUTAGE.compute(context)
    assert result.value == 3.0
    interval = result.worst_interval
    assert (interval.start_index, interval.end_index) == (2, 4)
    assert (interval.start_offset_s, interval.end_offset_s) == (2 * HOUR, 5 * HOUR)
    assert not interval.boundary_truncated
    assert result.notes == ()
    assert FRACTION.compute(context).value == pytest.approx(3 / 6)


def test_longest_of_several_outages_wins_and_ties_pick_earliest():
    longest = OUTAGE.compute(context_for([V, O, V, O, O, V, V]))
    assert longest.value == 2.0
    assert longest.worst_interval.start_index == 3

    tie = OUTAGE.compute(context_for([V, O, O, V, O, O, V]))
    assert tie.worst_interval.start_index == 1


def test_unknown_is_excluded_from_fraction_and_reported_as_coverage():
    # 6 hours: 2 visible, 1 obstructed, 3 unknown (sample 6 has zero weight).
    context = context_for([V, V, O, U, U, U, V])

    result = FRACTION.compute(context)
    assert result.value == pytest.approx(2 / 3)
    assert result.coverage == pytest.approx(3 / 6)
    assert result.notes


def test_unknown_breaks_outage_runs():
    result = OUTAGE.compute(context_for([V, O, O, U, O, O, V]))

    assert result.value == 2.0
    assert result.coverage < 1.0
    assert any("may be longer" in note for note in result.notes)


def test_all_unknown_gives_no_value():
    context = context_for([U, U, U])

    assert FRACTION.compute(context).value is None
    assert OUTAGE.compute(context).value is None


def test_invalid_state_values_are_rejected():
    context = context_for([V, 2, V])

    with pytest.raises(ValueError):
        FRACTION.compute(context)
