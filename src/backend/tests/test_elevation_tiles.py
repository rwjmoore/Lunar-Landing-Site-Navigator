"""
Filename: tests/test_elevation_tiles.py
Description: Tests for the map's elevation overlay tiles (app/terrain/elevation_tiles.py,
    pipeline/build_elevation_tiles.py, docs/elevation_overlay.md): the height
    encoding round trip, the PNG writer, the tile scheme shared with the
    frontend, pyramid orientation, and - when the tiles have been built - that
    built tiles reproduce the LOLA grids and are served by the API.
"""

import json
import struct
import zlib

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.physics.horizon import TERRAIN_DIR
from app.physics.point_terrain import REGION_DIR
from app.terrain.elevation_tiles import (ELEVATION_TILES_DIR, STEP_M, TILE_PX, decode_heights, encode_heights,
                                         pixel_centres, png_bytes, tile_bounds)
from app.terrain.grid import TerrainGrid
from pipeline.build_elevation_tiles import downsample

MANIFEST = ELEVATION_TILES_DIR / "manifest.json"
built = pytest.mark.skipif(not MANIFEST.exists(), reason="elevation tiles not built")


def read_png(data: bytes) -> np.ndarray:
    """Decode the PNGs our writer produces (8-bit RGBA, 'Up' filter) without an imaging library."""
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", data[16:24])
    assert data[24:29] == bytes([8, 6, 0, 0, 0])   # 8-bit RGBA, no interlace
    idat, pos = b"", 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        if kind == b"IDAT":
            idat += data[pos + 8:pos + 8 + length]
        pos += 12 + length
    raw = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(height, width * 4 + 1)
    assert (raw[:, 0] == 2).all()
    rows = np.cumsum(raw[:, 1:].astype(np.int64), axis=0) % 256   # undo the Up filter
    return rows.astype(np.uint8).reshape(height, width, 4)


def test_encoding_round_trip_and_no_data():
    rng = np.random.default_rng(1)
    h = rng.uniform(-8000, 8000, (64, 64))
    h[3, 5] = np.nan
    back = decode_heights(encode_heights(h))
    assert np.isnan(back[3, 5])
    finite = ~np.isnan(h)
    assert np.max(np.abs(back[finite] - h[finite])) <= STEP_M / 2 + 1e-9


def test_png_writer_is_lossless():
    rng = np.random.default_rng(2)
    rgba = rng.integers(0, 256, (37, 53, 4), dtype=np.uint8)
    assert np.array_equal(read_png(png_bytes(rgba)), rgba)


def test_tile_scheme_matches_the_frontend():
    # src/frontend/src/imagery.ts: ROOT_KM = 640, TILE_PX = 512, col along +x, row along +y.
    assert TILE_PX == 512
    assert tile_bounds(0, 0, 0) == (-320_000.0, -320_000.0, 320_000.0, 320_000.0)
    assert tile_bounds(5, 16, 16) == (0.0, 0.0, 20_000.0, 20_000.0)
    x, y = pixel_centres(5, 16, 16)
    assert y[0, 0] > y[-1, 0] and x[0, 0] < x[0, -1]   # image row 0 is the north (largest y) edge


def test_downsample_puts_northern_children_on_top():
    children = {(dc, dr): np.full((TILE_PX, TILE_PX), float(10 * dc + dr)) for dc in (0, 1) for dr in (0, 1)}
    out = downsample(children)
    assert out[0, 0] == 1 and out[0, -1] == 11 and out[-1, 0] == 0 and out[-1, -1] == 10
    assert np.isnan(downsample({**children, (0, 1): None})[0, 0])


@built
def test_built_tiles_reproduce_the_lola_grids():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    region = TerrainGrid.load(REGION_DIR)
    site = TerrainGrid.load(TERRAIN_DIR / "site04")
    x, y = -2_690.0, -6_090.0   # Site 04 (Shackleton rim), map metres
    for grid, level in ((region, manifest["region"]["levels"][1]), (site, manifest["sites"][0]["levels"][1])):
        span = 640_000.0 / 2**level
        col, row = int((x + 320_000) // span), int((y + 320_000) // span)
        tile = decode_heights(read_png((ELEVATION_TILES_DIR / str(level) / str(col) / f"{row}.png").read_bytes()))
        expected = grid.sample_xy(*pixel_centres(level, col, row))
        both = np.isfinite(tile) & np.isfinite(expected)
        assert both.mean() > 0.9
        assert np.max(np.abs(tile[both] - expected[both])) <= STEP_M / 2 + 1e-6


@built
def test_api_serves_the_tiles():
    with TestClient(app) as client:
        manifest = client.get("/tiles/elevation/manifest.json")
        assert manifest.status_code == 200 and manifest.json()["tile_px"] == TILE_PX
        tile = client.get("/tiles/elevation/0/0/0.png")
        assert tile.status_code == 200 and tile.headers["content-type"] == "image/png"
        assert client.get("/tiles/elevation/0/0/9.png").status_code == 404
