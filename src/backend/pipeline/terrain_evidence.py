"""
Filename: pipeline/terrain_evidence.py
Description: Produces the review evidence for docs/physics/terrain.md
    section 8.1: projection agreement with pyproj, 5 m vs 40 m height
    consistency, the local terrain at each proposed site point (slope and
    nearby high ground), and shaded-relief images of each site and the region.

    Run from src/backend:  python -m pipeline.terrain_evidence
"""

import json
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pyproj  # noqa: E402

from app.terrain.grid import TerrainGrid, polar_stereo_forward, polar_stereo_inverse  # noqa: E402
from pipeline import REPO_ROOT  # noqa: E402
from pipeline.build_terrain import ARTIFACT_DIR, SITES_PATH  # noqa: E402

IMG_DIR = REPO_ROOT / "docs" / "physics" / "img"


def hillshade(h: np.ndarray, pixel_m: float, azimuth_deg=315.0, altitude_deg=30.0) -> np.ndarray:
    dz_dy, dz_dx = np.gradient(h, pixel_m)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)
    az, alt = np.radians(azimuth_deg), np.radians(altitude_deg)
    return np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)


def projection_check() -> None:
    rng = np.random.default_rng(seed=1)
    lat = np.radians(rng.uniform(-89.999, -80.0, 100_000))
    lon = np.radians(rng.uniform(0, 360, 100_000))
    proj = pyproj.Proj("+proj=stere +lat_0=-90 +lat_ts=-90 +lon_0=0 +x_0=0 +y_0=0 +R=1737400 +units=m")
    px, py = proj(np.degrees(lon), np.degrees(lat))
    x, y = polar_stereo_forward(lat, lon)
    lat2, _ = polar_stereo_inverse(px, py)
    fwd_mm = np.max(np.hypot(x - px, y - py)) * 1000
    inv_mm = np.max(np.abs(lat2 - lat)) * 1_737_400 * 1000
    print(f"Projection vs pyproj, 100,000 points 80-90 S: forward worst {fwd_mm:.2e} mm, "
          f"inverse worst {inv_mm:.2e} mm")


def site_checks(sites: list[dict]) -> None:
    region = TerrainGrid.load(ARTIFACT_DIR / "region_80s_40m")
    print("\n| Site | 5 m vs 40 m: mean diff | RMS diff | Ground at site | Slope at site "
          "| Highest point within 1 km | Highest within 2 km | Near-field radius |")
    print("|---|---|---|---|---|---|---|---|")
    for s in sites:
        grid = TerrainGrid.load(ARTIFACT_DIR / s["id"], mmap=False)
        h = grid.heights_m
        blocks = h.reshape(400, 8, 400, 8).mean(axis=(1, 3))
        x = grid.x0_m + 3.5 * grid.pixel_m + 40.0 * np.arange(400)
        y = grid.y0_m - 3.5 * grid.pixel_m - 40.0 * np.arange(400)
        diff = blocks - region.sample_xy(*np.meshgrid(x, y))

        dz_dy, dz_dx = np.gradient(h.astype(float), grid.pixel_m)
        slope_deg = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
        # Site point (from the site list) in fractional pixel coordinates.
        site_col = (s["map_x_m"] - grid.x0_m) / grid.pixel_m
        site_row = (grid.y0_m - s["map_y_m"]) / grid.pixel_m
        rr, cc = int(round(site_row)), int(round(site_col))
        rows, cols = np.mgrid[0:h.shape[0], 0:h.shape[1]]
        dist = np.hypot(rows - site_row, cols - site_col) * grid.pixel_m
        highs = []
        for radius in (1000, 2000):
            masked = np.where(dist <= radius, h, -np.inf)
            r, c = np.unravel_index(np.argmax(masked), h.shape)
            highs.append(f"{h[r, c]:.0f} m, {dist[r, c] / 1000:.2f} km away")
        print(f"| {s['id']} {s['name']} | {diff.mean():+.2f} m | {np.sqrt((diff**2).mean()):.1f} m "
              f"| {s['ground_height_m']:.0f} m | {slope_deg[rr - 1:rr + 2, cc - 1:cc + 2].mean():.1f}° "
              f"| {highs[0]} | {highs[1]} | {s['near_field_radius_m'] / 1000:.2f} km |")

        fig, ax = plt.subplots(figsize=(5, 5))
        extent = [grid.x0_m / 1000, (grid.x0_m + 3199 * grid.pixel_m) / 1000,
                  (grid.y0_m - 3199 * grid.pixel_m) / 1000, grid.y0_m / 1000]
        ax.imshow(hillshade(h.astype(float), grid.pixel_m), cmap="gray", extent=extent)
        ax.plot(s["map_x_m"] / 1000, s["map_y_m"] / 1000, "r+", ms=14, mew=2)
        radius_km = s["near_field_radius_m"] / 1000
        ax.add_patch(plt.Circle((s["map_x_m"] / 1000, s["map_y_m"] / 1000), radius_km,
                                fill=False, color="r", lw=0.8))
        ax.set_title(f"{s['id']} {s['name']} (5 m), + = site, circle = {radius_km:.1f} km near field",
                     fontsize=9)
        ax.set_xlabel("map x (km)")
        ax.set_ylabel("map y (km)")
        fig.tight_layout()
        fig.savefig(IMG_DIR / f"terrain_{s['id']}.png", dpi=100)
        plt.close(fig)


def region_image(sites: list[dict]) -> None:
    region = TerrainGrid.load(ARTIFACT_DIR / "region_80s_40m")
    step = 8  # 320 m display pixels
    h = np.asarray(region.heights_m[::step, ::step], dtype=float)
    half = 304.0
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(hillshade(h, 40.0 * step), cmap="gray", extent=[-half, half, -half, half])
    for s in sites:
        ax.plot(s["map_x_m"] / 1000, s["map_y_m"] / 1000, "r+", ms=10, mew=2)
        ax.annotate(s["id"], (s["map_x_m"] / 1000, s["map_y_m"] / 1000), color="r",
                    xytext=(6, 6), textcoords="offset points", fontsize=8)
    ax.add_patch(plt.Circle((0, 0), 240, fill=False, color="y", lw=0.8))
    ax.set_title("80-90 S, 40 m LOLA (shaded relief). Yellow: 240 km = farthest horizon reach", fontsize=9)
    ax.set_xlabel("map x (km)")
    ax.set_ylabel("map y (km)")
    fig.tight_layout()
    fig.savefig(IMG_DIR / "terrain_region_80s.png", dpi=100)
    plt.close(fig)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    sites = json.loads(SITES_PATH.read_text(encoding="utf-8"))["sites"]
    projection_check()
    site_checks(sites)
    region_image(sites)
    print(f"\nwrote images to {IMG_DIR}")


if __name__ == "__main__":
    main()
