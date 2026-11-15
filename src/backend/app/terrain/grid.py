"""
Filename: app/terrain/grid.py
Description: Terrain height lookup on LOLA south polar stereographic grids
    (docs/physics/terrain.md sections 3 and 5).

      - polar_stereo_forward / polar_stereo_inverse: closed-form projection on
        the 1737.4 km sphere (+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0).
      - TerrainGrid: a regular pixel-registered height grid with bilinear
        lookup. Any NaN neighbour, or a point off the grid, gives NaN, which
        callers must treat as UNKNOWN terrain (never as low or clear).

    Conventions: angles in radians, distances and heights in metres, heights
    above the 1737.4 km reference sphere, longitude east-positive.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.coordinates.frames import MOON_RADIUS_M, TWO_PI


def polar_stereo_forward(lat_rad, lon_rad) -> tuple[np.ndarray, np.ndarray]:
    """South polar stereographic map coordinates (x, y) in metres (section 3)."""
    rho = 2.0 * MOON_RADIUS_M * np.tan(np.pi / 4 + np.asarray(lat_rad, float) / 2)
    lon = np.asarray(lon_rad, float)
    return rho * np.sin(lon), rho * np.cos(lon)


def polar_stereo_inverse(x_m, y_m) -> tuple[np.ndarray, np.ndarray]:
    """Inverse of polar_stereo_forward: (lat_rad, lon_rad in [0, 2*pi))."""
    x, y = np.asarray(x_m, float), np.asarray(y_m, float)
    lat = 2.0 * np.arctan(np.hypot(x, y) / (2.0 * MOON_RADIUS_M)) - np.pi / 2
    lon = np.mod(np.arctan2(x, y), TWO_PI)
    return lat, lon


@dataclass(frozen=True)
class TerrainGrid:
    """Regular height grid in south polar stereographic coordinates.

    Attributes:
        heights_m: (rows, cols) heights above the reference sphere; NaN = no data.
            Row 0 is the northernmost row in map y (largest y), as in GeoTIFFs.
        x0_m: map x of the CENTRE of column 0.
        y0_m: map y of the CENTRE of row 0.
        pixel_m: pixel size (square pixels).
    """

    heights_m: np.ndarray
    x0_m: float
    y0_m: float
    pixel_m: float

    @classmethod
    def load(cls, directory: Path, mmap: bool = True) -> "TerrainGrid":
        """Load `heights.npy` + `grid.json` written by pipeline/build_terrain.py."""
        meta = json.loads((directory / "grid.json").read_text(encoding="utf-8"))
        heights = np.load(directory / "heights.npy", mmap_mode="r" if mmap else None)
        return cls(heights, meta["x0_center_m"], meta["y0_center_m"], meta["pixel_m"])

    @property
    def shape(self) -> tuple[int, int]:
        return self.heights_m.shape

    def sample_xy(self, x_m, y_m) -> np.ndarray:
        """Bilinear height at map coordinates; NaN if off-grid or next to no-data."""
        rows, cols = self.shape
        col = (np.asarray(x_m, float) - self.x0_m) / self.pixel_m
        row = (self.y0_m - np.asarray(y_m, float)) / self.pixel_m
        inside = (col >= 0) & (col <= cols - 1) & (row >= 0) & (row <= rows - 1)

        # Clip so the 2x2 neighbourhood stays in bounds; the last row/column
        # centre is reached with fraction 1 from the previous index.
        c0 = np.clip(np.floor(np.where(inside, col, 0)).astype(np.int64), 0, cols - 2)
        r0 = np.clip(np.floor(np.where(inside, row, 0)).astype(np.int64), 0, rows - 2)
        fc = np.where(inside, col, 0) - c0
        fr = np.where(inside, row, 0) - r0

        h = self.heights_m
        top = h[r0, c0] * (1 - fc) + h[r0, c0 + 1] * fc
        bottom = h[r0 + 1, c0] * (1 - fc) + h[r0 + 1, c0 + 1] * fc
        value = top * (1 - fr) + bottom * fr  # NaN in any neighbour propagates
        return np.where(inside, value, np.nan)

    def height_at(self, lat_rad, lon_rad) -> np.ndarray:
        """Bilinear terrain height at latitude/longitude; NaN means unknown."""
        x, y = polar_stereo_forward(lat_rad, lon_rad)
        return self.sample_xy(x, y)
