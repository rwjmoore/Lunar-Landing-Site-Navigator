"""
Filename: app/planning/calendar.py
Description: Date-flexibility calendar (docs/physics/planning.md section 2):
    mission metrics and feasibility for EVERY candidate start date at once.

    The site's Sun/Earth visibility is computed once over the whole hourly sky
    grid; each candidate mission is then a window of that series. Results
    follow the approved metric definitions (docs/metrics.md) exactly for
    whole-hour missions sampled hourly:
      - a mission of D hours covers samples s .. s+D-1 at one hour each (the
        final sample at s+D has zero weight and contributes nothing);
      - fractions are over known samples; unknown samples break outage runs;
      - a constraint is unknown when coverage < 1.
    tests/test_planning.py checks equality with app.physics.analysis.analyze.
"""

from dataclasses import dataclass

import numpy as np

from app.astronomy.sky import SkyGrid
from app.metrics.core import OBSTRUCTED, UNKNOWN, VISIBLE
from app.physics.horizon import SiteTerrain
from app.physics.visibility import visibility


@dataclass(frozen=True)
class GridVisibility:
    """Sun/Earth visibility states for one site and vehicle over the whole sky grid."""

    sun: np.ndarray    # int8 VISIBLE / OBSTRUCTED / UNKNOWN, one per grid hour
    earth: np.ndarray


def grid_visibility(terrain: SiteTerrain, grid: SkyGrid, mast_m: float, antenna_m: float) -> GridVisibility:
    """Visibility of the Sun (vs the mast horizon) and Earth (vs the antenna horizon) at every grid hour."""
    frame = terrain.site.frame(0.0)
    sun_az, sun_el = frame.azimuth_elevation(grid.sun_m)
    earth_az, earth_el = frame.azimuth_elevation(grid.earth_m)
    return GridVisibility(visibility(terrain.horizon(mast_m), sun_az, sun_el),
                          visibility(terrain.horizon(antenna_m), earth_az, earth_el))


def joint_states(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Both bodies visible at once: obstructed if either is obstructed, else unknown
    if either is unknown, else visible."""
    out = np.full(a.shape, VISIBLE, dtype=np.int8)
    out[(a == UNKNOWN) | (b == UNKNOWN)] = UNKNOWN
    out[(a == OBSTRUCTED) | (b == OBSTRUCTED)] = OBSTRUCTED
    return out


@dataclass(frozen=True)
class WindowMetrics:
    """Per-window results (arrays over candidate starts). Hours; NaN = not computable."""

    visible_fraction: np.ndarray
    longest_outage_h: np.ndarray
    coverage: np.ndarray


def window_metrics(states: np.ndarray, starts: np.ndarray, length: int) -> WindowMetrics:
    """Visible fraction, longest obstructed run and coverage for windows
    states[s : s + length] at each start s (hourly samples, one hour each)."""
    starts = np.asarray(starts, dtype=np.int64)
    ends = starts + length - 1
    known = np.concatenate(([0], np.cumsum(states != UNKNOWN)))
    seen = np.concatenate(([0], np.cumsum(states == VISIBLE)))
    known_n = known[ends + 1] - known[starts]
    visible_n = seen[ends + 1] - seen[starts]
    with np.errstate(invalid="ignore", divide="ignore"):
        fraction = np.where(known_n > 0, visible_n / known_n, np.nan)
    longest = _longest_runs(states == OBSTRUCTED, starts, ends).astype(float)
    longest[known_n == 0] = np.nan
    return WindowMetrics(fraction, longest, known_n / length)


def _longest_runs(flags: np.ndarray, starts: np.ndarray, ends: np.ndarray) -> np.ndarray:
    """Length of the longest run of True inside each [start, end] window (inclusive).

    Combines (1) the longest run lying wholly inside the window, found with a
    sparse-table range maximum over run lengths, and (2) the runs clipped at
    the window's left and right edges.
    """
    edges = np.diff(np.concatenate(([0], flags.astype(np.int8), [0])))
    a = np.flatnonzero(edges == 1)           # run starts
    b = np.flatnonzero(edges == -1) - 1      # run ends (inclusive)
    result = np.zeros(len(starts), dtype=np.int64)
    if len(a) == 0:
        return result
    lengths = b - a + 1

    # (1) whole runs inside the window: run indices kl..kr.
    kl = np.searchsorted(a, starts, side="left")
    kr = np.searchsorted(b, ends, side="right") - 1
    valid = kl <= kr
    if valid.any():
        table = [lengths]
        while (1 << len(table)) <= len(lengths):
            prev, half = table[-1], 1 << (len(table) - 1)
            table.append(np.maximum(prev[:-half], prev[half:]))
        lo, hi = kl[valid], kr[valid]
        level = np.floor(np.log2(hi - lo + 1)).astype(np.int64)
        inside = np.empty(len(lo), dtype=np.int64)
        for j in np.unique(level):
            sel = level == j
            inside[sel] = np.maximum(table[j][lo[sel]], table[j][hi[sel] - (1 << j) + 1])
        result[valid] = inside

    # (2) the run containing the window start, and the run containing the window end.
    k = np.searchsorted(a, starts, side="right") - 1
    ok = (k >= 0) & (b[np.maximum(k, 0)] >= starts)
    left = np.where(ok, np.minimum(b[np.maximum(k, 0)], ends) - starts + 1, 0)
    k = np.searchsorted(a, ends, side="right") - 1
    ok = (k >= 0) & (b[np.maximum(k, 0)] >= ends)
    right = np.where(ok, ends - np.maximum(a[np.maximum(k, 0)], starts) + 1, 0)
    return np.maximum(result, np.maximum(left, right))


@dataclass(frozen=True)
class Calendar:
    """Metrics and feasibility for each candidate start (arrays over starts)."""

    start_index: np.ndarray
    sun: WindowMetrics
    earth: WindowMetrics
    status: np.ndarray            # 'feasible' / 'infeasible' / 'unknown'
    worst_margin_h: np.ndarray    # smallest signed margin across constraints (NaN if none/unknown)


def calendar(vis: GridVisibility, starts: np.ndarray, duration_hours: int,
             max_darkness_h: float | None, max_blackout_h: float | None) -> Calendar:
    """Evaluate every candidate start. Constraints follow docs/metrics.md section 4."""
    sun = window_metrics(vis.sun, starts, duration_hours)
    earth = window_metrics(vis.earth, starts, duration_hours)
    checks = []
    for limit, metrics in ((max_darkness_h, sun), (max_blackout_h, earth)):
        if limit is None:
            continue
        margin = limit - metrics.longest_outage_h
        known = (metrics.coverage >= 1.0) & ~np.isnan(margin)
        checks.append((margin, known))
    n = len(starts)
    if not checks:
        return Calendar(np.asarray(starts), sun, earth, np.full(n, "unknown", dtype=object), np.full(n, np.nan))
    failed = np.zeros(n, bool)
    unknown = np.zeros(n, bool)
    worst = np.full(n, np.inf)
    for margin, known in checks:
        failed |= known & (margin < 0)
        unknown |= ~known
        worst = np.minimum(worst, np.where(known, margin, np.nan))
    status = np.where(failed, "infeasible", np.where(unknown, "unknown", "feasible")).astype(object)
    return Calendar(np.asarray(starts), sun, earth, status, worst)
