"""
Filename: tests/test_frames.py
Description: Known-answer tests for lunar coordinate geometry
    (app/coordinates/frames.py), one test per check in docs/physics/frames.md
    section 7.
"""

import numpy as np
import pytest

from app.coordinates.frames import (
    MOON_RADIUS_M,
    LocalFrame,
    position_to_site,
    site_to_position,
)

ATOL_RAD = 1e-12
# Sites spanning the globe plus realistic south-pole sites.
SITES_DEG = [(0, 0), (30, 45), (-45, 200), (-85, 10), (-89.5, 300), (-89.9, 123.4), (89.9, 0)]


def angle_diff(a, b):
    """Smallest signed difference between angles, handling the 0/2*pi seam."""
    return np.angle(np.exp(1j * (np.asarray(a) - np.asarray(b))))


def frame_deg(lat_deg, lon_deg, h=0.0) -> LocalFrame:
    return LocalFrame.at_site(np.radians(lat_deg), np.radians(lon_deg), h)


def test_frame_at_origin_matches_axes():
    frame = frame_deg(0, 0)

    np.testing.assert_allclose(frame.up, [1, 0, 0], atol=ATOL_RAD)
    np.testing.assert_allclose(frame.east, [0, 1, 0], atol=ATOL_RAD)
    np.testing.assert_allclose(frame.north, [0, 0, 1], atol=ATOL_RAD)
    np.testing.assert_allclose(frame.origin, [MOON_RADIUS_M, 0, 0])


@pytest.mark.parametrize("lat, lon", SITES_DEG)
def test_frame_is_orthonormal_and_right_handed(lat, lon):
    f = frame_deg(lat, lon)
    basis = np.stack([f.east, f.north, f.up])

    np.testing.assert_allclose(basis @ basis.T, np.eye(3), atol=ATOL_RAD)
    np.testing.assert_allclose(np.cross(f.east, f.north), f.up, atol=ATOL_RAD)
    np.testing.assert_allclose(f.up, f.origin / np.linalg.norm(f.origin), atol=ATOL_RAD)


@pytest.mark.parametrize("lat, lon", SITES_DEG)
@pytest.mark.parametrize(
    "axis, expected_az_deg", [("north", 0), ("east", 90), ("-north", 180), ("-east", 270)]
)
def test_cardinal_directions(lat, lon, axis, expected_az_deg):
    f = frame_deg(lat, lon)
    sign = -1.0 if axis.startswith("-") else 1.0
    target = f.origin + 1000.0 * sign * getattr(f, axis.lstrip("-"))

    azimuth, elevation = f.azimuth_elevation(target)

    assert abs(angle_diff(azimuth, np.radians(expected_az_deg))) < 1e-9
    assert abs(elevation) < 1e-9


@pytest.mark.parametrize("lat, lon", SITES_DEG)
def test_straight_up_is_ninety_degrees_elevation(lat, lon):
    f = frame_deg(lat, lon)

    _, elevation = f.azimuth_elevation(f.origin + 500.0 * f.up)

    assert elevation == pytest.approx(np.pi / 2, abs=1e-12)


def test_site_position_round_trip():
    lat = np.radians([0, 30, -45, -89.9, -89.5, 10, -20])
    lon = np.radians([0, 45, 200, 123.4, 359.9999, 0.0001, 359.0])
    h = np.array([0.0, 100.0, -2500.0, 5000.0, 0.0, 12.3, -7.0])

    lat2, lon2, h2 = position_to_site(site_to_position(lat, lon, h))

    np.testing.assert_allclose(lat2, lat, atol=1e-12)
    np.testing.assert_allclose(angle_diff(lon2, lon), 0, atol=1e-12)
    np.testing.assert_allclose(h2, h, atol=1e-6)
    assert np.all((lon2 >= 0) & (lon2 < 2 * np.pi))


def test_great_circle_zero_distance_returns_site():
    f = frame_deg(-89.5, 300)

    direction = f.great_circle_direction(np.radians(37.0), 0.0)

    np.testing.assert_allclose(direction, f.up, atol=ATOL_RAD)


def test_great_circle_north_from_equator_reaches_pole():
    f = frame_deg(0, 75)

    direction = f.great_circle_direction(0.0, np.pi / 2)

    np.testing.assert_allclose(direction, [0, 0, 1], atol=ATOL_RAD)


@pytest.mark.parametrize("lat, lon", [(-89.5, 300), (-85, 10), (20, 200)])
def test_point_reached_at_azimuth_is_seen_at_that_azimuth(lat, lon):
    f = frame_deg(lat, lon)
    azimuths = np.radians(np.arange(0, 360, 7.5))[:, None]
    deltas = np.array([1e-4, 0.01, 0.1, 1.0, 3.0])[None, :]  # up to ~172 degrees

    targets = MOON_RADIUS_M * f.great_circle_direction(azimuths, deltas)
    seen_az, _ = f.azimuth_elevation(targets)

    np.testing.assert_allclose(angle_diff(seen_az, azimuths), 0, atol=1e-9)


@pytest.mark.parametrize("delta", [1e-5, 1e-3, 0.05, 0.5, 2.0])
def test_surface_point_elevation_is_minus_half_angular_distance(delta):
    f = frame_deg(-89.5, 300)

    target = MOON_RADIUS_M * f.great_circle_direction(np.radians(123.0), delta)
    _, elevation = f.azimuth_elevation(target)

    assert elevation == pytest.approx(-delta / 2, rel=1e-9)


def test_great_circle_broadcasts_to_ray_grid():
    f = frame_deg(-89.5, 300)

    grid = f.great_circle_direction(np.zeros((1440, 1)), np.zeros((1, 50)))

    assert grid.shape == (1440, 50, 3)
    np.testing.assert_allclose(np.linalg.norm(grid, axis=-1), 1.0, atol=1e-12)


@pytest.mark.parametrize("lat_deg", [-90.0, -89.9995, 89.9995, 90.0])
def test_sites_at_the_pole_are_rejected(lat_deg):
    with pytest.raises(ValueError, match="pole"):
        frame_deg(lat_deg, 0)


def test_sites_just_inside_pole_limit_are_accepted():
    frame_deg(-89.9989, 0)
