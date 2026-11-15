"""
Filename: pipeline/build_far_horizons.py
Description: Precomputes each site's far-zone horizon (docs/physics/horizon.md
    section 4): rays over the 40 m regional map from the site's near-field
    radius out to 200 km, cast from several observer heights
    (FAR_CANDIDATE_HEIGHTS_M). For each height and azimuth it stores the 3D
    point of the highest far terrain and its distance, so the runtime can
    re-evaluate those candidate points exactly for any height in 0-20 m
    without shipping the 882 MB regional map.

    Run from src/backend:  python -m pipeline.build_far_horizons
    Output: data/horizons/<site>_far.npz (committed, ~350 KB each).
"""

import json
import time
from datetime import UTC, datetime

import numpy as np

from app.physics.horizon import (
    AZIMUTHS_RAD,
    FAR_CANDIDATE_HEIGHTS_M,
    FAR_STEP_M,
    HORIZON_DIR,
    MAX_RANGE_M,
    TERRAIN_DIR,
    cast_rays,
    load_sites,
    uniform_distances,
)
from app.terrain.grid import TerrainGrid

REGION_DIR = TERRAIN_DIR / "region_80s_40m"


def build_site(site, region: TerrainGrid) -> dict:
    distances = uniform_distances(site.near_field_radius_m, MAX_RANGE_M, FAR_STEP_M)
    results = [cast_rays(site.frame(h), region, distances) for h in FAR_CANDIDATE_HEIGHTS_M]
    region_meta = json.loads((REGION_DIR / "grid.json").read_text(encoding="utf-8"))
    provenance = {
        "site": site.id,
        "candidate_observer_heights_m": list(FAR_CANDIDATE_HEIGHTS_M),
        "range_m": [site.near_field_radius_m, MAX_RANGE_M],
        "step_m": FAR_STEP_M,
        "azimuths": len(AZIMUTHS_RAD),
        "terrain_source": region_meta["source"],
        "script": "src/backend/pipeline/build_far_horizons.py",
        "created_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return {
        "azimuth_rad": AZIMUTHS_RAD,
        "candidate_heights_m": np.array(FAR_CANDIDATE_HEIGHTS_M),
        "point_m": np.stack([r.point_m for r in results]),
        "distance_m": np.stack([r.distance_m for r in results]),
        "elevation_rad": np.stack([r.elevation_rad for r in results]),
        "no_data": np.any([r.no_data for r in results], axis=0),
        "provenance": np.array(json.dumps(provenance)),
    }


def main() -> None:
    region = TerrainGrid.load(REGION_DIR)
    HORIZON_DIR.mkdir(parents=True, exist_ok=True)
    for site in load_sites().values():
        started = time.perf_counter()
        arrays = build_site(site, region)
        path = HORIZON_DIR / f"{site.id}_far.npz"
        np.savez(path, **arrays)
        ground = arrays["elevation_rad"][0]
        print(f"{site.id}: {time.perf_counter() - started:.1f} s, "
              f"no-data directions {int(arrays['no_data'].sum())}, "
              f"far elevation at ground {np.degrees(ground.min()):+.2f}° to {np.degrees(ground.max()):+.2f}°, "
              f"{path.stat().st_size / 1000:.0f} KB")


if __name__ == "__main__":
    main()
