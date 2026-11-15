"""
Filename: tests/test_contract.py
Description: Keeps the Pydantic models and the frontend/backend JSON contract
    (docs/frontend-backend_interface.json) in sync, and checks that the models
    reject malformed results.
"""

import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.api.schemas import AnalyzeResponse

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = REPO_ROOT / "docs" / "frontend-backend_interface.json"


@pytest.fixture
def fixture_json() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_fixture_validates_against_models(fixture_json):
    AnalyzeResponse.model_validate(fixture_json)


def test_models_round_trip_fixture_exactly(fixture_json):
    """Serializing the parsed fixture must reproduce it: no fields added or dropped."""
    parsed = AnalyzeResponse.model_validate(fixture_json)

    assert parsed.model_dump(mode="json") == fixture_json


def test_unknown_field_is_rejected(fixture_json):
    bad = copy.deepcopy(fixture_json)
    bad["candidate"]["metrics"]["made_up_metric"] = 1.0

    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate(bad)


def test_series_arrays_must_have_equal_length(fixture_json):
    bad = copy.deepcopy(fixture_json)
    series = bad["candidate"]["series"]
    series["timestamps_utc"] = ["2030-11-20T12:00:00Z", "2030-11-20T13:00:00Z"]
    for name in series:
        if name != "timestamps_utc":
            series[name] = [False] if name.endswith("visible") else [0.0]

    with pytest.raises(ValidationError, match="equal length"):
        AnalyzeResponse.model_validate(bad)


def test_horizon_arrays_must_have_equal_length(fixture_json):
    bad = copy.deepcopy(fixture_json)
    bad["candidate"]["horizons"]["azimuth_deg"] = [0.0, 0.25]

    with pytest.raises(ValidationError, match="equal length"):
        AnalyzeResponse.model_validate(bad)


@pytest.mark.parametrize(
    "path, value",
    [
        (("vehicle", "solar_panel_mast_height_m"), -1.0),
        (("location", "latitude_deg"), -91.0),
        (("metrics", "sun_visible_fraction"), 1.5),
        (("feasibility", "status"), "maybe"),
    ],
)
def test_out_of_range_values_are_rejected(fixture_json, path, value):
    bad = copy.deepcopy(fixture_json)
    section, field = path
    bad["candidate"][section][field] = value

    with pytest.raises(ValidationError):
        AnalyzeResponse.model_validate(bad)
