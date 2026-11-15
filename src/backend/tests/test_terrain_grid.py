"""
Filename: tests/test_terrain_grid.py
Description: Known-answer tests for the terrain projection and height lookup
    (app/terrain/grid.py, docs/physics/terrain.md section 8) on synthetic
    grids. The pyproj comparison is skipped where pyproj is not installed.
"""

import numpy as np
import pytest

from app.coordinates.frames import MOON_RADIUS_M
from app.terrain.grid import TerrainGrid, polar_stereo_forward, polar_stereo_inverse

RNG = np.random.default_rng(seed=2026)


def random_polar_points(n=5000):
    lat = np.radians(RNG.uniform(-89.999, -80.0, n))
    lon = np.radians(RNG.uniform(0.0, 360.0, n))
    return lat, lon


def test_rho_at_80_south_matches_map_half_width():
    x, y = polar_stereo_forward(np.radians(-80.0), 0.0)
    assert np.hypot(x, y) == pytest.approx(304_000.0, abs=50.0)  # map spans +/-304 km
    expected = 2 * MOON_RADIUS_M * np.tan(np.radians(5.0))
    assert np.hypot(x, y) == pytest.approx(expected, rel=1e-12)


def test_site04_centre_longitude():
    lat, lon = polar_stereo_inverse(-1000.0, -7000.0)
    assert np.degrees(lon) == pytest.approx(188.1301, abs=1e-4)


def test_forward_inverse_round_trip():
    lat, lon = random_polar_points()
    lat2, lon2 = polar_stereo_inverse(*polar_stereo_forward(lat, lon))
    np.testing.assert_allclose(lat2, lat, atol=1e-12)
    np.testing.assert_allclose(np.angle(np.exp(1j * (lon2 - lon))), 0, atol=1e-11)


def test_projection_matches_pyproj():
    pyproj = pytest.importorskip("pyproj")
    lat, lon = random_polar_points()
    proj = pyproj.Proj("+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m")
    px, py = proj(np.degrees(lon), np.degrees(lat))
    x, y = polar_stereo_forward(lat, lon)
    assert np.max(np.hypot(x - px, y - py)) < 0.001  # 1 mm
    plon, plat = proj(px, py, inverse=True)
    lat2, lon2 = polar_stereo_inverse(px, py)
    # 1 mm on the ground is about 6e-10 rad on the 1737.4 km sphere.
    assert np.max(np.abs(lat2 - np.radians(plat))) < 6e-10


def make_grid(heights, x0=1000.0, y0=5000.0, pixel=10.0) -> TerrainGrid:
    return TerrainGrid(np.asarray(heights, dtype=np.float32), x0, y0, pixel)


def pixel_centre(grid: TerrainGrid, row, col):
    return grid.x0_m + col * grid.pixel_m, grid.y0_m - row * grid.pixel_m


def test_lookup_at_pixel_centres_returns_pixel_values():
    heights = RNG.normal(0, 100, (6, 7))
    grid = make_grid(heights)
    rows, cols = np.mgrid[0:6, 0:7]
    x, y = pixel_centre(grid, rows, cols)
    np.testing.assert_allclose(grid.sample_xy(x, y), heights.astype(np.float32), atol=1e-4)


def test_lookup_reproduces_a_tilted_plane():
    rows, cols = np.mgrid[0:20, 0:30]
    grid = make_grid(3.0 * cols - 2.0 * rows + 50.0)
    x = RNG.uniform(grid.x0_m, grid.x0_m + 29 * grid.pixel_m, 1000)
    y = RNG.uniform(grid.y0_m - 19 * grid.pixel_m, grid.y0_m, 1000)
    col = (x - grid.x0_m) / grid.pixel_m
    row = (grid.y0_m - y) / grid.pixel_m
    np.testing.assert_allclose(grid.sample_xy(x, y), 3.0 * col - 2.0 * row + 50.0, atol=1e-3)


def test_points_off_the_grid_are_unknown():
    grid = make_grid(np.zeros((5, 5)))
    x, y = pixel_centre(grid, np.array([-0.01, 2, 4.01, 2]), np.array([2, -0.01, 2, 4.01]))
    assert np.all(np.isnan(grid.sample_xy(x, y)))


def test_last_row_and_column_centres_are_inside():
    heights = np.arange(25, dtype=float).reshape(5, 5)
    grid = make_grid(heights)
    x, y = pixel_centre(grid, 4, 4)
    assert grid.sample_xy(x, y) == pytest.approx(24.0)


def test_nan_neighbour_makes_lookup_unknown():
    heights = np.ones((5, 5))
    heights[2, 2] = np.nan
    grid = make_grid(heights)
    x_near, y_near = pixel_centre(grid, 1.5, 1.5)  # touches (2, 2)
    x_far, y_far = pixel_centre(grid, 0.5, 3.5)    # does not
    assert np.isnan(grid.sample_xy(x_near, y_near))
    assert grid.sample_xy(x_far, y_far) == pytest.approx(1.0)


def test_height_at_uses_lat_lon():
    lat, lon = np.radians(-89.5), np.radians(300.0)
    x, y = polar_stereo_forward(lat, lon)
    grid = make_grid(np.full((3, 3), 123.0), x0=float(x) - 10.0, y0=float(y) + 10.0)
    assert grid.height_at(lat, lon) == pytest.approx(123.0)
