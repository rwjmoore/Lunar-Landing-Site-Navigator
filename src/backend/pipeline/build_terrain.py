"""
Filename: pipeline/build_terrain.py
Description: Offline terrain ingest (docs/physics/terrain.md section 7).

    1. Verifies the source GeoTIFFs against data/manifests/terrain.json.
    2. Refuses any file whose projection or grid differs from the expected
       south polar stereographic layout on the 1737.4 km sphere.
    3. Writes, for each demo site, the 5 m height grid (heights.npy + grid.json)
       to data/artifacts/terrain/<site>/, and the 40 m regional grid to
       data/artifacts/terrain/region_80s_40m/ (all gitignored).
    4. Writes the site list with coordinates and ground heights to
       data/sites/south_pole_sites.json (committed).

    Run from src/backend:  python -m pipeline.build_terrain
"""

import json
from pathlib import Path

import numpy as np
import rasterio
from pyproj import CRS

from app.terrain.grid import TerrainGrid, polar_stereo_inverse
from pipeline import DATA_DIR
from pipeline.checksums import verify

MANIFEST_PATH = DATA_DIR / "manifests" / "terrain.json"
RAW_DIR = DATA_DIR / "raw" / "terrain"
ARTIFACT_DIR = DATA_DIR / "artifacts" / "terrain"
SITES_PATH = DATA_DIR / "sites" / "south_pole_sites.json"

EXPECTED_CRS = CRS.from_proj4("+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m")
# Compared by parameter, not by CRS object equality: the files name the same
# sphere differently ("Moon (2015) - Sphere" vs unnamed), which is irrelevant.
_PROJECTION_KEYS = ("proj", "lat_0", "lat_ts", "lon_0", "x_0", "y_0", "R", "units")
NEAR_FIELD_RADIUS_M = 8000.0  # docs/physics/terrain.md section 7

RIM_SEARCH_RADIUS_M = 2000.0
# (DEM id, name, how the site point is chosen). "dem_centre" uses the centre of
# the 5 m DEM; "highest_within_2km" uses the highest 5 m pixel within 2 km of
# the centre. Site 04's DEM centre lies on Shackleton's inner wall (33 deg
# slope), so its site point is moved to the rim crest (approved 2026-11-14,
# docs/physics/terrain.md section 6).
SITES = [
    ("Site01", "Connecting ridge", "dem_centre"),
    ("Site04", "Shackleton rim", "highest_within_2km"),
    ("Site07", "Peak near Shackleton", "dem_centre"),
    ("Site11", "de Gerlache rim", "dem_centre"),
]
_COORDINATE_SOURCES = {
    "dem_centre": "centre of the PGDA 5 m site DEM",
    "highest_within_2km": "highest 5 m DEM pixel within 2 km of the DEM centre (rim crest)",
}
REGION_FILE = "LDEM_80S_40MPP_ADJ.TIF"


def read_checked(path: Path) -> tuple[np.ndarray, dict]:
    """Read band 1 and grid metadata, refusing unexpected projections or layouts."""
    with rasterio.open(path) as src:
        crs = CRS.from_wkt(src.crs.to_wkt())
        found = {k: crs.to_dict().get(k) for k in _PROJECTION_KEYS}
        expected = {k: EXPECTED_CRS.to_dict().get(k) for k in _PROJECTION_KEYS}
        if found != expected:
            raise ValueError(f"{path.name}: unexpected projection {found}, expected {expected}")
        t = src.transform
        if t.b != 0 or t.d != 0 or t.a != -t.e or t.a <= 0:
            raise ValueError(f"{path.name}: grid must be north-up with square pixels, got {t}")
        if src.count != 1 or src.dtypes[0] != "float32":
            raise ValueError(f"{path.name}: expected one float32 band")
        heights = src.read(1)
        meta = {
            "x0_center_m": t.c + t.a / 2,  # GeoTIFF bounds are pixel edges
            "y0_center_m": t.f + t.e / 2,
            "pixel_m": t.a,
            "width": src.width,
            "height": src.height,
            "crs_proj4": EXPECTED_CRS.to_proj4(),
            "nodata_count": int(np.isnan(heights).sum()),
        }
    return heights, meta


def write_grid(directory: Path, heights: np.ndarray, meta: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    np.save(directory / "heights.npy", heights)
    (directory / "grid.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")


def measured_fraction(counts: np.ndarray, meta: dict, radius_m: float) -> float:
    """Fraction of pixels within radius of the grid centre that hold >= 1 LOLA measurement."""
    rows, cols = counts.shape
    y, x = np.mgrid[0:rows, 0:cols]
    dx = (x - (cols - 1) / 2) * meta["pixel_m"]
    dy = (y - (rows - 1) / 2) * meta["pixel_m"]
    inside = np.hypot(dx, dy) <= radius_m
    return float((counts[inside] > 0).mean())


def site_pixel(heights: np.ndarray, meta: dict, rule: str) -> tuple[float, float]:
    """Fractional row/column of the site point in the 5 m grid, per the site's rule.

    The DEM centre lies between pixel centres (even grid size), so it is fractional.
    """
    rows, cols = heights.shape
    centre = ((rows - 1) / 2, (cols - 1) / 2)
    if rule == "dem_centre":
        return centre
    if rule == "highest_within_2km":
        r, c = np.mgrid[0:rows, 0:cols]
        dist = np.hypot(r - centre[0], c - centre[1]) * meta["pixel_m"]
        masked = np.where(dist <= RIM_SEARCH_RADIUS_M, heights, -np.inf)
        row, col = np.unravel_index(int(np.argmax(masked)), heights.shape)
        return float(row), float(col)
    raise ValueError(f"unknown site rule {rule!r}")


def near_field_radius(meta: dict, row: float, col: float) -> float:
    """Largest radius (<= 8 km) over which every point can be height-looked-up.

    Bilinear lookup needs points within the outermost pixel CENTRES (not the
    pixel edges), so the radius is measured to those centres. Measuring to the
    edges left the last 2.5 m of every near-zone ray unknown (found in M2).
    One pixel of margin is kept because surface distance and map distance
    differ slightly (polar stereographic scale > 1 away from the pole).
    """
    to_outer_centres = [
        col * meta["pixel_m"],
        (meta["width"] - 1 - col) * meta["pixel_m"],
        row * meta["pixel_m"],
        (meta["height"] - 1 - row) * meta["pixel_m"],
    ]
    return min(NEAR_FIELD_RADIUS_M, min(to_outer_centres) - meta["pixel_m"])


def main() -> None:
    files = {f["name"]: f for f in verify(MANIFEST_PATH, RAW_DIR)}

    region_heights, region_meta = read_checked(RAW_DIR / REGION_FILE)
    region_meta["source"] = {"name": REGION_FILE, "sha256": files[REGION_FILE]["sha256"]}
    write_grid(ARTIFACT_DIR / "region_80s_40m", region_heights, region_meta)
    print(f"region: {region_meta['width']}x{region_meta['height']} @ {region_meta['pixel_m']} m, "
          f"NaN {region_meta['nodata_count']}")

    sites = []
    for site_id, name, rule in SITES:
        surf, ldec = f"{site_id}_final_adj_5mpp_surf.tif", f"{site_id}_final_adj_5mpp_ldec.tif"
        heights, meta = read_checked(RAW_DIR / surf)
        counts, count_meta = read_checked(RAW_DIR / ldec)
        if {k: count_meta[k] for k in ("x0_center_m", "y0_center_m", "pixel_m")} != {
            k: meta[k] for k in ("x0_center_m", "y0_center_m", "pixel_m")
        }:
            raise ValueError(f"{site_id}: count map grid differs from height grid")

        meta["source"] = {"name": surf, "sha256": files[surf]["sha256"]}
        meta["measured_fraction_within_8km"] = measured_fraction(counts, meta, NEAR_FIELD_RADIUS_M)
        write_grid(ARTIFACT_DIR / site_id.lower(), heights, meta)

        row, col = site_pixel(heights, meta, rule)
        site_x = meta["x0_center_m"] + col * meta["pixel_m"]
        site_y = meta["y0_center_m"] - row * meta["pixel_m"]
        lat, lon = polar_stereo_inverse(site_x, site_y)
        grid = TerrainGrid(heights, meta["x0_center_m"], meta["y0_center_m"], meta["pixel_m"])
        ground = float(grid.sample_xy(site_x, site_y))
        radius = near_field_radius(meta, row, col)
        sites.append({
            "id": site_id.lower(),
            "name": name,
            "latitude_deg": round(float(np.degrees(lat)), 6),
            "longitude_deg_east": round(float(np.degrees(lon)), 6),
            "ground_height_m": round(ground, 2),
            "map_x_m": site_x,
            "map_y_m": site_y,
            "near_field_radius_m": radius,
            "terrain_dir": f"data/artifacts/terrain/{site_id.lower()}",
            "measured_fraction_within_8km": round(meta["measured_fraction_within_8km"], 4),
            "coordinate_source": f"{_COORDINATE_SOURCES[rule]} (docs/physics/terrain.md section 6)",
        })
        print(f"{site_id}: lat {sites[-1]['latitude_deg']}, lon {sites[-1]['longitude_deg_east']}, "
              f"ground {ground:.1f} m, near field {radius / 1000:.2f} km, NaN {meta['nodata_count']}, "
              f"measured within 8 km {meta['measured_fraction_within_8km']:.1%}")

    SITES_PATH.parent.mkdir(parents=True, exist_ok=True)
    SITES_PATH.write_text(json.dumps({"sites": sites}, indent=2), encoding="utf-8")
    print(f"wrote {SITES_PATH}")


if __name__ == "__main__":
    main()
