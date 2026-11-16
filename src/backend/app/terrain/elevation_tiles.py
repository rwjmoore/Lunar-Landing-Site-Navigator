"""
Filename: app/terrain/elevation_tiles.py
Description: Tile scheme and height encoding for the map's elevation / slope
    overlay (docs/elevation_overlay.md). Display only: the physics never reads
    these tiles; it samples the LOLA grids directly (app/terrain/grid.py).

    Tile scheme (must match src/frontend/src/imagery.ts): a quadtree over the
    south polar stereographic square x, y in [-320, +320] km; tile (level, col,
    row) spans ROOT_M / 2**level metres, with col counted along +x from the
    west edge and row along +y from the south edge. Each tile is TILE_PX x
    TILE_PX pixels; image row 0 is the tile's northern (largest y) edge.

    Height encoding (lossless PNG, 8-bit RGBA so browsers can read it exactly):
    value = round((h + OFFSET_M) / STEP_M), a 16-bit integer; R = value >> 8,
    G = value & 255, B = 0, A = 255. No data -> A = 0. Decode:
    h = (256 R + G) * STEP_M - OFFSET_M. Covers -8192 m to +8191.75 m in 0.25 m
    steps (the LOLA south-polar range is about -7,254 m to +7,007 m).
"""

import struct
import zlib
from pathlib import Path

import numpy as np

ROOT_M = 640_000.0
ROOT_MIN_M = -ROOT_M / 2
TILE_PX = 512
OFFSET_M = 8192.0
STEP_M = 0.25
ELEVATION_TILES_DIR = Path(__file__).resolve().parents[4] / "data" / "artifacts" / "elevation_tiles"


def tile_span_m(level: int) -> float:
    return ROOT_M / 2**level


def tile_bounds(level: int, col: int, row: int) -> tuple[float, float, float, float]:
    """(min_x, min_y, max_x, max_y) of a tile, in map metres."""
    span = tile_span_m(level)
    min_x = ROOT_MIN_M + col * span
    min_y = ROOT_MIN_M + row * span
    return min_x, min_y, min_x + span, min_y + span


def pixel_centres(level: int, col: int, row: int) -> tuple[np.ndarray, np.ndarray]:
    """Map x, y of every pixel centre, shaped (TILE_PX, TILE_PX); row 0 is the north edge."""
    min_x, min_y, max_x, max_y = tile_bounds(level, col, row)
    pixel = (max_x - min_x) / TILE_PX
    xs = min_x + (np.arange(TILE_PX) + 0.5) * pixel
    ys = max_y - (np.arange(TILE_PX) + 0.5) * pixel
    return np.meshgrid(xs, ys)


def encode_heights(heights_m: np.ndarray) -> np.ndarray:
    """Heights (NaN = no data) -> uint8 RGBA array per the encoding above."""
    h = np.asarray(heights_m, float)
    valid = np.isfinite(h)
    value = np.clip(np.round((np.where(valid, h, 0.0) + OFFSET_M) / STEP_M), 0, 65535).astype(np.uint32)
    rgba = np.zeros(h.shape + (4,), np.uint8)
    rgba[..., 0] = value >> 8
    rgba[..., 1] = value & 255
    rgba[..., 3] = np.where(valid, 255, 0)
    rgba[~valid, :3] = 0
    return rgba


def decode_heights(rgba: np.ndarray) -> np.ndarray:
    """Inverse of encode_heights (NaN where alpha is 0)."""
    rgba = np.asarray(rgba)
    value = rgba[..., 0].astype(np.float64) * 256 + rgba[..., 1]
    return np.where(rgba[..., 3] > 0, value * STEP_M - OFFSET_M, np.nan)


def png_bytes(rgba: np.ndarray) -> bytes:
    """Minimal PNG writer (8-bit RGBA, 'Up' row filter), so the pipeline needs no imaging library."""
    rows, cols, _ = rgba.shape
    data = rgba.astype(np.int16)
    filtered = np.empty_like(data)
    filtered[0] = data[0]
    filtered[1:] = data[1:] - data[:-1]
    raw = np.empty((rows, cols * 4 + 1), np.uint8)
    raw[:, 0] = 2  # filter type 2 = Up
    raw[:, 1:] = (filtered % 256).astype(np.uint8).reshape(rows, cols * 4)

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload))

    header = struct.pack(">IIBBBBB", cols, rows, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(raw.tobytes(), 9)) + chunk(b"IEND", b""))
