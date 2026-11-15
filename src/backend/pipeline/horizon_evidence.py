"""
Filename: pipeline/horizon_evidence.py
Description: Produces the review evidence for docs/physics/horizon.md
    section 9.1 on all 1,440 directions: stored-far-point accuracy across
    observer heights, near/far boundary sensitivity, step-halving convergence,
    runtime cost, what sets each site's horizon, yearly Sun/Earth results,
    and 360-degree horizon plots with a year of Sun and Earth tracks.

    Run from src/backend:  python -m pipeline.horizon_evidence
"""

import sys
import time

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from app.astronomy.sky import SkyGrid, parse_utc  # noqa: E402
from app.metrics.core import VISIBLE  # noqa: E402
from app.physics.analysis import MissionWindow, Vehicle, analyze  # noqa: E402
from app.physics.horizon import (  # noqa: E402
    FAR_STEP_M,
    MAX_RANGE_M,
    NEAR_RELATIVE_STEP,
    NEAR_STEP_M,
    TERRAIN_DIR,
    SiteTerrain,
    cast_rays,
    load_sites,
    near_distances,
    uniform_distances,
)
from app.terrain.grid import TerrainGrid  # noqa: E402
from pipeline import REPO_ROOT  # noqa: E402

IMG_DIR = REPO_ROOT / "docs" / "physics" / "img"
YEAR = MissionWindow(parse_utc("2030-01-01T00:00:00Z"), 365 * 86400, 3600)


def direct(site, near_grid, region, h, boundary, refine=1.0):
    frame = site.frame(h)
    near = cast_rays(frame, near_grid, near_distances(boundary, NEAR_STEP_M / refine,
                                                      NEAR_RELATIVE_STEP / refine))
    far = cast_rays(frame, region, uniform_distances(boundary, MAX_RANGE_M, FAR_STEP_M / refine))
    return np.maximum(near.elevation_rad, far.elevation_rad)


def deg_worst(a, b) -> float:
    return float(np.degrees(np.max(np.abs(a - b))))


def plot_site(site, a2, a10) -> None:
    fig, ax = plt.subplots(figsize=(11, 4.2))
    az = np.degrees(a2.sun_horizon.azimuth_rad)
    ax.plot(az, np.degrees(a2.sun_horizon.elevation_rad), color="0.15", lw=1.2, label="Terrain horizon, 2 m mast")
    ax.plot(az, np.degrees(a10.sun_horizon.elevation_rad), color="0.15", lw=0.8, ls="--",
            label="Terrain horizon, 10 m mast")
    sun_az, sun_el = np.degrees(a2.sky.sun_azimuth), np.degrees(a2.sky.sun_elevation)
    lit = a2.sun_visible == VISIBLE
    ax.scatter(sun_az[lit], sun_el[lit], s=0.4, color="#EF9F27", label="Sun (2030), visible")
    ax.scatter(sun_az[~lit], sun_el[~lit], s=0.4, color="#BA7517", alpha=0.25, label="Sun, blocked")
    e_az, e_el = np.degrees(a2.sky.earth_azimuth), np.degrees(a2.sky.earth_elevation)
    ax.scatter(e_az, e_el, s=0.4, color="#185FA5", label="Earth (2030)")
    ax.set_xlim(0, 360)
    ax.set_xticks(range(0, 361, 45))
    ax.set_xlabel("Azimuth (deg clockwise from north)")
    ax.set_ylabel("Elevation (deg)")
    ax.set_title(f"{site.id} {site.name}: 360° horizon with the 2030 Sun and Earth tracks", fontsize=10)
    ax.legend(loc="upper right", fontsize=7, markerscale=8, ncol=2)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(IMG_DIR / f"horizon_{site.id}.png", dpi=100)
    plt.close(fig)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    region = TerrainGrid.load(TERRAIN_DIR / "region_80s_40m")
    sky = SkyGrid.load()
    rows_checks, rows_year, rows_source = [], [], []
    for site in load_sites().values():
        t = SiteTerrain.load(site)
        r = site.near_field_radius_m

        timings = []
        for _ in range(3):
            fresh = SiteTerrain(site, t.near_grid, t.far)
            started = time.perf_counter()
            fresh.horizon(2.0)
            timings.append(time.perf_counter() - started)

        far_worst = max(deg_worst(t.horizon(h).elevation_rad, direct(site, t.near_grid, region, h, r))
                        for h in (0.0, 2.0, 7.5, 12.0, 20.0))
        boundary = deg_worst(t.horizon(2.0).elevation_rad, direct(site, t.near_grid, region, 2.0, 4000.0))
        step = deg_worst(direct(site, t.near_grid, region, 2.0, r),
                         direct(site, t.near_grid, region, 2.0, r, refine=2.0))
        rows_checks.append(f"| {site.id} | {far_worst:.4f}° | {boundary:.4f}° | {step:.4f}° | {min(timings):.2f} s |")

        p = t.horizon(2.0)
        d = p.blocking_distance_m
        rows_source.append(
            f"| {site.id} | {np.degrees(p.elevation_rad.min()):+.2f}° to {np.degrees(p.elevation_rad.max()):+.2f}° "
            f"| {np.mean(d < 1000):.0%} | {np.mean((d >= 1000) & ~p.from_far):.0%} | {np.mean(p.from_far):.0%} "
            f"| {int(p.no_data.sum())} |")

        a2 = analyze(t, sky, YEAR, Vehicle(2.0, 2.0), [])
        a10 = analyze(t, sky, YEAR, Vehicle(10.0, 10.0), [])
        m2, m10 = a2.metrics, a10.metrics
        rows_year.append(
            f"| {site.id} {site.name} | {m2['sun_visible_fraction'].value:.1%} | "
            f"{m10['sun_visible_fraction'].value:.1%} | {m2['max_continuous_darkness_hours'].value:.0f} h | "
            f"{m10['max_continuous_darkness_hours'].value:.0f} h | {m2['earth_visible_fraction'].value:.1%} | "
            f"{m2['max_continuous_earth_blackout_hours'].value:.0f} h |")
        plot_site(site, a2, a10)

    print("| Site | Stored far points vs full recompute (0-20 m) | Boundary moved to 4 km | Step halving | Near zone, 1,440 rays |")
    print("|---|---|---|---|---|")
    print("\n".join(rows_checks))
    print("\n| Site | Horizon range (2 m) | Set by terrain < 1 km | Near zone >= 1 km | Far zone | No-data directions |")
    print("|---|---|---|---|---|---|")
    print("\n".join(rows_source))
    print("\n| Site | Sun visible, 2 m mast | Sun visible, 10 m mast | Longest darkness, 2 m | Longest darkness, 10 m "
          "| Earth visible, 2 m | Longest Earth blackout, 2 m |")
    print("|---|---|---|---|---|---|---|")
    print("\n".join(rows_year))
    print(f"\nwrote horizon plots to {IMG_DIR}")


if __name__ == "__main__":
    main()
