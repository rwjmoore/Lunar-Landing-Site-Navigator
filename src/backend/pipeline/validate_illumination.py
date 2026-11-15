"""
Filename: pipeline/validate_illumination.py
Description: Validation against NASA's published south-pole illumination and
    Earth-visibility maps (Mazarico et al. 2011, 2016 build), as approved in
    docs/physics/validation.md.

    Their maps count a body as visible when ANY PART of its disk is above the
    horizon (from the PDS labels), so this script uses that rule here only:
    visible if centre elevation + disk angular radius > horizon. The app's own
    metrics keep the centre-point rule.

      A. Method check: 100 random points in 87-90 S (seeded), our ray casting
         on the 40 m regional map only, observer 0 m, hourly 2026-2040.
      B. The four demo sites with the full model (5 m near + 40 m far zone),
         observer 0 m, compared with NASA's value at the point and its
         min/max within 120 m.

    Run from src/backend:  python -m pipeline.validate_illumination
    Outputs: tables on stdout, data/validation/comparison_a.csv,
             docs/physics/img/validation_scatter.png
"""

import csv
import sys
import time
from datetime import timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402

from app.astronomy.sky import SkyGrid  # noqa: E402
from app.coordinates.frames import MOON_RADIUS_M, LocalFrame  # noqa: E402
from app.physics.horizon import (  # noqa: E402
    AZIMUTHS_RAD,
    MAX_RANGE_M,
    TERRAIN_DIR,
    HorizonProfile,
    SiteTerrain,
    cast_rays,
    load_sites,
)
from app.physics.visibility import horizon_at  # noqa: E402
from app.terrain.grid import TerrainGrid, polar_stereo_forward, polar_stereo_inverse  # noqa: E402
from pipeline import DATA_DIR, REPO_ROOT  # noqa: E402
from pipeline.checksums import verify  # noqa: E402

RAW_DIR = DATA_DIR / "raw" / "validation"
MANIFEST = DATA_DIR / "manifests" / "validation.json"
OUT_CSV = DATA_DIR / "validation" / "comparison_a.csv"
PLOT = REPO_ROOT / "docs" / "physics" / "img" / "validation_scatter.png"

SUN_RADIUS_M = 696_000e3
EARTH_RADIUS_M = 6_371e3
N_POINTS = 100
SEED = 2026
RHO_MIN_M = 10_000.0
RHO_MAX_M = 2 * MOON_RADIUS_M * np.tan(np.radians(1.5))  # 87 S
COARSE_SKIP_M = 80.0  # two 40 m pixels: skip the observer's own pixels
COARSE_STEP_M = 40.0
TOLERANCES = {"mean_pp": 3.0, "rms_pp": 8.0, "corr": 0.90}  # approved, validation.md section 6


def nasa_map(name: str) -> TerrainGrid:
    """NASA map as a bilinear-sampleable grid (orientation verified against terrain)."""
    with rasterio.open(RAW_DIR / f"{name}.LBL") as src:
        t = src.transform
        values = src.read(1).astype(np.float64) * src.scales[0] + src.offsets[0]
    return TerrainGrid(values, t.c + t.a / 2, t.f + t.e / 2, t.a)


def coarse_distances() -> np.ndarray:
    """80 m to 200 km; 0.5% of distance, max 40 m (same rule as the M2 near zone)."""
    out = [COARSE_SKIP_M]
    while out[-1] < MAX_RANGE_M:
        out.append(min(out[-1] + min(COARSE_STEP_M, out[-1] * 0.005), MAX_RANGE_M))
    return np.array(out)


def profile_from(rays) -> HorizonProfile:
    n = len(AZIMUTHS_RAD)
    return HorizonProfile(AZIMUTHS_RAD, rays.elevation_rad, rays.distance_m,
                          np.zeros(n, bool), rays.no_data, 0.0)


def any_part_visible(profile, frame, body_m, radius_m) -> np.ndarray:
    """Visible if any part of the disk is above the horizon (flat-horizon approximation)."""
    az, el = frame.azimuth_elevation(body_m)
    rho = np.arcsin(radius_m / np.linalg.norm(body_m - frame.origin, axis=1))
    horizon, unknown = horizon_at(profile, az)
    if unknown.any():
        raise ValueError("unknown horizon directions in validation")
    return el + rho > horizon


def centre_visible(profile, frame, body_m) -> np.ndarray:
    az, el = frame.azimuth_elevation(body_m)
    return el > horizon_at(profile, az)[0]


def stats(ours: np.ndarray, nasa: np.ndarray) -> dict:
    diff = 100 * (ours - nasa)
    return {"mean_pp": float(diff.mean()), "rms_pp": float(np.sqrt((diff**2).mean())),
            "corr": float(np.corrcoef(ours, nasa)[0, 1])}


def comparison_a(region, sky, nasa_sun, nasa_earth) -> list[dict]:
    rng = np.random.default_rng(SEED)
    distances = coarse_distances()
    rows = []
    while len(rows) < N_POINTS:
        rho = np.sqrt(rng.uniform(RHO_MIN_M**2, RHO_MAX_M**2))
        bearing = rng.uniform(0, 2 * np.pi)
        x, y = rho * np.sin(bearing), rho * np.cos(bearing)
        sun_ref = float(nasa_sun.sample_xy(x, y))
        if not sun_ref >= 0.01:
            continue  # permanent or near-permanent shadow: trivial agreement
        lat, lon = polar_stereo_inverse(x, y)
        ground = float(region.sample_xy(x, y))
        frame = LocalFrame.at_site(float(lat), float(lon), ground)
        profile = profile_from(cast_rays(frame, region, distances))
        sun = any_part_visible(profile, frame, sky.sun_m, SUN_RADIUS_M).mean()
        earth = any_part_visible(profile, frame, sky.earth_m, EARTH_RADIUS_M).mean()
        rows.append({"lat_deg": float(np.degrees(lat)), "lon_deg": float(np.degrees(lon)),
                     "x_m": x, "y_m": y, "ground_m": ground,
                     "ours_sun": float(sun), "nasa_sun": sun_ref,
                     "ours_earth": float(earth), "nasa_earth": float(nasa_earth.sample_xy(x, y))})
        if len(rows) % 20 == 0:
            print(f"  A: {len(rows)} points done", flush=True)
    return rows


def nasa_neighbourhood(grid: TerrainGrid, x: float, y: float, radius_m: float = 120.0) -> tuple[float, float]:
    col = (x - grid.x0_m) / grid.pixel_m
    row = (grid.y0_m - y) / grid.pixel_m
    r0, c0 = int(round(row)), int(round(col))
    k = int(np.ceil(radius_m / grid.pixel_m)) + 1
    rr, cc = np.mgrid[r0 - k:r0 + k + 1, c0 - k:c0 + k + 1]
    px = grid.x0_m + cc * grid.pixel_m
    py = grid.y0_m - rr * grid.pixel_m
    inside = np.hypot(px - x, py - y) <= radius_m
    values = grid.heights_m[rr[inside], cc[inside]]
    return float(values.min()), float(values.max())


def per_year_spread(visible: np.ndarray, sky: SkyGrid) -> float:
    """Range (max - min) of yearly visible fractions, in percentage points."""
    years = np.array([(sky.utc_start + timedelta(hours=i)).year for i in range(sky.size)])
    fractions = [visible[years == yr].mean() for yr in np.unique(years)]
    return 100 * (max(fractions) - min(fractions))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    verify(MANIFEST, RAW_DIR)
    sky = SkyGrid.load()
    region = TerrainGrid.load(TERRAIN_DIR / "region_80s_40m")
    nasa_sun = nasa_map("AVGVISIB_85S_060M_201608")
    nasa_earth = nasa_map("AVGVISIB_85S_060M_201608_EARTH")

    print("B: four demo sites, full model")
    site_rows = []
    for site in load_sites().values():
        t = SiteTerrain.load(site)
        profile = t.horizon(0.0)
        frame = site.frame(0.0)
        sun_vis = any_part_visible(profile, frame, sky.sun_m, SUN_RADIUS_M)
        earth_vis = any_part_visible(profile, frame, sky.earth_m, EARTH_RADIUS_M)
        mx, my = polar_stereo_forward(np.radians(site.latitude_deg), np.radians(site.longitude_deg_east))
        mx, my = float(mx), float(my)
        s_lo, s_hi = nasa_neighbourhood(nasa_sun, mx, my)
        e_lo, e_hi = nasa_neighbourhood(nasa_earth, mx, my)
        site_rows.append((site, sun_vis.mean(), float(nasa_sun.sample_xy(mx, my)), s_lo, s_hi,
                          earth_vis.mean(), float(nasa_earth.sample_xy(mx, my)), e_lo, e_hi,
                          centre_visible(profile, frame, sky.sun_m).mean(),
                          per_year_spread(sun_vis, sky)))

    print("A: 100 random points, 40 m terrain only")
    started = time.perf_counter()
    rows = comparison_a(region, sky, nasa_sun, nasa_earth)
    print(f"  A took {time.perf_counter() - started:.0f} s")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    ours_sun = np.array([r["ours_sun"] for r in rows]); nasa_s = np.array([r["nasa_sun"] for r in rows])
    ours_earth = np.array([r["ours_earth"] for r in rows]); nasa_e = np.array([r["nasa_earth"] for r in rows])
    print("\n| Comparison A (100 points) | Mean difference (ours − NASA) | RMS difference | Correlation | Pass? |")
    print("|---|---|---|---|---|")
    for label, ours, ref in (("Sunlight", ours_sun, nasa_s), ("Earth visibility", ours_earth, nasa_e)):
        s = stats(ours, ref)
        ok = (abs(s["mean_pp"]) <= TOLERANCES["mean_pp"] and s["rms_pp"] <= TOLERANCES["rms_pp"]
              and s["corr"] >= TOLERANCES["corr"])
        print(f"| {label} | {s['mean_pp']:+.2f} pp | {s['rms_pp']:.2f} pp | {s['corr']:.3f} | {'PASS' if ok else 'FAIL'} |")
    print(f"\nNASA sunlight range across the 100 points: {nasa_s.min():.1%} to {nasa_s.max():.1%}; "
          f"Earth: {nasa_e.min():.1%} to {nasa_e.max():.1%}")

    print("\n| Site | Sunlight: ours | NASA at point | NASA within 120 m | Earth: ours | NASA at point "
          "| NASA within 120 m | Ours, centre-point rule | Year-to-year spread (ours) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for (site, s_o, s_n, s_lo, s_hi, e_o, e_n, e_lo, e_hi, centre, spread) in site_rows:
        print(f"| {site.id} {site.name} | {s_o:.1%} | {s_n:.1%} | {s_lo:.1%}–{s_hi:.1%} | {e_o:.1%} | {e_n:.1%} "
              f"| {e_lo:.1%}–{e_hi:.1%} | {centre:.1%} | {spread:.1f} pp |")

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.8))
    for ax, ours, ref, title in ((axes[0], ours_sun, nasa_s, "Sunlight"), (axes[1], ours_earth, nasa_e, "Earth visibility")):
        ax.scatter(100 * ref, 100 * ours, s=12, color="#534AB7")
        ax.plot([0, 100], [0, 100], color="0.5", lw=0.8)
        s = stats(ours, ref)
        ax.set_title(f"{title}: mean {s['mean_pp']:+.1f} pp, RMS {s['rms_pp']:.1f} pp, r = {s['corr']:.3f}", fontsize=9)
        ax.set_xlabel("NASA map (% of time, any part of disk)")
        ax.set_ylabel("Our model, 40 m terrain (%)")
        ax.set_xlim(0, 100); ax.set_ylim(0, 100); ax.set_aspect("equal"); ax.grid(alpha=0.3)
    fig.suptitle("Comparison A: 100 random points in 87–90°S, hourly 2026–2040", fontsize=10)
    fig.tight_layout()
    fig.savefig(PLOT, dpi=100)
    print(f"\nwrote {OUT_CSV} and {PLOT}")


if __name__ == "__main__":
    main()
