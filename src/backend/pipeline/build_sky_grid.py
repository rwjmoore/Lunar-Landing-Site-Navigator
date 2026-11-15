"""
Filename: pipeline/build_sky_grid.py
Description: Builds the sky grid (docs/physics/sky.md section 4): apparent Sun
    and Earth position vectors from the Moon's center, in MOON_ME, with LT+S
    aberration correction, every whole UTC hour over the supported date range.

    Run from src/backend:  python -m pipeline.build_sky_grid
    Output: data/sky/sky_grid_de421_2026_2040_1h.npz (committed to the repo).
"""

import json
from datetime import UTC, datetime

import numpy as np
import spiceypy

from pipeline import DATA_DIR
from pipeline.spice_kernels import load_kernels

GRID_START_UTC = "2026-01-01T00:00:00Z"
GRID_END_UTC = "2041-01-01T00:00:00Z"  # exclusive
GRID_STEP_S = 3600
OUTPUT_PATH = DATA_DIR / "sky" / "sky_grid_de421_2026_2040_1h.npz"
KM_TO_M = 1000.0


def grid_utc_strings() -> list[str]:
    """Whole-hour UTC instants from GRID_START_UTC up to (not incl.) GRID_END_UTC."""
    start = np.datetime64(GRID_START_UTC.rstrip("Z"), "s")
    end = np.datetime64(GRID_END_UTC.rstrip("Z"), "s")
    times = np.arange(start, end, np.timedelta64(GRID_STEP_S, "s"))
    return [str(t) for t in times]


def utc_to_et(utc_strings: list[str]) -> np.ndarray:
    """UTC ISO strings -> TDB seconds past J2000, via the leapseconds kernel."""
    return np.array([spiceypy.str2et(s) for s in utc_strings])


def apparent_positions_from_moon_center(target: str, et: np.ndarray) -> np.ndarray:
    """Apparent position of `target` from the Moon's center in MOON_ME, metres. Shape (N, 3)."""
    positions_km, _ = spiceypy.spkpos(target, et, "MOON_ME", "LT+S", "MOON")
    return np.asarray(positions_km) * KM_TO_M


def build() -> dict:
    """Compute the grid arrays and provenance (kernels must be loadable)."""
    kernels = load_kernels()
    utc = grid_utc_strings()
    et = utc_to_et(utc)
    provenance = {
        "description": "Apparent Sun/Earth positions from Moon center, MOON_ME, LT+S",
        "grid_start_utc": GRID_START_UTC,
        "grid_end_utc_exclusive": GRID_END_UTC,
        "step_s": GRID_STEP_S,
        "samples": len(utc),
        "kernels": [{"name": k["name"], "sha256": k["sha256"]} for k in kernels],
        "spiceypy": spiceypy.__version__,
        "cspice": spiceypy.tkvrsn("TOOLKIT"),
        "script": "src/backend/pipeline/build_sky_grid.py",
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {
        "utc_start": np.array(GRID_START_UTC),
        "step_s": np.array(GRID_STEP_S),
        "et_tdb_s": et,
        "sun_m": apparent_positions_from_moon_center("SUN", et),
        "earth_m": apparent_positions_from_moon_center("EARTH", et),
        "provenance": np.array(json.dumps(provenance)),
    }


def main() -> None:
    arrays = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez(OUTPUT_PATH, **arrays)
    size_mb = OUTPUT_PATH.stat().st_size / 1e6
    print(f"wrote {OUTPUT_PATH} ({len(arrays['et_tdb_s'])} samples, {size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
