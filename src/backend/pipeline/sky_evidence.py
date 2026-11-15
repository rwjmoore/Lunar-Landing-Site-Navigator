"""
Filename: pipeline/sky_evidence.py
Description: Produces the review evidence for docs/physics/sky.md section 7.1:
    worst-case differences between the grid method and SPICE computed at the
    site (check 1), physical sanity statistics over one year (check 3), and a
    plot of Sun/Earth azimuth and elevation at a polar test location.

    Run from src/backend:  python -m pipeline.sky_evidence
"""

import sys
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import spiceypy  # noqa: E402

from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, parse_utc, sky_track  # noqa: E402
from app.coordinates.frames import LocalFrame, site_to_position  # noqa: E402
from pipeline import REPO_ROOT  # noqa: E402
from pipeline.spice_kernels import load_kernels  # noqa: E402

SITES_DEG = [(-89.5, 300.0), (-85.0, 10.0), (-89.9, 123.4)]
PLOT_PATH = REPO_ROOT / "docs" / "physics" / "img" / "sky_tracks_m89.5_300.png"


def separation_deg(a, b):
    a = a / np.linalg.norm(a, axis=-1, keepdims=True)
    b = b / np.linalg.norm(b, axis=-1, keepdims=True)
    return np.degrees(np.arctan2(np.linalg.norm(np.cross(a, b), axis=-1), np.sum(a * b, axis=-1)))


def method_check(grid: SkyGrid, et: np.ndarray, samples: int = 2000) -> None:
    print("| Site (lat, lon) | Body | Samples | Worst difference vs SPICE at site |")
    print("|---|---|---|---|")
    indices = np.random.default_rng(seed=421).choice(grid.size, size=samples, replace=False)
    for lat, lon in SITES_DEG:
        site_m = site_to_position(np.radians(lat), np.radians(lon), 0.0)
        for body, column in (("SUN", "sun_m"), ("EARTH", "earth_m")):
            spice = np.array([
                np.asarray(spiceypy.spkcpo(body, t, "MOON_ME", "OBSERVER", "LT+S",
                                           site_m / 1000.0, "MOON", "MOON_ME")[0][:3]) * 1000.0
                for t in et[indices]
            ])
            ours = getattr(grid, column)[indices] - site_m
            worst = separation_deg(ours, spice).max()
            print(f"| {lat}°, {lon}° | {body.title()} | {samples} | {worst:.2e}° |")


def sanity(grid: SkyGrid) -> None:
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))
    start = parse_utc("2030-01-01T00:00:00Z")
    track = sky_track(grid, frame, start, duration_s=365 * 86400, step_s=3600)
    sun_el, earth_el = np.degrees(track.sun_elevation), np.degrees(track.earth_elevation)
    turns = np.ptp(np.unwrap(track.sun_azimuth)) / (2 * np.pi)
    earth_span = np.degrees(np.ptp(np.unwrap(track.earth_azimuth)))
    sun_au = np.linalg.norm(grid.sun_m, axis=1) / 1.495978707e11
    earth_km = np.linalg.norm(grid.earth_m, axis=1) / 1000.0
    print("\n| Check (site -89.5°, 300°, year 2030) | Expected | Measured |")
    print("|---|---|---|")
    print(f"| Sun elevation range | within about ±2° | {sun_el.min():+.2f}° to {sun_el.max():+.2f}° |")
    print(f"| Sun azimuth turns per year | about 365/29.53 = 12.36 | {turns:.2f} |")
    print(f"| Earth elevation range | within a few degrees (libration) | "
          f"{earth_el.min():+.2f}° to {earth_el.max():+.2f}° |")
    print(f"| Earth azimuth span | wobbles, never a full turn | {earth_span:.1f}° |")
    print(f"| Sun distance, whole grid | about 1 AU | {sun_au.min():.4f} to {sun_au.max():.4f} AU |")
    print(f"| Earth distance, whole grid | about 356,000 to 407,000 km | "
          f"{earth_km.min():,.0f} to {earth_km.max():,.0f} km |")


def plot(grid: SkyGrid) -> None:
    frame = LocalFrame.at_site(np.radians(-89.5), np.radians(300.0))
    start = parse_utc("2030-01-01T00:00:00Z")
    track = sky_track(grid, frame, start, duration_s=90 * 86400, step_s=3600)
    days = np.arange(len(track.timestamps_utc)) / 24.0
    fig, (ax_el, ax_az) = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    ax_el.plot(days, np.degrees(track.sun_elevation), label="Sun", color="#BA7517")
    ax_el.plot(days, np.degrees(track.earth_elevation), label="Earth", color="#185FA5")
    ax_el.axhline(0, color="0.6", lw=0.8)
    ax_el.set_ylabel("Elevation (deg)")
    ax_el.legend(loc="upper right")
    ax_az.plot(days, np.degrees(track.sun_azimuth), ".", ms=1.5, color="#BA7517")
    ax_az.plot(days, np.degrees(track.earth_azimuth), ".", ms=1.5, color="#185FA5")
    ax_az.set_ylabel("Azimuth (deg, from north)")
    ax_az.set_xlabel(f"Days after {start:%Y-%m-%d} UTC")
    ax_az.set_ylim(0, 360)
    fig.suptitle("Sun and Earth seen from (-89.5°, 300°E), hourly, DE421 sky grid")
    fig.tight_layout()
    PLOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(PLOT_PATH, dpi=110)
    print(f"\nwrote {PLOT_PATH}")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    load_kernels()
    grid = SkyGrid.load()
    with np.load(DEFAULT_SKY_GRID_PATH) as data:
        et = data["et_tdb_s"]
    method_check(grid, et)
    sanity(grid)
    plot(grid)


if __name__ == "__main__":
    main()
