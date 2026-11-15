"""
Filename: tests/test_terrain_data.py
Description: Validation of the built terrain artifacts against the source
    GeoTIFFs (docs/physics/terrain.md section 8). Skipped automatically when
    rasterio, the raw files or the built artifacts are not present.
"""

import json

import numpy as np
import pytest

rasterio = pytest.importorskip("rasterio")

from app.terrain.grid import TerrainGrid  # noqa: E402
from pipeline.build_terrain import ARTIFACT_DIR, RAW_DIR, SITES_PATH  # noqa: E402

pytestmark = pytest.mark.skipif(
    not (SITES_PATH.exists() and (ARTIFACT_DIR / "region_80s_40m" / "heights.npy").exists()),
    reason="terrain artifacts not built",
)
SITE_IDS = ["site01", "site04", "site07", "site11"]


def raw_name(site_id: str) -> str:
    return f"Site{site_id[-2:]}_final_adj_5mpp_surf.tif"


@pytest.mark.parametrize("site_id", SITE_IDS)
def test_lookup_matches_rasterio_at_pixel_centres(site_id):
    """Confirms the half-pixel registration: our lookup at rasterio's pixel
    centres returns exactly the values rasterio reads there."""
    grid = TerrainGrid.load(ARTIFACT_DIR / site_id)
    rng = np.random.default_rng(seed=7)
    with rasterio.open(RAW_DIR / raw_name(site_id)) as src:
        rows = rng.integers(0, src.height, 500)
        cols = rng.integers(0, src.width, 500)
        xs, ys = rasterio.transform.xy(src.transform, rows, cols, offset="center")
        expected = np.array([v[0] for v in src.sample(zip(xs, ys))])
    np.testing.assert_allclose(grid.sample_xy(np.array(xs), np.array(ys)), expected, atol=1e-3)


def test_regional_lookup_matches_rasterio():
    grid = TerrainGrid.load(ARTIFACT_DIR / "region_80s_40m")
    rng = np.random.default_rng(seed=8)
    with rasterio.open(RAW_DIR / "LDEM_80S_40MPP_ADJ.TIF") as src:
        rows = rng.integers(0, src.height, 300)
        cols = rng.integers(0, src.width, 300)
        xs, ys = rasterio.transform.xy(src.transform, rows, cols, offset="center")
        expected = np.array([v[0] for v in src.sample(zip(xs, ys))])
    np.testing.assert_allclose(grid.sample_xy(np.array(xs), np.array(ys)), expected, atol=1e-3)


@pytest.mark.parametrize("site_id", SITE_IDS + ["region_80s_40m"])
def test_no_missing_data(site_id):
    grid = TerrainGrid.load(ARTIFACT_DIR / site_id)
    assert not np.isnan(grid.heights_m).any()


@pytest.mark.parametrize("site_id", SITE_IDS)
def test_5m_and_40m_share_a_height_datum(site_id):
    """Averaging the 5 m map into 40 m blocks must agree with the 40 m map on
    average; a systematic offset would mean a datum mismatch."""
    site = TerrainGrid.load(ARTIFACT_DIR / site_id, mmap=False)
    region = TerrainGrid.load(ARTIFACT_DIR / "region_80s_40m")
    blocks = site.heights_m.reshape(400, 8, 400, 8).mean(axis=(1, 3))
    # Centres of the 8x8 blocks, which coincide with 40 m pixel centres.
    x = site.x0_m + 3.5 * site.pixel_m + 40.0 * np.arange(400)
    y = site.y0_m - 3.5 * site.pixel_m - 40.0 * np.arange(400)
    xx, yy = np.meshgrid(x, y)
    diff = blocks - region.sample_xy(xx, yy)
    assert abs(np.mean(diff)) < 1.0
    assert np.sqrt(np.mean(diff**2)) < 20.0


def test_site_list_is_consistent():
    sites = json.loads(SITES_PATH.read_text(encoding="utf-8"))["sites"]
    assert [s["id"] for s in sites] == SITE_IDS
    for s in sites:
        grid = TerrainGrid.load(ARTIFACT_DIR / s["id"])
        ground = grid.height_at(np.radians(s["latitude_deg"]), np.radians(s["longitude_deg_east"]))
        assert ground == pytest.approx(s["ground_height_m"], abs=0.05)
        assert -90.0 < s["latitude_deg"] < -88.0
        # The near-field circle must lie within the outermost pixel centres,
        # where every point can be height-looked-up.
        rows, cols = grid.shape
        left, right = grid.x0_m, grid.x0_m + (cols - 1) * grid.pixel_m
        top, bottom = grid.y0_m, grid.y0_m - (rows - 1) * grid.pixel_m
        edge = min(s["map_x_m"] - left, right - s["map_x_m"], top - s["map_y_m"], s["map_y_m"] - bottom)
        assert 0 < s["near_field_radius_m"] <= min(8000.0, edge) + 1e-6


def test_site04_is_on_the_shackleton_rim_crest():
    """Site 04's DEM centre is on the crater's inner wall; the site point must be
    the local high ground instead (docs/physics/terrain.md section 6)."""
    site = next(s for s in json.loads(SITES_PATH.read_text(encoding="utf-8"))["sites"] if s["id"] == "site04")
    grid = TerrainGrid.load(ARTIFACT_DIR / "site04", mmap=False)
    rows, cols = np.mgrid[0:grid.shape[0], 0:grid.shape[1]]
    x = grid.x0_m + cols * grid.pixel_m
    y = grid.y0_m - rows * grid.pixel_m
    within_1km = np.hypot(x - site["map_x_m"], y - site["map_y_m"]) <= 1000.0
    assert site["ground_height_m"] == pytest.approx(float(grid.heights_m[within_1km].max()), abs=0.05)
    assert "rim crest" in site["coordinate_source"]
