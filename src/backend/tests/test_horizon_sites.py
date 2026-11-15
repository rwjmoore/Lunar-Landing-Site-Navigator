"""
Filename: tests/test_horizon_sites.py
Description: Consistency checks of the horizon and analysis on the real sites
    (docs/physics/horizon.md section 9, real-sites table) with the approved
    tolerances. Uses every 10th azimuth (144 directions) for speed; the full
    1,440-direction numbers are produced by pipeline/horizon_evidence.py.
    Skipped automatically when terrain artifacts or the sky grid are missing.
"""

import numpy as np
import pytest

from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, parse_utc
from app.physics.analysis import MissionWindow, Vehicle, analyze
from app.physics.horizon import (
    AZIMUTHS_RAD,
    FAR_STEP_M,
    HORIZON_DIR,
    MAX_RANGE_M,
    NEAR_RELATIVE_STEP,
    NEAR_STEP_M,
    SITES_PATH,
    TERRAIN_DIR,
    SiteTerrain,
    cast_rays,
    load_sites,
    near_distances,
    uniform_distances,
)
from app.planning.constraints import Constraint
from app.terrain.grid import TerrainGrid

REGION_DIR = TERRAIN_DIR / "region_80s_40m"
pytestmark = pytest.mark.skipif(
    not (SITES_PATH.exists() and (REGION_DIR / "heights.npy").exists()
         and HORIZON_DIR.exists() and DEFAULT_SKY_GRID_PATH.exists()),
    reason="terrain artifacts, far horizons or sky grid not present",
)
SUBSET = AZIMUTHS_RAD[::10]
FAR_POINT_TOL_DEG = 0.01   # approved, horizon.md section 9
BOUNDARY_TOL_DEG = 0.05
STEP_TOL_DEG = 0.015  # approved 2026-11-14 (was 0.01; worst on all directions 0.0124)
SITE_IDS = ["site01", "site04", "site07", "site11"]


@pytest.fixture(scope="module")
def region():
    return TerrainGrid.load(REGION_DIR)


@pytest.fixture(scope="module")
def terrains():
    return {sid: SiteTerrain.load(site) for sid, site in load_sites().items()}


def horizon_subset(site, near_grid, far_grid, h_obs, boundary_m, refine=1.0):
    """Horizon over SUBSET with every zone cast directly (no stored far points).
    `refine` > 1 divides every step size by that factor."""
    frame = site.frame(h_obs)
    near = cast_rays(frame, near_grid,
                     near_distances(boundary_m, NEAR_STEP_M / refine, NEAR_RELATIVE_STEP / refine), SUBSET)
    far = cast_rays(frame, far_grid, uniform_distances(boundary_m, MAX_RANGE_M, FAR_STEP_M / refine), SUBSET)
    return np.maximum(near.elevation_rad, far.elevation_rad)


@pytest.mark.parametrize("site_id", SITE_IDS)
@pytest.mark.parametrize("h_obs", [0.0, 2.0, 7.5, 12.0, 20.0])
def test_stored_far_points_match_full_far_recompute(terrains, region, site_id, h_obs):
    t = terrains[site_id]
    profile = t.horizon(h_obs)
    direct = horizon_subset(t.site, t.near_grid, region, h_obs, t.site.near_field_radius_m)
    worst = np.degrees(np.max(np.abs(profile.elevation_rad[::10] - direct)))
    assert worst <= FAR_POINT_TOL_DEG


@pytest.mark.parametrize("site_id", SITE_IDS)
def test_moving_the_near_far_boundary(terrains, region, site_id):
    t = terrains[site_id]
    standard = t.horizon(2.0).elevation_rad[::10]
    moved = horizon_subset(t.site, t.near_grid, region, 2.0, 4000.0)
    assert np.degrees(np.max(np.abs(standard - moved))) <= BOUNDARY_TOL_DEG


@pytest.mark.parametrize("site_id", SITE_IDS)
def test_halving_the_step_size(terrains, region, site_id):
    t = terrains[site_id]
    r = t.site.near_field_radius_m
    standard = horizon_subset(t.site, t.near_grid, region, 2.0, r)
    finer = horizon_subset(t.site, t.near_grid, region, 2.0, r, refine=2.0)
    assert np.degrees(np.max(np.abs(standard - finer))) <= STEP_TOL_DEG


@pytest.fixture(scope="module")
def sky():
    return SkyGrid.load()


WINDOW = MissionWindow(parse_utc("2030-01-01T00:00:00Z"), 60 * 86400, 3600)
CONSTRAINTS = [Constraint("max_continuous_darkness_hours", "<=", 100.0)]


def test_solar_mast_change_leaves_earth_unchanged(terrains, sky):
    t = terrains["site04"]
    low = analyze(t, sky, WINDOW, Vehicle(2.0, 2.0), CONSTRAINTS)
    high = analyze(t, sky, WINDOW, Vehicle(15.0, 2.0), CONSTRAINTS)
    np.testing.assert_array_equal(low.earth_visible, high.earth_visible)
    np.testing.assert_array_equal(low.earth_horizon.elevation_rad, high.earth_horizon.elevation_rad)
    assert (high.metrics["sun_visible_fraction"].value
            >= low.metrics["sun_visible_fraction"].value)


def test_analysis_is_reproducible(terrains, sky):
    t = terrains["site01"]
    a = analyze(t, sky, WINDOW, Vehicle(3.0, 1.0), CONSTRAINTS)
    fresh = SiteTerrain.load(t.site)  # no cache
    b = analyze(fresh, sky, WINDOW, Vehicle(3.0, 1.0), CONSTRAINTS)
    np.testing.assert_array_equal(a.sun_visible, b.sun_visible)
    np.testing.assert_array_equal(a.sun_horizon.elevation_rad, b.sun_horizon.elevation_rad)
    assert {k: v.value for k, v in a.metrics.items()} == {k: v.value for k, v in b.metrics.items()}


def test_observer_height_outside_approved_range_is_rejected(terrains):
    with pytest.raises(ValueError, match="0-20"):
        terrains["site01"].horizon(25.0)
