"""
Filename: app/physics/horizon.py
Description: 360-degree terrain horizon by azimuthal ray casting
    (docs/physics/horizon.md sections 2-5).

      - cast_rays: walks great circles from an observer over one terrain grid
        at given distances and returns, per azimuth, the highest terrain
        elevation angle, its distance and 3D position, and a no-data flag.
      - near_distances / uniform_distances: the sample distances per zone. The
        near zone's step grows with distance (fine close to the observer,
        where small height errors subtend large angles).
      - FarField: the precomputed far zone for a site: the highest far
        terrain point per azimuth as seen from several observer heights
        (built offline by pipeline/build_far_horizons.py, in data/horizons/).
      - SiteTerrain.horizon: near zone cast at runtime for a given observer
        height, combined with the far zone recomputed exactly from its stored
        3D points (section 4).

    Conventions: radians internally, metres, azimuth clockwise from north.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from app.coordinates.frames import MOON_RADIUS_M, TWO_PI, LocalFrame
from app.terrain.grid import TerrainGrid

N_AZIMUTHS = 1440
AZIMUTHS_RAD = np.arange(N_AZIMUTHS) * (TWO_PI / N_AZIMUTHS)  # 0.25 deg bins
MAX_RANGE_M = 200_000.0
SELF_SKIP_M = 10.0          # skip the observer's own pixels (2 x 5 m)
NEAR_STEP_M = 5.0           # largest near-zone step (the 5 m pixel size)
NEAR_RELATIVE_STEP = 0.005  # near-zone step = 0.5% of distance, up to NEAR_STEP_M
FAR_STEP_M = 40.0           # far-zone step (the 40 m pixel size)
MAX_OBSERVER_HEIGHT_M = 20.0  # approved range 0-20 m (horizon.md section 10)
FAR_CANDIDATE_HEIGHTS_M = (0.0, 5.0, 10.0, 15.0, 20.0)
_CHUNK = 120  # azimuths per vectorized block, bounds memory use

REPO_DATA = Path(__file__).resolve().parents[4] / "data"
SITES_PATH = REPO_DATA / "sites" / "south_pole_sites.json"
HORIZON_DIR = REPO_DATA / "horizons"
TERRAIN_DIR = REPO_DATA / "artifacts" / "terrain"


def near_distances(stop_m: float, max_step_m: float = NEAR_STEP_M,
                   relative_step: float = NEAR_RELATIVE_STEP) -> np.ndarray:
    """Near-zone sample distances from SELF_SKIP_M to stop_m.

    The step is `relative_step` x distance, capped at `max_step_m`: 5 cm at
    10 m, 0.5 m at 100 m and 5 m from 1 km on. An angle error at distance s
    scales as height error / s, so closer terrain needs finer sampling
    (step-halving convergence measured in horizon.md section 9.1).
    """
    out = [SELF_SKIP_M]
    while out[-1] < stop_m:
        out.append(min(out[-1] + min(max_step_m, out[-1] * relative_step), stop_m))
    return np.array(out)


def uniform_distances(start_m: float, stop_m: float, step_m: float) -> np.ndarray:
    """Evenly spaced sample distances from start_m to stop_m (inclusive)."""
    return np.arange(start_m, stop_m + step_m / 2, step_m)


@dataclass(frozen=True)
class RayResult:
    """Per-azimuth maximum along one zone of the rays (arrays of length A)."""

    elevation_rad: np.ndarray
    distance_m: np.ndarray
    point_m: np.ndarray  # (A, 3) MOON_ME position of the highest sample
    no_data: np.ndarray  # True if any sample on the ray had unknown terrain


def cast_rays(
    frame: LocalFrame,
    grid: TerrainGrid,
    distances_m: np.ndarray,
    azimuths_rad: np.ndarray = AZIMUTHS_RAD,
) -> RayResult:
    """Highest terrain elevation along each azimuth, sampled at `distances_m`.

    Samples lie on the great circle leaving the observer at each azimuth
    (frames.md section 6). Terrain points are (R + h) * direction; elevation is
    measured from `frame`'s origin, which includes the observer height.
    """
    deltas = np.asarray(distances_m, float) / MOON_RADIUS_M
    n = len(azimuths_rad)
    elevation = np.empty(n)
    distance = np.empty(n)
    point = np.empty((n, 3))
    no_data = np.empty(n, dtype=bool)

    for lo in range(0, n, _CHUNK):
        az = np.asarray(azimuths_rad[lo:lo + _CHUNK])
        directions = frame.great_circle_direction(az[:, None], deltas[None, :])  # (c, D, 3)
        lat = np.arcsin(np.clip(directions[..., 2], -1.0, 1.0))
        lon = np.arctan2(directions[..., 1], directions[..., 0])
        heights = grid.height_at(lat, lon)  # NaN = unknown terrain
        points = (MOON_RADIUS_M + heights)[..., None] * directions
        _, el = frame.azimuth_elevation(points)

        unknown = np.isnan(el)
        best = np.argmax(np.where(unknown, -np.inf, el), axis=1)
        rows = np.arange(len(az))
        elevation[lo:lo + len(az)] = el[rows, best]
        distance[lo:lo + len(az)] = distances_m[best]
        point[lo:lo + len(az)] = points[rows, best]
        no_data[lo:lo + len(az)] = unknown.any(axis=1)

    return RayResult(elevation, distance, point, no_data)


@dataclass(frozen=True)
class SiteInfo:
    """One supported site, as written by pipeline/build_terrain.py."""

    id: str
    name: str
    latitude_deg: float
    longitude_deg_east: float
    ground_height_m: float
    near_field_radius_m: float

    def frame(self, observer_height_m: float = 0.0) -> LocalFrame:
        """Local frame at the observer: ground height plus vehicle height."""
        return LocalFrame.at_site(
            np.radians(self.latitude_deg),
            np.radians(self.longitude_deg_east),
            self.ground_height_m + observer_height_m,
        )


def load_sites(path: Path = SITES_PATH) -> dict[str, SiteInfo]:
    raw = json.loads(path.read_text(encoding="utf-8"))["sites"]
    fields = SiteInfo.__dataclass_fields__
    return {s["id"]: SiteInfo(**{k: s[k] for k in fields}) for s in raw}


@dataclass(frozen=True)
class FarField:
    """Precomputed far zone for one site.

    For each candidate observer height k (FAR_CANDIDATE_HEIGHTS_M) and azimuth,
    the 3D point of the highest far terrain as seen from that height. At
    runtime every candidate is re-evaluated exactly from the requested height
    and the highest is used (section 4).
    """

    azimuth_rad: np.ndarray    # (A,)
    point_m: np.ndarray        # (K, A, 3)
    distance_m: np.ndarray     # (K, A)
    no_data: np.ndarray        # (A,)
    provenance: str = ""

    @classmethod
    def load(cls, path: Path) -> "FarField":
        with np.load(path) as data:
            return cls(data["azimuth_rad"], data["point_m"], data["distance_m"],
                       data["no_data"], str(data["provenance"]))


@dataclass(frozen=True)
class HorizonProfile:
    """Terrain horizon seen from one observer height (arrays of length A).

    `from_far` marks directions set by the far zone; `no_data` directions are
    unknown and must not be treated as clear.
    """

    azimuth_rad: np.ndarray
    elevation_rad: np.ndarray
    blocking_distance_m: np.ndarray
    from_far: np.ndarray
    no_data: np.ndarray
    observer_height_m: float


def combine(frame: LocalFrame, near: RayResult, far: FarField, observer_height_m: float) -> HorizonProfile:
    """Per-azimuth max of the near zone and the far zone's stored candidate
    points, the latter's elevations recomputed exactly from `frame`."""
    _, candidate_elevation = frame.azimuth_elevation(far.point_m)  # (K, A)
    best = np.argmax(candidate_elevation, axis=0)
    columns = np.arange(candidate_elevation.shape[1])
    far_elevation = candidate_elevation[best, columns]
    far_distance = far.distance_m[best, columns]
    use_far = far_elevation > near.elevation_rad
    return HorizonProfile(
        azimuth_rad=AZIMUTHS_RAD,
        elevation_rad=np.where(use_far, far_elevation, near.elevation_rad),
        blocking_distance_m=np.where(use_far, far_distance, near.distance_m),
        from_far=use_far,
        no_data=near.no_data | far.no_data,
        observer_height_m=observer_height_m,
    )


@dataclass
class SiteTerrain:
    """Everything needed to compute a site's horizon at runtime, with a cache
    of horizons by observer height."""

    site: SiteInfo
    near_grid: TerrainGrid
    far: FarField
    _cache: dict = field(default_factory=dict, repr=False)

    @classmethod
    def load(cls, site: SiteInfo) -> "SiteTerrain":
        grid = TerrainGrid.load(TERRAIN_DIR / site.id, mmap=False)
        far = FarField.load(HORIZON_DIR / f"{site.id}_far.npz")
        if far.point_m.shape[1:] != (N_AZIMUTHS, 3):
            raise ValueError(f"{site.id}: unexpected far-field shape {far.point_m.shape}")
        return cls(site, grid, far)

    def horizon(self, observer_height_m: float) -> HorizonProfile:
        """Horizon seen from `observer_height_m` above the site's ground."""
        if not 0.0 <= observer_height_m <= MAX_OBSERVER_HEIGHT_M:
            raise ValueError(f"observer height must be within 0-{MAX_OBSERVER_HEIGHT_M:g} m")
        key = round(float(observer_height_m), 6)
        if key not in self._cache:
            frame = self.site.frame(observer_height_m)
            near = cast_rays(frame, self.near_grid, near_distances(self.site.near_field_radius_m))
            self._cache[key] = combine(frame, near, self.far, observer_height_m)
        return self._cache[key]
