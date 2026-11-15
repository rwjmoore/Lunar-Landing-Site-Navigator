"""
Filename: tests/test_metrics_core.py
Description: Tests for the metric framework's time grid and metric runner
    (app/metrics/core.py, docs/metrics.md section 3.1).
"""

import numpy as np
import pytest

from app.metrics.core import EvaluationContext, compute_metrics
from app.metrics.registry import DEFAULT_METRICS
from app.metrics.visibility import VisibleFraction

HOUR = 3600.0


def test_grid_with_exact_multiple_has_zero_weight_final_sample():
    context = EvaluationContext.from_window(duration_s=3 * HOUR, step_s=HOUR)

    np.testing.assert_array_equal(context.offsets_s, [0, HOUR, 2 * HOUR, 3 * HOUR])
    np.testing.assert_array_equal(context.weights_s, [HOUR, HOUR, HOUR, 0])
    assert context.total_s == 3 * HOUR


def test_grid_truncates_final_sample_at_mission_end():
    context = EvaluationContext.from_window(duration_s=2.5 * HOUR, step_s=HOUR)

    np.testing.assert_array_equal(context.weights_s, [HOUR, HOUR, 0.5 * HOUR])
    assert context.total_s == 2.5 * HOUR


@pytest.mark.parametrize("duration, step", [(0, HOUR), (HOUR, 0), (-HOUR, HOUR)])
def test_grid_rejects_nonpositive_inputs(duration, step):
    with pytest.raises(ValueError):
        EvaluationContext.from_window(duration, step)


def test_series_length_must_match_grid():
    with pytest.raises(ValueError, match="sun_visible"):
        EvaluationContext.from_window(3 * HOUR, HOUR, {"sun_visible": np.ones(2, np.int8)})


def test_missing_required_series_fails_before_computing():
    context = EvaluationContext.from_window(3 * HOUR, HOUR, {"sun_visible": np.ones(4, np.int8)})

    with pytest.raises(KeyError, match="earth_visible"):
        compute_metrics(context, DEFAULT_METRICS)


def test_duplicate_metric_ids_are_rejected():
    context = EvaluationContext.from_window(3 * HOUR, HOUR, {"s": np.ones(4, np.int8)})
    metric = VisibleFraction("same_id", "A", series="s")

    with pytest.raises(ValueError, match="same_id"):
        compute_metrics(context, [metric, metric])


def test_default_registry_ids_match_api_metric_fields():
    from app.api.schemas import Metrics

    assert {m.id for m in DEFAULT_METRICS} == set(Metrics.model_fields)
