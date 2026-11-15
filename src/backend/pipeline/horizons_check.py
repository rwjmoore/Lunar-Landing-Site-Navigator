"""
Filename: pipeline/horizons_check.py
Description: Independent cross-check of the sky model against JPL Horizons
    (docs/physics/sky.md section 7, check 2). Queries the public Horizons API
    for apparent, airless azimuth/elevation of the Sun and Earth from test
    locations on the Moon, compares with our grid + topocentric conversion,
    and prints a Markdown table. Network access required; sends only the test
    coordinates and times below.

    Run from src/backend:  python -m pipeline.horizons_check
"""

import re
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime

import numpy as np

from app.astronomy.sky import SkyGrid, format_utc, sky_track
from app.coordinates.frames import LocalFrame

API_URL = "https://ssd.jpl.nasa.gov/api/horizons.api"
TEST_SITES_DEG = [(-89.5, 300.0), (-85.0, 10.0)]
TEST_TIMES_UTC = [
    datetime(2027, 3, 1, 0, tzinfo=UTC),
    datetime(2030, 6, 15, 12, tzinfo=UTC),
    datetime(2033, 9, 30, 6, tzinfo=UTC),
    datetime(2039, 12, 1, 18, tzinfo=UTC),
]
TARGETS = {"Sun": "10", "Earth": "399"}
TOLERANCE_DEG = 0.01  # approved in docs/physics/sky.md section 9
J2000 = datetime(2000, 1, 1, 12, tzinfo=UTC)


def julian_date(value: datetime) -> float:
    return 2451545.0 + (value - J2000).total_seconds() / 86400.0


def query_horizons(target_id: str, lat_deg: float, lon_deg: float) -> list[tuple[float, float]]:
    """Return [(azimuth_deg, elevation_deg)] for TEST_TIMES_UTC from Horizons."""
    params = {
        "format": "text",
        "COMMAND": f"'{target_id}'",
        "OBJ_DATA": "'NO'",
        "MAKE_EPHEM": "'YES'",
        "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'coord@301'",
        "COORD_TYPE": "'GEODETIC'",
        "SITE_COORD": f"'{lon_deg},{lat_deg},0'",
        "TLIST": "'" + " ".join(f"{julian_date(t):.6f}" for t in TEST_TIMES_UTC) + "'",
        "TLIST_TYPE": "'JD'",
        "QUANTITIES": "'4'",
        "ANG_FORMAT": "'DEG'",
        "APPARENT": "'AIRLESS'",
        "EXTRA_PREC": "'YES'",
        "TIME_TYPE": "'UT'",
    }
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=120) as response:
        text = response.read().decode("utf-8")
    block = text.split("$$SOE")[1].split("$$EOE")[0]
    rows = []
    for line in block.strip().splitlines():
        numbers = re.findall(r"-?\d+\.\d+", line.split(":", 2)[-1])
        rows.append((float(numbers[-2]), float(numbers[-1])))
    if len(rows) != len(TEST_TIMES_UTC):
        raise RuntimeError(f"expected {len(TEST_TIMES_UTC)} rows from Horizons, got {len(rows)}")
    return rows


def ours(grid: SkyGrid, lat_deg: float, lon_deg: float, body: str) -> list[tuple[float, float]]:
    frame = LocalFrame.at_site(np.radians(lat_deg), np.radians(lon_deg))
    out = []
    for t in TEST_TIMES_UTC:
        track = sky_track(grid, frame, t, duration_s=3600, step_s=3600)
        az = track.sun_azimuth if body == "Sun" else track.earth_azimuth
        el = track.sun_elevation if body == "Sun" else track.earth_elevation
        out.append((float(np.degrees(az[0])), float(np.degrees(el[0]))))
    return out


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # Markdown table uses °, Δ on any console
    grid = SkyGrid.load()
    print("| Site (lat, lon) | Body | Time (UTC) | Horizons az / el | Ours az / el | Δaz | Δel |")
    print("|---|---|---|---|---|---|---|")
    worst = 0.0
    for lat, lon in TEST_SITES_DEG:
        for body, target_id in TARGETS.items():
            reference = query_horizons(target_id, lat, lon)
            computed = ours(grid, lat, lon, body)
            for t, (h_az, h_el), (o_az, o_el) in zip(TEST_TIMES_UTC, reference, computed):
                d_az = (o_az - h_az + 180.0) % 360.0 - 180.0
                d_el = o_el - h_el
                # Azimuth error expressed as an on-sky angle (scaled by cos elevation).
                worst = max(worst, abs(d_el), abs(d_az) * np.cos(np.radians(h_el)))
                print(
                    f"| {lat}°, {lon}° | {body} | {format_utc(t)} | {h_az:.4f}° / {h_el:+.4f}° "
                    f"| {o_az:.4f}° / {o_el:+.4f}° | {d_az:+.5f}° | {d_el:+.5f}° |"
                )
    verdict = "PASS" if worst < TOLERANCE_DEG else "FAIL"
    print(f"\nWorst on-sky difference: {worst:.5f}° (tolerance {TOLERANCE_DEG}°): {verdict}")


if __name__ == "__main__":
    main()
