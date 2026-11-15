"""
Filename: app/physics/point_terrain.py
Description: Terrain horizons for ANY point in the covered south-polar area,
    computed on demand (docs/physics/custom_points.md). Same interface as
    app.physics.horizon.SiteTerrain (.site and .horizon(height)), so the
    analysis, calendar, explanations and rescue work on it unchanged.

    Two detail tiers, using only the signed-off ray caster (horizon.md):
      - HIGH detail: the point lies inside one of the 5 m site maps. Near zone
        from the 5 m map (radius kept inside the map, max 8 km); far zone cast
        directly over the 40 m map out to 200 km.
      - STANDARD detail: anywhere else. The whole ray is cast over the 40 m map,
        starting two pixels (80 m) out - the configuration validated against
        NASA's published illumination maps (validation.md, comparison A).

    Coverage: every 200 km ray must stay inside the 40 m map (+/- 304 km), so
    points must lie within COVERAGE_RADIUS_M of the pole (about 86.7-90 S).
"""

from dataclasses import dataclass, field

import numpy as np

from app.coordinates.frames import MOON_RADIUS_M
from app.physics.horizon import (
    AZIMUTHS_RAD,
    FAR_STEP_M,
    MAX_OBSERVER_HEIGHT_M,
    MAX_RANGE_M,
    NEAR_STEP_M,
    TERRAIN_DIR,
    HorizonProfile,
    SiteInfo,
    cast_rays,
    near_distances,
    uniform_distances,
)
from app.terrain.grid import TerrainGrid, polar_stereo_forward

COVERAGE_RADIUS_M = 100_000.0        # map half-width 304 km minus the 200 km ray, with margin
NEAR_MAX_M = 8_000.0
STANDARD_SKIP_M = 80.0               # two 40 m pixels: skip the observer's own pixels
REGION_DIR = TERRAIN_DIR / "region_80s_40m"


def coverage_latitude_deg() -> float:
    """Northern edge of the covered area, from COVERAGE_RADIUS_M on the polar map."""
    return float(np.degrees(2 * np.arctan(COVERAGE_RADIUS_M / (2 * MOON_RADIUS_M))) - 90.0)


def standard_distances(relative_step: float = 0.005, max_step_m: float = FAR_STEP_M) -> np.ndarray:
    """80 m to 200 km on the 40 m map; step 0.5% of distance up to the 40 m pixel."""
    out = [STANDARD_SKIP_M]
    while out[-1] < MAX_RANGE_M:
        out.append(min(out[-1] + min(max_step_m, out[-1] * relative_step), MAX_RANGE_M))
    return np.array(out)


def map_radius(grid: TerrainGrid, x: float, y: float) -> float:
    """Largest near-zone radius (<= 8 km) inside a 5 m map around (x, y), one pixel of margin;
    <= 0 if the point is outside the map."""
    rows, cols = grid.shape
    edges = [x - grid.x0_m, grid.x0_m + (cols - 1) * grid.pixel_m - x,
             grid.y0_m - y, y - (grid.y0_m - (rows - 1) * grid.pixel_m)]
    return min(NEAR_MAX_M, min(edges) - grid.pixel_m)


@dataclass
class PointTerrain:
    """On-demand horizons for one point. Horizons are cached per observer height."""

    site: SiteInfo
    region: TerrainGrid
    near_grid: TerrainGrid | None   # 5 m map containing the point, or None (standard detail)
    detail: str                     # 'high' or 'standard'
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def at(cls, latitude_deg: float, longitude_deg_east: float, region: TerrainGrid,
           site_grids: dict[str, TerrainGrid], name: str = "Custom point") -> "PointTerrain":
        """Build the terrain for a point. Raises ValueError outside the covered area."""
        lat, lon = np.radians(latitude_deg), np.radians(longitude_deg_east % 360.0)
        x, y = (float(v) for v in polar_stereo_forward(lat, lon))
        if np.hypot(x, y) > COVERAGE_RADIUS_M:
            raise ValueError(f"outside the covered area (south of {abs(coverage_latitude_deg()):.2f}°S)")
        near_grid, radius = None, 0.0
        for grid in site_grids.values():
            r = map_radius(grid, x, y)
            if r > radius:
                near_grid, radius = grid, r
        ground = float((near_grid or region).sample_xy(x, y))
        if not np.isfinite(ground):
            raise ValueError("no terrain data at this point")
        site = SiteInfo(id=f"pt_{latitude_deg:.6f}_{longitude_deg_east % 360.0:.6f}", name=name,
                        latitude_deg=float(latitude_deg), longitude_deg_east=float(longitude_deg_east % 360.0),
                        ground_height_m=ground, near_field_radius_m=radius)
        return cls(site, region, near_grid, "high" if near_grid is not None else "standard")

    def horizon(self, observer_height_m: float) -> HorizonProfile:
        if not 0.0 <= observer_height_m <= MAX_OBSERVER_HEIGHT_M:
            raise ValueError(f"observer height must be within 0-{MAX_OBSERVER_HEIGHT_M:g} m")
        key = round(float(observer_height_m), 6)
        if key not in self._cache:
            self._cache[key] = self.compute(observer_height_m)
        return self._cache[key]

    def compute(self, observer_height_m: float, azimuths: np.ndarray = AZIMUTHS_RAD,
                refine: float = 1.0) -> HorizonProfile:
        """Full horizon (no caching). `refine` > 1 divides every step (for convergence checks)."""
        frame = self.site.frame(observer_height_m)
        if self.near_grid is None:
            rays = cast_rays(frame, self.region, standard_distances(0.005 / refine, FAR_STEP_M / refine), azimuths)
            return HorizonProfile(azimuths, rays.elevation_rad, rays.distance_m,
                                  np.ones(len(azimuths), bool), rays.no_data, observer_height_m)
        r = self.site.near_field_radius_m
        near = cast_rays(frame, self.near_grid, near_distances(r, NEAR_STEP_M / refine, 0.005 / refine), azimuths)
        far = cast_rays(frame, self.region, uniform_distances(r, MAX_RANGE_M, FAR_STEP_M / refine), azimuths)
        use_far = far.elevation_rad > near.elevation_rad
        return HorizonProfile(azimuths, np.where(use_far, far.elevation_rad, near.elevation_rad),
                              np.where(use_far, far.distance_m, near.distance_m), use_far,
                              near.no_data | far.no_data, observer_height_m)
