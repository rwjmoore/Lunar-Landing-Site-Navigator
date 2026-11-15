"""
Filename: app/planning/rescue.py
Description: Mission rescue (docs/physics/planning.md section 4): for a mission
    that fails (or is uncertain against) its limits, search for the smallest
    single change that makes it pass, and quantify the trade-off:

      - a taller solar mast (fixes darkness) / a taller antenna (fixes Earth
        blackout): the smallest height in 0.5 m steps up to 20 m, found by
        bisection. Valid because raising the observer never raises the terrain
        horizon (tested in M2), so outages never lengthen with height;
      - a different start date: the nearest earlier and later start that passes,
        searched hourly within +/- max_shift_days, at the same heights;
      - a nearby point: candidates on a grid within +/- 800 m are SCREENED with
        a cheap approximate horizon (1-degree rays; candidate's own terrain to
        2 km plus the original point's horizon beyond), then the most promising
        are VERIFIED with the full exact horizon at the requested heights. Only
        verified results are reported.

    Each option changes ONE thing; the rest of the mission stays as requested.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from app.astronomy.sky import SkyGrid, format_utc
from app.coordinates.frames import TWO_PI
from app.physics.analysis import MissionWindow, Vehicle
from app.physics.horizon import MAX_OBSERVER_HEIGHT_M, MAX_RANGE_M, HorizonProfile, cast_rays, near_distances, \
    uniform_distances
from app.physics.visibility import visibility
from app.planning.calendar import calendar, grid_visibility, window_metrics
from app.terrain.grid import TerrainGrid, polar_stereo_forward, polar_stereo_inverse

HEIGHT_STEP_M = 0.5
DEFAULT_MAX_SHIFT_DAYS = 60
NEARBY_SPACING_M = 200.0
NEARBY_HALF_STEPS = 4          # 9 x 9 grid: +/- 800 m
SCREEN_AZIMUTHS = np.arange(360) * (TWO_PI / 360)
SCREEN_NEAR_M = 2_000.0
VERIFY_BUDGET = 2              # full exact horizons computed at most this many candidates
WORKERS = 4                    # candidates processed in parallel (NumPy releases the GIL for the heavy work)
# Screening distances on the 40 m map: from two pixels (80 m) to 2 km, step 1% of distance up to 40 m.
_SCREEN_REGION_DISTANCES = near_distances(SCREEN_NEAR_M, 40.0, 0.01)
_SCREEN_REGION_DISTANCES = _SCREEN_REGION_DISTANCES[_SCREEN_REGION_DISTANCES >= 80.0]


@dataclass(frozen=True)
class Outcome:
    """Metrics and verdict of one candidate mission (hours; None = not computable)."""

    sun_visible_fraction: float | None
    max_darkness_h: float | None
    earth_visible_fraction: float | None
    max_blackout_h: float | None
    status: str


@dataclass(frozen=True)
class Option:
    kind: str            # 'mast' | 'antenna' | 'date_earlier' | 'date_later' | 'move_nearest' | 'move_best'
    fixes: bool          # True if the mission passes every limit with this change
    change: dict
    outcome: Outcome
    text: str


@dataclass(frozen=True)
class RescueResult:
    baseline: Outcome
    options: list[Option]
    notes: list[str] = field(default_factory=list)


def _verdict(darkness, blackout, sun_cov, earth_cov, max_dark, max_black) -> str:
    checks = [(max_dark, darkness, sun_cov), (max_black, blackout, earth_cov)]
    checks = [(lim, val, cov) for lim, val, cov in checks if lim is not None]
    if not checks:
        return "unknown"
    if any(val is not None and cov >= 1 and val > lim for lim, val, cov in checks):
        return "infeasible"
    if any(val is None or cov < 1 for lim, val, cov in checks):
        return "unknown"
    return "feasible"


def _nan_to_none(x) -> float | None:
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


def _outcome(sun_states, earth_states, length, max_dark, max_black) -> Outcome:
    s = window_metrics(sun_states, np.array([0]), length)
    e = window_metrics(earth_states, np.array([0]), length)
    dark, black = _nan_to_none(s.longest_outage_h[0]), _nan_to_none(e.longest_outage_h[0])
    return Outcome(_nan_to_none(s.visible_fraction[0]), dark, _nan_to_none(e.visible_fraction[0]), black,
                   _verdict(dark, black, s.coverage[0], e.coverage[0], max_dark, max_black))


class _Mission:
    """The requested mission's window on the sky grid, seen from one site."""

    def __init__(self, terrain, grid: SkyGrid, window: MissionWindow):
        self.terrain, self.grid = terrain, grid
        start = grid.mission_indices(window.start_utc, window.duration_s, window.step_s)[0]
        if window.step_s != 3600 or window.duration_s % 3600:
            raise ValueError("mission rescue needs hourly sampling and a whole number of hours")
        self.length = int(window.duration_s // 3600)
        self.index = np.arange(start, start + self.length + 1)
        frame = terrain.site.frame(0.0)
        self.sun_az, self.sun_el = frame.azimuth_elevation(grid.sun_m[self.index])
        self.earth_az, self.earth_el = frame.azimuth_elevation(grid.earth_m[self.index])

    def sun(self, mast_m: float) -> np.ndarray:
        return visibility(self.terrain.horizon(mast_m), self.sun_az, self.sun_el)

    def earth(self, antenna_m: float) -> np.ndarray:
        return visibility(self.terrain.horizon(antenna_m), self.earth_az, self.earth_el)


def _smallest_height(passes, start_m: float) -> float | None:
    """Smallest height on the 0.5 m grid above start_m (up to 20 m) for which passes(h)
    is True, assuming passes is monotone in height. None if even 20 m fails."""
    heights = np.arange(np.floor(start_m / HEIGHT_STEP_M + 1) * HEIGHT_STEP_M,
                        MAX_OBSERVER_HEIGHT_M + HEIGHT_STEP_M / 2, HEIGHT_STEP_M)
    if len(heights) == 0 or not passes(float(heights[-1])):
        return None
    lo, hi = 0, len(heights) - 1   # invariant: heights[hi] passes
    while lo < hi:
        mid = (lo + hi) // 2
        if passes(float(heights[mid])):
            hi = mid
        else:
            lo = mid + 1
    return float(heights[lo])


def rescue(terrain, grid: SkyGrid, window: MissionWindow, vehicle: Vehicle,
           max_darkness_h: float | None, max_blackout_h: float | None,
           region: TerrainGrid | None = None, make_terrain: Callable | None = None,
           max_shift_days: int = DEFAULT_MAX_SHIFT_DAYS) -> RescueResult:
    """`terrain` is a SiteTerrain or PointTerrain. `region` (the 40 m map) and
    `make_terrain(lat_deg, lon_deg)` -> PointTerrain enable the nearby-point search."""
    mission = _Mission(terrain, grid, window)
    L = mission.length
    mast, antenna = vehicle.solar_panel_mast_height_m, vehicle.antenna_height_m
    sun0, earth0 = mission.sun(mast), mission.earth(antenna)
    baseline = _outcome(sun0, earth0, L, max_darkness_h, max_blackout_h)
    options: list[Option] = []
    notes: list[str] = []
    if max_darkness_h is None and max_blackout_h is None:
        return RescueResult(baseline, [], ["No limits were given, so there is nothing to rescue."])
    if baseline.status == "feasible":
        notes.append("The mission already meets every limit; the options below show how much slack each change adds.")

    # -- taller mast / antenna --------------------------------------------------------
    for kind, limit, current, states_for, other in (
        ("mast", max_darkness_h, mast, mission.sun, earth0),
        ("antenna", max_blackout_h, antenna, mission.earth, sun0),
    ):
        if limit is None:
            continue
        value = baseline.max_darkness_h if kind == "mast" else baseline.max_blackout_h
        if value is not None and value <= limit:
            continue  # this limit already passes; a taller mast/antenna isn't needed for it

        def passes(h, states_for=states_for, limit=limit):
            m = window_metrics(states_for(h), np.array([0]), L)
            return m.coverage[0] >= 1 and m.longest_outage_h[0] <= limit
        h = _smallest_height(passes, current)
        label = "solar mast" if kind == "mast" else "antenna"
        if h is None:
            options.append(Option(kind, False, {f"{label.replace(' ', '_')}_height_m": None},
                                  baseline, f"No {label} height up to {MAX_OBSERVER_HEIGHT_M:g} m meets the limit."))
            continue
        changed = states_for(h)
        outcome = (_outcome(changed, other, L, max_darkness_h, max_blackout_h) if kind == "mast"
                   else _outcome(other, changed, L, max_darkness_h, max_blackout_h))
        before, after = (baseline.max_darkness_h, outcome.max_darkness_h) if kind == "mast" else \
            (baseline.max_blackout_h, outcome.max_blackout_h)
        what = "darkness" if kind == "mast" else "Earth blackout"
        options.append(Option(kind, outcome.status == "feasible",
                              {f"{label.replace(' ', '_')}_height_m": h},
                              outcome, f"Raise the {label} from {current:g} m to {h:g} m: longest {what} "
                                       f"{before:.0f} h → {after:.0f} h."))

    # -- different start date -----------------------------------------------------------
    start = int(mission.index[0])
    shift = max_shift_days * 24
    lo, hi = max(0, start - shift), min(grid.size - L - 1, start + shift)
    vis = grid_visibility(terrain, grid, mast, antenna)
    starts = np.arange(lo, hi + 1)
    cal = calendar(vis, starts, L, max_darkness_h, max_blackout_h)
    feasible = starts[cal.status == "feasible"]
    for kind, candidates in (("date_earlier", feasible[feasible < start][::-1]), ("date_later", feasible[feasible > start])):
        if len(candidates) == 0:
            continue
        s = int(candidates[0])
        i = s - lo
        outcome = Outcome(_nan_to_none(cal.sun.visible_fraction[i]), _nan_to_none(cal.sun.longest_outage_h[i]),
                          _nan_to_none(cal.earth.visible_fraction[i]), _nan_to_none(cal.earth.longest_outage_h[i]),
                          "feasible")
        hours = s - start
        when = format_utc(grid.utc_start + timedelta(hours=s))
        options.append(Option(kind, True, {"start_utc": when, "shift_hours": hours},
                              outcome, f"Start {abs(hours) / 24:.1f} days {'earlier' if hours < 0 else 'later'}, "
                                       f"at {when}: the mission meets every limit."))
    if not len(feasible):
        notes.append(f"No start within ±{max_shift_days} days meets every limit with the current heights.")

    # -- nearby point ---------------------------------------------------------------------
    if region is None or make_terrain is None:
        notes.append("Nearby points were not searched (the regional terrain is not loaded on this server).")
    else:
        options.extend(_nearby(terrain, mission, grid, region, make_terrain, mast, antenna,
                               max_darkness_h, max_blackout_h, notes))
    return RescueResult(baseline, options, notes)


def _margin(o: Outcome, max_darkness_h, max_blackout_h) -> float:
    """Smallest signed margin across the enabled limits (larger is better)."""
    margins = [lim - val for lim, val in ((max_darkness_h, o.max_darkness_h), (max_blackout_h, o.max_blackout_h))
               if lim is not None and val is not None]
    return min(margins) if margins else -np.inf


def _screen_horizon(candidate, region: TerrainGrid, origin_far: HorizonProfile, height: float) -> HorizonProfile:
    """Cheap approximate horizon for RANKING only: the candidate's own terrain out to
    2 km (5 m map where available, plus the 40 m map), combined with the original
    point's horizon beyond 2 km, on 1-degree rays."""
    frame = candidate.site.frame(height)
    near = cast_rays(frame, region, _SCREEN_REGION_DISTANCES, SCREEN_AZIMUTHS).elevation_rad
    if candidate.near_grid is not None and candidate.site.near_field_radius_m > 10.0:
        fine = cast_rays(frame, candidate.near_grid,
                         near_distances(min(SCREEN_NEAR_M, candidate.site.near_field_radius_m), 5.0, 0.01),
                         SCREEN_AZIMUTHS).elevation_rad
        near = np.maximum(near, fine)
    elevation = np.maximum(near, origin_far.elevation_rad)
    n = len(SCREEN_AZIMUTHS)
    return HorizonProfile(SCREEN_AZIMUTHS, elevation, np.zeros(n), np.zeros(n, bool), np.zeros(n, bool), height)


def _nearby(origin, mission: "_Mission", grid: SkyGrid, region: TerrainGrid, make_terrain, mast, antenna,
            max_darkness_h, max_blackout_h, notes: list[str]) -> list[Option]:
    """Screen a 9 x 9 grid (200 m spacing) around the point, then verify the most
    promising candidates with the full exact horizon. Returns 'move' options."""
    site = origin.site
    ox, oy = (float(v) for v in polar_stereo_forward(np.radians(site.latitude_deg), np.radians(site.longitude_deg_east)))
    far_distances = uniform_distances(SCREEN_NEAR_M, MAX_RANGE_M, 40.0)
    origin_far = {}
    for h in {mast, antenna}:
        rays = cast_rays(site.frame(h), region, far_distances, SCREEN_AZIMUTHS)
        n = len(SCREEN_AZIMUTHS)
        origin_far[h] = HorizonProfile(SCREEN_AZIMUTHS, rays.elevation_rad, rays.distance_m, np.ones(n, bool),
                                       rays.no_data, h)

    def screen(offset):
        dx, dy = offset
        lat, lon = (float(np.degrees(v)) for v in polar_stereo_inverse(ox + dx, oy + dy))
        try:
            candidate = make_terrain(lat, lon)
        except ValueError:
            return None  # outside coverage
        frame = candidate.site.frame(0.0)
        s_az, s_el = frame.azimuth_elevation(grid.sun_m[mission.index])
        e_az, e_el = frame.azimuth_elevation(grid.earth_m[mission.index])
        horizons = {h: _screen_horizon(candidate, region, origin_far[h], h) for h in {mast, antenna}}
        sun = visibility(horizons[mast], s_az, s_el)
        earth = visibility(horizons[antenna], e_az, e_el)
        o = _outcome(sun, earth, mission.length, max_darkness_h, max_blackout_h)
        return candidate, float(np.hypot(dx, dy)), o, (s_az, s_el, e_az, e_el)

    steps = np.arange(-NEARBY_HALF_STEPS, NEARBY_HALF_STEPS + 1) * NEARBY_SPACING_M
    offsets = [(dx, dy) for dy in steps for dx in steps if dx or dy]
    with ThreadPoolExecutor(WORKERS) as pool:
        screened = [s for s in pool.map(screen, offsets) if s is not None]
    if not screened:
        notes.append("No nearby points lie inside the covered area.")
        return []

    # Verify: nearest screened passes first, then the best margins, within the budget.
    passing = sorted((c for c in screened if c[2].status == "feasible"), key=lambda c: c[1])
    by_margin = sorted(screened, key=lambda c: -_margin(c[2], max_darkness_h, max_blackout_h))
    order, seen = [], set()
    for c in passing[:2] + by_margin:
        if id(c[0]) not in seen:
            order.append(c)
            seen.add(id(c[0]))
    def verify(item):
        candidate, distance, _, (s_az, s_el, e_az, e_el) = item
        o = _outcome(visibility(candidate.horizon(mast), s_az, s_el),
                     visibility(candidate.horizon(antenna), e_az, e_el), mission.length, max_darkness_h, max_blackout_h)
        return candidate, distance, o

    with ThreadPoolExecutor(WORKERS) as pool:
        verified = list(pool.map(verify, order[:VERIFY_BUDGET]))

    options = []
    exact_passing = [v for v in verified if v[2].status == "feasible"]
    if not exact_passing:
        best = max(verified, key=lambda v: _margin(v[2], max_darkness_h, max_blackout_h))
        notes.append(f"No nearby point within {NEARBY_HALF_STEPS * NEARBY_SPACING_M:.0f} m was found that meets every "
                     f"limit (checked {len(screened)} points, verified {len(verified)} exactly). The closest call: "
                     f"{_describe_move(origin, best[0], best[1], best[2])}")
        return options
    nearest = min(exact_passing, key=lambda v: v[1])
    best = max(exact_passing, key=lambda v: _margin(v[2], max_darkness_h, max_blackout_h))
    for kind, (candidate, distance, o) in (("move_nearest", nearest), ("move_best", best)):
        if kind == "move_best" and candidate is nearest[0]:
            continue
        bearing, _ = origin.site.frame(0.0).azimuth_elevation(candidate.site.frame(0.0).origin)
        options.append(Option(kind, True, {
            "latitude_deg": round(candidate.site.latitude_deg, 6),
            "longitude_deg_east": round(candidate.site.longitude_deg_east, 6),
            "distance_m": round(distance, 1),
            "bearing_deg": round(float(np.degrees(bearing)), 1),
            "ground_m": round(candidate.site.ground_height_m, 1),
            "terrain_detail": candidate.detail,
        }, o, ("Move " if kind == "move_nearest" else "Best nearby point: move ")
            + _describe_move(origin, candidate, distance, o)))
    return options


def _describe_move(origin, candidate, distance: float, o: Outcome) -> str:
    bearing, _ = origin.site.frame(0.0).azimuth_elevation(candidate.site.frame(0.0).origin)
    parts = [f"{distance:.0f} m toward azimuth {np.degrees(bearing):.0f}° (ground {candidate.site.ground_height_m:.0f} m"
             f", {candidate.detail} detail)"]
    if o.max_darkness_h is not None:
        parts.append(f"longest darkness {o.max_darkness_h:.0f} h")
    if o.max_blackout_h is not None:
        parts.append(f"longest Earth blackout {o.max_blackout_h:.0f} h")
    return ": ".join([parts[0], ", ".join(parts[1:])]) + "."
