"""
Filename: tests/test_sky_runtime.py
Description: Tests for the runtime sky module (app/astronomy/sky.py) on small
    synthetic grids: mission alignment/range rules and topocentric conversion.
    No SPICE or real grid file needed.
"""

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from app.astronomy.sky import (
    SkyGrid,
    SkyGridRangeError,
    format_utc,
    parse_utc,
    sky_track,
)
from app.coordinates.frames import LocalFrame
from app.metrics.core import EvaluationContext

HOUR = 3600
START = datetime(2030, 1, 1, tzinfo=UTC)


def synthetic_grid(n: int = 48, sun=None, earth=None) -> SkyGrid:
    sun = np.tile([1.5e11, 0.0, 0.0], (n, 1)) if sun is None else sun
    earth = np.tile([3.8e8, 0.0, 0.0], (n, 1)) if earth is None else earth
    return SkyGrid(utc_start=START, step_s=HOUR, sun_m=sun, earth_m=earth)


def test_indices_follow_sample_count_convention():
    grid = synthetic_grid()

    indices = grid.mission_indices(START + timedelta(hours=2), duration_s=6 * HOUR, step_s=2 * HOUR)

    np.testing.assert_array_equal(indices, [2, 4, 6, 8])
    context = EvaluationContext.from_window(6 * HOUR, 2 * HOUR)
    assert len(indices) == len(context.offsets_s)


def test_start_must_be_on_a_grid_hour():
    with pytest.raises(SkyGridRangeError, match="whole grid hour"):
        synthetic_grid().mission_indices(START + timedelta(minutes=30), 6 * HOUR, HOUR)


def test_step_must_be_whole_hours():
    with pytest.raises(SkyGridRangeError, match="multiple"):
        synthetic_grid().mission_indices(START, 6 * HOUR, 1800)


@pytest.mark.parametrize(
    "start, duration",
    [(START - timedelta(hours=1), 3 * HOUR), (START + timedelta(hours=40), 10 * HOUR)],
)
def test_mission_outside_grid_is_rejected(start, duration):
    with pytest.raises(SkyGridRangeError, match="within"):
        synthetic_grid().mission_indices(start, duration, HOUR)


def test_last_grid_sample_is_usable():
    grid = synthetic_grid(n=48)

    indices = grid.mission_indices(START, 47 * HOUR, HOUR)

    assert indices[-1] == 47
    assert grid.utc_end == START + timedelta(hours=47)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone"):
        synthetic_grid().mission_indices(datetime(2030, 1, 1), HOUR, HOUR)


def test_body_straight_above_site_is_at_zenith():
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))
    overhead = np.tile(frame.origin + 1e9 * frame.up, (48, 1))

    track = sky_track(synthetic_grid(sun=overhead), frame, START, 3 * HOUR, HOUR)

    np.testing.assert_allclose(track.sun_elevation, np.pi / 2, atol=1e-12)


def test_site_offset_is_subtracted_for_nearby_body():
    # Earth placed 384,400 km out along the site's horizontal north, measured
    # from the site: the topocentric elevation must be exactly zero, whereas
    # a center-based direction would show the ~0.26 degree parallax.
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))
    earth = np.tile(frame.origin + 3.844e8 * frame.north, (48, 1))

    track = sky_track(synthetic_grid(earth=earth), frame, START, 2 * HOUR, HOUR)

    np.testing.assert_allclose(track.earth_elevation, 0.0, atol=1e-12)
    np.testing.assert_allclose(track.earth_azimuth, 0.0, atol=1e-12)
    center_based_elevation = np.arctan2(earth[0] @ frame.up, earth[0] @ frame.north)
    assert np.degrees(center_based_elevation) == pytest.approx(0.259, abs=0.001)


def test_timestamps_are_utc_iso_strings():
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))

    track = sky_track(synthetic_grid(), frame, START + timedelta(hours=1), 2 * HOUR, HOUR)

    assert track.timestamps_utc == [
        "2030-01-01T01:00:00Z",
        "2030-01-01T02:00:00Z",
        "2030-01-01T03:00:00Z",
    ]


def test_utc_parse_and_format_round_trip():
    assert format_utc(parse_utc("2030-11-20T12:00:00Z")) == "2030-11-20T12:00:00Z"
    with pytest.raises(ValueError):
        parse_utc("2030-11-20T12:00:00")
