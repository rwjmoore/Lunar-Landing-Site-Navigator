"""
Filename: pipeline/build_elevation_tiles.py
Description: Builds the map's elevation overlay tiles from the LOLA terrain
    artifacts (docs/elevation_overlay.md). Run after pipeline.build_terrain:

        python -m pipeline.build_elevation_tiles

    Output: data/artifacts/elevation_tiles/{level}/{col}/{row}.png plus
    manifest.json (gitignored; served by the API at /tiles/elevation/).

    - Levels 0-5 come from the 40 m regional map (80-90 S); level 5 has
      39 m pixels, matching the source.
    - Levels 6-8 come from the 5 m site maps and exist only around the four
      sites; level 8 has 4.9 m pixels.
    The finest level of each source is sampled bilinearly at pixel centres
    (the same lookup the physics uses); every coarser tile is the 2x2 mean of
    its four children, so coarse tiles are true area averages, not aliased
    point samples. Encoding: app/terrain/elevation_tiles.py.
"""

import json
import shutil
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

from app.physics.horizon import TERRAIN_DIR, load_sites
from app.physics.point_terrain import REGION_DIR
from app.terrain.elevation_tiles import (ELEVATION_TILES_DIR, OFFSET_M, ROOT_M, STEP_M, TILE_PX,
                                         encode_heights, pixel_centres, png_bytes, tile_bounds)
from app.terrain.grid import TerrainGrid

REGION_LEVELS = (0, 5)
SITE_LEVELS = (6, 8)


def grid_bounds(grid: TerrainGrid) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of a grid's outer pixel edges."""
    rows, cols = grid.shape
    half = grid.pixel_m / 2
    return (grid.x0_m - half, grid.y0_m - (rows - 1) * grid.pixel_m - half,
            grid.x0_m + (cols - 1) * grid.pixel_m + half, grid.y0_m + half)


def overlaps(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def downsample(children: dict[tuple[int, int], np.ndarray | None]) -> np.ndarray:
    """2x2 NaN-aware mean of four child tiles keyed by (dcol, drow); None = no data."""
    empty = np.full((TILE_PX, TILE_PX), np.nan)
    mosaic = np.empty((2 * TILE_PX, 2 * TILE_PX))
    # Image row 0 is north, so the northern children (drow = 1) go on top.
    for (dc, dr), child in children.items():
        r0 = 0 if dr == 1 else TILE_PX
        c0 = dc * TILE_PX
        mosaic[r0:r0 + TILE_PX, c0:c0 + TILE_PX] = empty if child is None else child
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN blocks stay NaN
        return np.nanmean(mosaic.reshape(TILE_PX, 2, TILE_PX, 2), axis=(1, 3))


class Builder:
    def __init__(self, sample, levels: tuple[int, int], coverage: list[tuple], out_dir):
        self.sample, self.levels, self.coverage, self.out_dir = sample, levels, coverage, out_dir
        self.count = 0
        self.height_min, self.height_max = np.inf, -np.inf
        self._lock = threading.Lock()   # tiles are built on worker threads

    def build(self, level: int, col: int, row: int) -> np.ndarray | None:
        """Write this tile (and its descendants); return its heights, or None if no data."""
        if not any(overlaps(tile_bounds(level, col, row), area) for area in self.coverage):
            return None
        if level == self.levels[1]:
            heights = self.sample(*pixel_centres(level, col, row))
        else:
            heights = downsample({(dc, dr): self.build(level + 1, 2 * col + dc, 2 * row + dr)
                                  for dc in (0, 1) for dr in (0, 1)})
        if not np.isfinite(heights).any():
            return None
        if level >= self.levels[0]:
            self.write(level, col, row, heights)
        return heights

    def write(self, level: int, col: int, row: int, heights: np.ndarray) -> None:
        path = self.out_dir / str(level) / str(col) / f"{row}.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(encode_heights(heights)))
        with self._lock:
            self.count += 1
            if level == self.levels[1]:
                self.height_min = min(self.height_min, float(np.nanmin(heights)))
                self.height_max = max(self.height_max, float(np.nanmax(heights)))

    def build_from(self, start_level: int) -> None:
        """Build every subtree rooted at start_level on 4 workers (numpy and zlib release the GIL),
        then the coarser levels above it from those subtrees' results."""
        n = 2**start_level
        roots = [(c, r) for c in range(n) for r in range(n)]
        with ThreadPoolExecutor(4) as pool:
            done = dict(zip(roots, pool.map(lambda t: self.build(start_level, *t), roots)))
        for level in range(start_level - 1, self.levels[0] - 1, -1):
            n = 2**level
            coarser = {}
            for col in range(n):
                for row in range(n):
                    heights = downsample({(dc, dr): done.get((2 * col + dc, 2 * row + dr)) for dc in (0, 1) for dr in (0, 1)})
                    if np.isfinite(heights).any():
                        self.write(level, col, row, heights)
                        coarser[(col, row)] = heights
            done = coarser


def main() -> None:
    started = time.time()
    out = ELEVATION_TILES_DIR
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    region = TerrainGrid.load(REGION_DIR)
    region_builder = Builder(region.sample_xy, REGION_LEVELS, [grid_bounds(region)], out)
    region_builder.build_from(start_level=2)   # 16 independent subtrees, then levels 1 and 0
    print(f"region: {region_builder.count} tiles, levels {REGION_LEVELS[0]}-{REGION_LEVELS[1]}, {time.time() - started:.0f} s")

    sites = {sid: TerrainGrid.load(TERRAIN_DIR / sid) for sid in load_sites()}
    site_bounds = {sid: grid_bounds(grid) for sid, grid in sites.items()}
    centres = {sid: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for sid, b in site_bounds.items()}

    def sample_sites(x, y):
        """Where 5 m maps overlap (Sites 01 and 04 do), use the map whose centre is nearest, so each
        site's surroundings come from that site's own map, the one its physics uses."""
        result = np.full(np.shape(x), np.nan)
        nearest = np.full(np.shape(x), np.inf)
        for sid, grid in sites.items():
            value = grid.sample_xy(x, y)
            distance = np.hypot(x - centres[sid][0], y - centres[sid][1])
            take = np.isfinite(value) & (distance < nearest)
            result = np.where(take, value, result)
            nearest = np.where(take, distance, nearest)
        return result

    site_builder = Builder(sample_sites, SITE_LEVELS, list(site_bounds.values()), out)
    n = 2**SITE_LEVELS[0]
    roots = [(SITE_LEVELS[0], c, r) for c in range(n) for r in range(n)
             if any(overlaps(tile_bounds(SITE_LEVELS[0], c, r), b) for b in site_bounds.values())]
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda t: site_builder.build(*t), roots))
    print(f"sites: {site_builder.count} tiles, levels {SITE_LEVELS[0]}-{SITE_LEVELS[1]}")

    manifest = {
        "description": "Elevation overlay tiles (display only). Scheme and encoding: app/terrain/elevation_tiles.py.",
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tile_px": TILE_PX,
        "root_m": ROOT_M,
        "encoding": {"offset_m": OFFSET_M, "step_m": STEP_M, "formula": "h = (256 R + G) * step_m - offset_m; A = 0 means no data"},
        "region": {"levels": list(REGION_LEVELS), "bounds_m": list(grid_bounds(region)), "source_pixel_m": region.pixel_m,
                   "source": "LDEM_80S_40MPP_ADJ (LOLA, 40 m)"},
        "sites": [{"id": sid, "levels": list(SITE_LEVELS), "bounds_m": list(b), "source_pixel_m": sites[sid].pixel_m,
                   "source": f"{sid} LOLA 5 m site map"} for sid, b in site_bounds.items()],
        "height_range_m": [round(min(region_builder.height_min, site_builder.height_min), 1),
                           round(max(region_builder.height_max, site_builder.height_max), 1)],
        "tiles": region_builder.count + site_builder.count,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    size = sum(p.stat().st_size for p in out.rglob("*.png"))
    print(f"total {manifest['tiles']} tiles, {size / 1e6:.0f} MB, in {time.time() - started:.0f} s -> {out}")


if __name__ == "__main__":
    main()
