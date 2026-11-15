"""
Filename: app/coordinates/frames.py
Description: Pure geometry on the lunar reference sphere in the MOON_ME frame.

    Implements docs/physics/frames.md (section numbers below refer to it):
      - site_to_position / position_to_site  (section 3)
      - LocalFrame: east/north/up directions at a site (section 4),
        azimuth/elevation of targets (section 5), and great-circle directions
        for horizon ray casting (section 6).

    Conventions: angles in radians, distances in metres, latitude
    planetocentric, longitude east-positive in [0, 2*pi), heights above the
    1737.4 km reference sphere. Azimuth is clockwise from north.
"""

from dataclasses import dataclass

import numpy as np

MOON_RADIUS_M = 1_737_400.0
"""Radius of the reference sphere that LOLA heights are measured against."""

MAX_SITE_LATITUDE_RAD = np.radians(89.999)
"""Sites closer to a pole than this are rejected: 'north' is undefined at the pole."""

TWO_PI = 2.0 * np.pi


def site_to_position(lat_rad, lon_rad, height_m=0.0) -> np.ndarray:
    """Moon-fixed position (metres) of a site; inputs may be arrays. Shape (..., 3)."""
    lat, lon, h = np.broadcast_arrays(
        np.asarray(lat_rad, float), np.asarray(lon_rad, float), np.asarray(height_m, float)
    )
    radius = MOON_RADIUS_M + h
    return np.stack(
        (
            radius * np.cos(lat) * np.cos(lon),
            radius * np.cos(lat) * np.sin(lon),
            radius * np.sin(lat),
        ),
        axis=-1,
    )


def position_to_site(position) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inverse of site_to_position: returns (lat_rad, lon_rad in [0, 2*pi), height_m)."""
    p = np.asarray(position, float)
    r = np.linalg.norm(p, axis=-1)
    lat = np.arcsin(np.clip(p[..., 2] / r, -1.0, 1.0))
    lon = np.mod(np.arctan2(p[..., 1], p[..., 0]), TWO_PI)
    return lat, lon, r - MOON_RADIUS_M


@dataclass(frozen=True)
class LocalFrame:
    """Local east/north/up frame at one site.

    Attributes:
        origin: Site position in MOON_ME, metres, shape (3,).
        east, north, up: Unit vectors in MOON_ME, shape (3,). Right-handed:
            east x north = up.
    """

    origin: np.ndarray
    east: np.ndarray
    north: np.ndarray
    up: np.ndarray

    @classmethod
    def at_site(cls, lat_rad: float, lon_rad: float, height_m: float = 0.0) -> "LocalFrame":
        """Build the frame at a site (frames.md section 4).

        Raises ValueError for sites within 0.001 degrees of a pole.
        """
        if abs(lat_rad) > MAX_SITE_LATITUDE_RAD:
            raise ValueError(
                f"latitude {np.degrees(lat_rad):.4f} deg is too close to a pole; "
                "east/north are undefined there"
            )
        sin_lat, cos_lat = np.sin(lat_rad), np.cos(lat_rad)
        sin_lon, cos_lon = np.sin(lon_rad), np.cos(lon_rad)
        return cls(
            origin=site_to_position(lat_rad, lon_rad, height_m),
            east=np.array([-sin_lon, cos_lon, 0.0]),
            north=np.array([-sin_lat * cos_lon, -sin_lat * sin_lon, cos_lat]),
            up=np.array([cos_lat * cos_lon, cos_lat * sin_lon, sin_lat]),
        )

    def azimuth_elevation(self, target_position) -> tuple[np.ndarray, np.ndarray]:
        """Azimuth in [0, 2*pi) and elevation of targets seen from this site (section 5).

        `target_position` is a MOON_ME position in metres, shape (..., 3). The
        vector is taken from the site, so the result is topocentric.
        """
        r = np.asarray(target_position, float) - self.origin
        e, n, u = r @ self.east, r @ self.north, r @ self.up
        azimuth = np.mod(np.arctan2(e, n), TWO_PI)
        elevation = np.arctan2(u, np.hypot(e, n))
        return azimuth, elevation

    def great_circle_direction(self, azimuth_rad, angular_distance_rad) -> np.ndarray:
        """Unit vector from the Moon's center to the point reached by walking the
        great circle that leaves the site at `azimuth_rad`, for an angular
        distance `angular_distance_rad` = surface distance / MOON_RADIUS_M
        (section 6). Inputs broadcast together; result shape (..., 3).

        For ray casting, pass azimuths shaped (A, 1) and distances shaped (1, D)
        to get an (A, D, 3) grid of sample directions.
        """
        az, delta = np.broadcast_arrays(
            np.asarray(azimuth_rad, float), np.asarray(angular_distance_rad, float)
        )
        az, delta = az[..., None], delta[..., None]
        horizontal = np.cos(az) * self.north + np.sin(az) * self.east
        return np.cos(delta) * self.up + np.sin(delta) * horizontal
