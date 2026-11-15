"""
Filename: tests/test_sky_spice.py
Description: Validation of the real sky grid against SPICE (docs/physics/sky.md
    section 7, checks 1, 3 and 4). Skipped automatically when SpiceyPy, the
    kernels in data/kernels/ or the grid file are not available, so the
    runtime-only test environment still passes.
"""

from datetime import timedelta

import numpy as np
import pytest

spiceypy = pytest.importorskip("spiceypy")

from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, format_utc, sky_track  # noqa: E402
from app.coordinates.frames import LocalFrame, site_to_position  # noqa: E402
from pipeline.spice_kernels import kernels_available, load_kernels  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (kernels_available() and DEFAULT_SKY_GRID_PATH.exists()),
    reason="SPICE kernels or sky grid not present",
)

TEST_SITES_DEG = [(-89.5, 300.0), (-85.0, 10.0), (-89.9, 123.4)]
METHOD_TOLERANCE_DEG = 0.001  # approved in docs/physics/sky.md section 9
HOUR = 3600
AU_M = 1.495978707e11


@pytest.fixture(scope="module")
def grid() -> SkyGrid:
    load_kernels()
    return SkyGrid.load()


def separation_deg(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Angle between direction vectors, in degrees (robust for any geometry)."""
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1)))


def spice_topocentric(target: str, et: float, site_m: np.ndarray) -> np.ndarray:
    """Apparent position of `target` from a site fixed in MOON_ME, computed by SPICE (metres)."""
    state, _ = spiceypy.spkcpo(
        target, et, "MOON_ME", "OBSERVER", "LT+S", site_m / 1000.0, "MOON", "MOON_ME"
    )
    return np.asarray(state[:3]) * 1000.0


def test_grid_integrity(grid):
    assert grid.size == 131_496
    assert grid.sun_m.shape == grid.earth_m.shape == (grid.size, 3)
    assert format_utc(grid.utc_start) == "2026-01-01T00:00:00Z"
    assert format_utc(grid.utc_end) == "2040-12-31T23:00:00Z"
    with np.load(DEFAULT_SKY_GRID_PATH) as data:
        et = data["et_tdb_s"]
    # Consecutive whole UTC hours differ by 3600 s of TDB, up to the ~ms periodic TDB-TT term.
    assert np.max(np.abs(np.diff(et) - HOUR)) < 0.01
    # Spot-check: the stored times are exactly the UTC grid.
    assert et[0] == pytest.approx(spiceypy.str2et("2026-01-01T00:00:00"), abs=1e-6)


@pytest.mark.parametrize("lat, lon", TEST_SITES_DEG)
@pytest.mark.parametrize("target, column", [("SUN", "sun_m"), ("EARTH", "earth_m")])
def test_grid_method_matches_spice_at_site(grid, lat, lon, target, column):
    """Check 1: center grid minus site position == SPICE computed from the site."""
    site_m = site_to_position(np.radians(lat), np.radians(lon), 0.0)
    rng = np.random.default_rng(seed=421)
    indices = rng.choice(grid.size, size=200, replace=False)
    with np.load(DEFAULT_SKY_GRID_PATH) as data:
        et = data["et_tdb_s"][indices]

    ours = getattr(grid, column)[indices] - site_m
    spice = np.array([spice_topocentric(target, t, site_m) for t in et])

    assert np.max(separation_deg(ours, spice)) < METHOD_TOLERANCE_DEG


@pytest.fixture(scope="module")
def year_track(grid):
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))
    start = grid.utc_start + timedelta(days=365 * 4)  # 2029-12-31
    return sky_track(grid, frame, start, duration_s=365 * 86400, step_s=HOUR)


def test_sun_elevation_stays_near_horizon_at_pole(year_track):
    elevation = np.degrees(year_track.sun_elevation)
    assert elevation.max() < 2.1
    assert elevation.min() > -2.1


def test_sun_azimuth_circles_once_per_synodic_month(year_track):
    turns = np.ptp(np.unwrap(year_track.sun_azimuth)) / (2 * np.pi)
    assert turns == pytest.approx(365 / 29.53, abs=0.5)


def test_earth_stays_near_horizon_and_does_not_circle(year_track):
    elevation = np.degrees(year_track.earth_elevation)
    assert np.abs(elevation).max() < 8.0
    azimuth_span_deg = np.degrees(np.ptp(np.unwrap(year_track.earth_azimuth)))
    assert azimuth_span_deg < 90.0


def test_distances_are_physical(grid):
    sun_au = np.linalg.norm(grid.sun_m, axis=1) / AU_M
    earth_km = np.linalg.norm(grid.earth_m, axis=1) / 1000.0
    assert 0.97 < sun_au.min() and sun_au.max() < 1.03
    assert 356_000 < earth_km.min() and earth_km.max() < 407_500
