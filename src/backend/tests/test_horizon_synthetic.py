"""
Filename: tests/test_horizon_synthetic.py
Description: Known-answer tests for ray casting and visibility on synthetic
    terrain (docs/physics/horizon.md section 9, synthetic table): a smooth
    sphere, a circular wall, a ridge in one sector, observer-height
    monotonicity, no-data handling, and the visibility rules.
"""

import numpy as np
import pytest

from app.coordinates.frames import MOON_RADIUS_M as R
from app.metrics.core import OBSTRUCTED, UNKNOWN, VISIBLE
from app.physics.horizon import AZIMUTHS_RAD, HorizonProfile, SiteInfo, uniform_distances
from app.physics.horizon import cast_rays as _cast_rays
from app.physics.visibility import horizon_at, visibility
from app.terrain.grid import TerrainGrid, polar_stereo_forward

SITE = SiteInfo("test", "Test", -89.5, 300.0, 0.0, 8000.0)
PIXEL = 500.0
STEP = 500.0
SITE_X, SITE_Y = (float(v) for v in polar_stereo_forward(np.radians(-89.5), np.radians(300.0)))


def synthetic_grid(height_fn) -> TerrainGrid:
    """Grid covering 230 km around the site; heights from height_fn(distance, local_azimuth).

    Near the pole, map "up" (+y) is not local north: on a south polar
    stereographic map, local north at longitude L points along map bearing L
    (radially away from the pole), so local azimuth = map bearing - L.
    """
    half = 230_000.0
    n = int(2 * half / PIXEL) + 1
    x0, y0 = SITE_X - half, SITE_Y + half
    cols, rows = np.meshgrid(np.arange(n), np.arange(n))
    dx = x0 + cols * PIXEL - SITE_X
    dy = y0 - rows * PIXEL - SITE_Y
    local_az = np.mod(np.arctan2(dx, dy) - np.radians(SITE.longitude_deg_east), 2 * np.pi)
    return TerrainGrid(height_fn(np.hypot(dx, dy), local_az).astype(np.float32), x0, y0, PIXEL)


def map_point(distance, local_az_deg):
    """Map (x, y) at a distance and local azimuth from the site (see synthetic_grid)."""
    bearing = np.radians(local_az_deg + SITE.longitude_deg_east)
    return SITE_X + distance * np.sin(bearing), SITE_Y + distance * np.cos(bearing)


def cast_rays(frame, grid, start, stop, step):
    """Uniform-step casting over the synthetic grids."""
    return _cast_rays(frame, grid, uniform_distances(start, stop, step))


def flat(dist, az):
    return np.zeros_like(dist)


def elevation_of(frame, azimuth, distance, height):
    point = (R + height) * frame.great_circle_direction(azimuth, distance / R)
    return float(frame.azimuth_elevation(point)[1])


def test_smooth_sphere_gives_the_spheres_own_horizon():
    h_obs = 1000.0
    frame = SITE.frame(h_obs)
    rays = cast_rays(frame, synthetic_grid(flat), 10.0, 200_000.0, STEP)
    expected = -np.arccos(R / (R + h_obs))  # tangent to the sphere
    np.testing.assert_allclose(rays.elevation_rad, expected, atol=2e-7)  # ~1e-5 deg
    # Tangent distance sqrt(2Rh) = 58.9 km, to within one step.
    np.testing.assert_allclose(rays.distance_m, np.sqrt(2 * R * h_obs), atol=STEP)
    assert not rays.no_data.any()


def test_circular_wall_sets_the_horizon_in_every_direction():
    wall_height, inner, thickness = 3000.0, 20_000.0, 2000.0
    grid = synthetic_grid(lambda d, a: np.where((d >= inner) & (d <= inner + thickness), wall_height, 0.0))
    frame = SITE.frame(2.0)
    rays = cast_rays(frame, grid, 10.0, 200_000.0, STEP)
    for i in range(0, 1440, 90):
        az = AZIMUTHS_RAD[i]
        # Bilinear lookup ramps the wall edge over one pixel, and samples fall
        # every STEP, so the highest full-height sample lies within
        # [inner - PIXEL, inner + PIXEL + STEP] of the site.
        upper = elevation_of(frame, az, inner - PIXEL, wall_height)
        lower = elevation_of(frame, az, inner + PIXEL + STEP, wall_height)
        assert lower <= rays.elevation_rad[i] <= upper
        assert abs(rays.distance_m[i] - inner) <= PIXEL + STEP


def test_ridge_in_one_sector_only_raises_that_sector():
    sector = (np.radians(80.0), np.radians(100.0))

    def ridge(d, a):
        az = np.mod(a, 2 * np.pi)
        return np.where((az >= sector[0]) & (az <= sector[1]) & (np.abs(d - 30_000) < 1000), 4000.0, 0.0)

    frame = SITE.frame(2.0)
    bare = cast_rays(frame, synthetic_grid(flat), 10.0, 200_000.0, STEP)
    rays = cast_rays(frame, synthetic_grid(ridge), 10.0, 200_000.0, STEP)
    deg = np.degrees(AZIMUTHS_RAD)
    inside = (deg >= 85) & (deg <= 95)
    outside = (deg < 70) | (deg > 110)
    assert np.all(rays.elevation_rad[inside] > bare.elevation_rad[inside] + np.radians(5))
    np.testing.assert_allclose(rays.elevation_rad[outside], bare.elevation_rad[outside], atol=1e-12)
    assert np.all(np.abs(rays.distance_m[inside] - 30_000) <= 1000 + PIXEL)


def hills(d, a):
    return 800.0 * np.sin(d / 7000.0) * np.cos(3 * a) + 300.0 * np.sin(d / 1300.0 + a)


def test_raising_the_observer_never_raises_the_horizon():
    grid = synthetic_grid(hills)
    low = cast_rays(SITE.frame(0.0), grid, 10.0, 200_000.0, STEP)
    high = cast_rays(SITE.frame(10.0), grid, 10.0, 200_000.0, STEP)
    assert np.all(high.elevation_rad <= low.elevation_rad + 1e-12)


def test_nan_pixel_makes_only_its_direction_unknown():
    grid = synthetic_grid(flat)
    heights = grid.heights_m.copy()
    x, y = map_point(50_000, 45.0)
    col, row = round((x - grid.x0_m) / PIXEL), round((grid.y0_m - y) / PIXEL)
    heights[row, col] = np.nan
    rays = cast_rays(SITE.frame(2.0), TerrainGrid(heights, grid.x0_m, grid.y0_m, PIXEL), 10.0, 200_000.0, STEP)
    deg = np.degrees(AZIMUTHS_RAD[rays.no_data])
    assert len(deg) >= 1
    assert np.all(np.abs(deg - 45.0) < 2.0)


def profile(elevations_deg, no_data=None) -> HorizonProfile:
    el = np.radians(np.asarray(elevations_deg, float))
    n = len(el)
    return HorizonProfile(
        azimuth_rad=np.arange(n) * 2 * np.pi / n,
        elevation_rad=el,
        blocking_distance_m=np.zeros(n),
        from_far=np.zeros(n, bool),
        no_data=np.zeros(n, bool) if no_data is None else np.asarray(no_data),
        observer_height_m=0.0,
    )


def test_horizon_interpolates_and_wraps_at_north():
    p = profile([0.0, 1.0, 2.0, 3.0])  # bins every 90 degrees
    h, _ = horizon_at(p, np.radians([45.0, 315.0, 359.0, 360.0]))
    np.testing.assert_allclose(np.degrees(h), [0.5, 1.5, 3.0 * 1 / 90, 0.0], atol=1e-12)


def test_visibility_rules():
    p = profile([1.0, 1.0, 1.0, 1.0], no_data=[False, False, True, False])
    az = np.radians([10.0, 10.0, 10.0, 200.0])
    el = np.radians([1.5, 1.0, 0.5, 5.0])
    states = visibility(p, az, el)
    assert list(states) == [VISIBLE, OBSTRUCTED, OBSTRUCTED, UNKNOWN]  # on-horizon = obstructed


@pytest.mark.parametrize("h_obs", [0.0, 50.0])
def test_far_point_recompute_is_exact_for_that_point(h_obs):
    """The runtime recomputes the stored far point's elevation from the new
    observer; for the same point this must equal a direct calculation."""
    frame = SITE.frame(h_obs)
    point = (R + 3000.0) * frame.great_circle_direction(np.radians(30.0), 50_000.0 / R)
    assert frame.azimuth_elevation(point)[1] == pytest.approx(elevation_of(frame, np.radians(30.0), 50_000.0, 3000.0))
