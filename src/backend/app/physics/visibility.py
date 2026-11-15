"""
Filename: app/physics/visibility.py
Description: Sun/Earth visibility against a terrain horizon
    (docs/physics/horizon.md section 6). Point-source bodies; the horizon is
    interpolated linearly between the two neighbouring azimuth bins with
    wrap-around at 0/360 degrees. A body exactly on the horizon is obstructed;
    a body next to a no-data direction is unknown.
"""

import numpy as np

from app.coordinates.frames import TWO_PI
from app.metrics.core import OBSTRUCTED, UNKNOWN, VISIBLE
from app.physics.horizon import HorizonProfile


def horizon_at(profile: HorizonProfile, azimuth_rad) -> tuple[np.ndarray, np.ndarray]:
    """Interpolated horizon elevation at arbitrary azimuths, and an 'unknown' mask."""
    n = len(profile.azimuth_rad)
    position = np.mod(np.asarray(azimuth_rad, float), TWO_PI) / (TWO_PI / n)
    lower = np.floor(position).astype(np.int64) % n
    upper = (lower + 1) % n
    fraction = position - np.floor(position)
    h = profile.elevation_rad
    elevation = (1 - fraction) * h[lower] + fraction * h[upper]
    unknown = profile.no_data[lower] | profile.no_data[upper]
    return elevation, unknown


def visibility(profile: HorizonProfile, azimuth_rad, elevation_rad) -> np.ndarray:
    """Visibility state per sample: VISIBLE, OBSTRUCTED or UNKNOWN (int8)."""
    horizon, unknown = horizon_at(profile, azimuth_rad)
    states = np.where(np.asarray(elevation_rad) > horizon, VISIBLE, OBSTRUCTED)
    return np.where(unknown, UNKNOWN, states).astype(np.int8)
