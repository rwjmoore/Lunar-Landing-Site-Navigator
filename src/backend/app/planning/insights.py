"""
Filename: app/planning/insights.py
Description: Plain-language explanations of an analysis (docs/physics/planning.md
    section 3): rise/set events, time until the next change at every sample,
    joint Sun + Earth windows, and for the worst outages, which directions the
    body was hidden in and which terrain blocked it.

    Everything is derived from an Assessment (app/physics/analysis.py); no new
    physics. Joint metrics reuse the metric framework's classes.
"""

from dataclasses import dataclass, field, replace

import numpy as np

from app.coordinates.frames import MOON_RADIUS_M, TWO_PI
from app.metrics.core import OBSTRUCTED, UNKNOWN, VISIBLE, EvaluationContext
from app.metrics.visibility import LongestOutage, VisibleFraction
from app.physics.analysis import Assessment
from app.physics.horizon import HorizonProfile, SiteInfo
from app.physics.visibility import horizon_at
from app.planning.calendar import joint_states

NEAR_TERRAIN_M = 1000.0  # "near the lander" threshold used in explanations
BODY_NAMES = {"sun": "Sun", "earth": "Earth"}


@dataclass(frozen=True)
class Event:
    time_utc: str
    body: str      # 'sun' / 'earth'
    event: str     # 'rise' / 'set' (visible <-> obstructed; changes to/from unknown are not events)


@dataclass(frozen=True)
class Blocker:
    """The terrain that hid a body for the most hours of an outage: the 10-degree
    azimuth sector holding the body longest, and that sector's highest horizon point."""

    sector_from_deg: float
    sector_to_deg: float
    hours: float         # hidden hours with the body in this sector
    azimuth_deg: float   # direction of the sector's highest horizon point
    distance_m: float    # distance to that terrain
    latitude_deg: float
    longitude_deg_east: float
    zone: str            # 'near' (< 1 km) or 'far'


@dataclass(frozen=True)
class OutageExplanation:
    body: str
    start_utc: str
    end_utc: str
    duration_h: float
    boundary_truncated: bool
    azimuth_from_deg: float       # body azimuth range while hidden (clockwise)
    azimuth_to_deg: float
    max_deficit_deg: float        # how far below the terrain horizon the body went
    near_share: float             # share of hidden hours blocked by terrain < 1 km away
    below_limb_share: float       # share of hidden hours below the Moon's own curved horizon
    dominant: Blocker
    text: str


@dataclass(frozen=True)
class Insights:
    events: list[Event]
    sun_hours_to_change: list[float | None]
    earth_hours_to_change: list[float | None]
    joint_visible_fraction: float | None
    longest_joint_window_h: float | None
    longest_joint_window: tuple[str, str] | None
    outages: list[OutageExplanation]
    summary: list[str] = field(default_factory=list)


def explain(assessment: Assessment, site: SiteInfo) -> Insights:
    a = assessment
    times = a.sky.timestamps_utc
    step_h = a.window.step_s / 3600.0
    events = _events(a.sun_visible, times, "sun") + _events(a.earth_visible, times, "earth")
    events.sort(key=lambda e: e.time_utc)

    context = EvaluationContext.from_window(a.window.duration_s, a.window.step_s, {
        "joint": joint_states(a.sun_visible, a.earth_visible),
        # Longest joint WINDOW = longest run of "visible" = longest outage of the inverted series.
        "joint_inverted": _invert(joint_states(a.sun_visible, a.earth_visible)),
    })
    joint_fraction = VisibleFraction("joint_visible_fraction", "Sun and Earth together", "joint").compute(context)
    joint_window = LongestOutage("longest_joint_window_hours", "Longest joint window", "joint_inverted").compute(context)
    window_span = None
    if joint_window.worst_interval is not None:
        window_span = (times[joint_window.worst_interval.start_index], times[joint_window.worst_interval.end_index])

    outages = []
    for body, metric_id, states, az, el, profile in (
        ("sun", "max_continuous_darkness_hours", a.sun_visible, a.sky.sun_azimuth, a.sky.sun_elevation, a.sun_horizon),
        ("earth", "max_continuous_earth_blackout_hours", a.earth_visible, a.sky.earth_azimuth,
         a.sky.earth_elevation, a.earth_horizon),
    ):
        interval = a.metrics[metric_id].worst_interval
        if interval is not None:
            outages.append(_explain_outage(body, interval, states, az, el, profile, site, times, step_h,
                                           a.metrics[metric_id].value))

    insights = Insights(
        events=events,
        sun_hours_to_change=_hours_to_change(a.sun_visible, step_h),
        earth_hours_to_change=_hours_to_change(a.earth_visible, step_h),
        joint_visible_fraction=joint_fraction.value,
        longest_joint_window_h=joint_window.value,
        longest_joint_window=window_span,
        outages=outages,
    )
    return replace(insights, summary=_summary(a, insights))


def _invert(states: np.ndarray) -> np.ndarray:
    out = states.copy()
    out[states == VISIBLE] = OBSTRUCTED
    out[states == OBSTRUCTED] = VISIBLE
    return out


def _events(states: np.ndarray, times: list[str], body: str) -> list[Event]:
    out = []
    for i in range(1, len(states)):
        before, after = states[i - 1], states[i]
        if before == OBSTRUCTED and after == VISIBLE:
            out.append(Event(times[i], body, "rise"))
        elif before == VISIBLE and after == OBSTRUCTED:
            out.append(Event(times[i], body, "set"))
    return out


def _hours_to_change(states: np.ndarray, step_h: float) -> list[float | None]:
    """Hours from each sample until the state next differs; None if it doesn't
    change before the mission ends, or if the state is unknown."""
    n = len(states)
    out: list[float | None] = [None] * n
    next_change = None
    for i in range(n - 1, -1, -1):
        if i + 1 < n and states[i + 1] != states[i]:
            next_change = i + 1
        out[i] = None if states[i] == UNKNOWN or next_change is None else (next_change - i) * step_h
    return out


def _circular_range(degrees: np.ndarray) -> tuple[float, float]:
    """Smallest clockwise arc [from, to] containing all azimuths (handles the 0/360 seam)."""
    s = np.sort(np.mod(degrees, 360.0))
    if len(s) == 1:
        return float(s[0]), float(s[0])
    gaps = np.diff(np.concatenate((s, [s[0] + 360.0])))
    k = int(np.argmax(gaps))
    return float(s[(k + 1) % len(s)]), float(s[k])


def _explain_outage(body, interval, states, az, el, profile: HorizonProfile, site: SiteInfo,
                    times, step_h, duration_h) -> OutageExplanation:
    idx = np.arange(interval.start_index, interval.end_index + 1)
    idx = idx[states[idx] == OBSTRUCTED]
    horizon, _ = horizon_at(profile, az[idx])
    deficit = np.degrees(horizon - el[idx])
    n_bins = len(profile.azimuth_rad)
    bins = np.rint(np.mod(az[idx], TWO_PI) / (TWO_PI / n_bins)).astype(int) % n_bins
    near_share = float(np.mean(profile.blocking_distance_m[bins] < NEAR_TERRAIN_M))
    # The Moon's own curved horizon for this observer (bare sphere, no terrain):
    # a body below it is hidden by the Moon itself; no mast or short move helps.
    observer_height = max(site.ground_height_m + profile.observer_height_m, 1e-3)
    limb = -np.arccos(MOON_RADIUS_M / (MOON_RADIUS_M + observer_height))
    below_limb_share = float(np.mean(el[idx] < limb))

    # Dominant blocker: the 10-degree sector holding the body longest, and its highest horizon point.
    sectors = (np.degrees(np.mod(az[idx], TWO_PI)) // 10).astype(int)
    values, counts = np.unique(sectors, return_counts=True)
    sector = int(values[np.argmax(counts)])
    in_sector = np.flatnonzero((np.degrees(profile.azimuth_rad) // 10).astype(int) == sector)
    top = int(in_sector[np.argmax(profile.elevation_rad[in_sector])])
    top_az = float(profile.azimuth_rad[top])
    top_distance = float(profile.blocking_distance_m[top])
    direction = site.frame(0.0).great_circle_direction(top_az, top_distance / MOON_RADIUS_M)
    lat = float(np.degrees(np.arcsin(np.clip(direction[2], -1, 1))))
    lon = float(np.degrees(np.mod(np.arctan2(direction[1], direction[0]), TWO_PI)))
    zone = "near" if top_distance < NEAR_TERRAIN_M else "far"
    dominant = Blocker(sector * 10.0, sector * 10.0 + 10.0, float(counts.max() * step_h),
                       round(float(np.degrees(top_az)), 2), round(top_distance, 1), round(lat, 6), round(lon, 6), zone)

    az_from, az_to = _circular_range(np.degrees(az[idx]))
    name = BODY_NAMES[body]
    kind = "darkness" if body == "sun" else "Earth blackout"
    where = (f"terrain {top_distance:.0f} m away, close to the lander" if zone == "near"
             else f"terrain {top_distance / 1000:.1f} km away")
    text = (f"The longest {kind} ({duration_h:.0f} h, from {times[interval.start_index]}) happened while the "
            f"{name} moved from azimuth {az_from:.0f}° to {az_to:.0f}°, up to {deficit.max():.2f}° below the "
            f"terrain horizon. It spent longest ({dominant.hours:.0f} h) between azimuth {sector * 10}° and "
            f"{sector * 10 + 10}°, where the horizon is set by {where} (around {abs(lat):.3f}°S, {lon:.3f}°E).")
    if below_limb_share >= 0.5:
        text += (f" For {below_limb_share:.0%} of the hidden hours the {name} was below the Moon's own curved "
                 f"horizon, so no mast height or short move could have helped.")
    elif near_share >= 0.5:
        text += f" {near_share:.0%} of the hidden hours were blocked by terrain within 1 km, which a taller mast can clear."
    if interval.boundary_truncated:
        text += " It touches the mission boundary, so it may last longer."
    return OutageExplanation(body, times[interval.start_index], times[interval.end_index], float(duration_h),
                             interval.boundary_truncated, round(az_from, 2), round(az_to, 2),
                             round(float(deficit.max()), 3), round(near_share, 3), round(below_limb_share, 3),
                             dominant, text)


def _summary(a: Assessment, ins: Insights) -> list[str]:
    m = {k: r.value for k, r in a.metrics.items()}
    lines = []
    for name, fraction, outage, kind in (("The Sun", "sun_visible_fraction", "max_continuous_darkness_hours", "darkness"),
                                         ("Earth", "earth_visible_fraction", "max_continuous_earth_blackout_hours",
                                          "Earth blackout")):
        if m[fraction] is None or m[outage] is None:
            lines.append(f"{name}'s visibility could not be determined (missing terrain data).")
        else:
            lines.append(f"{name} is visible {m[fraction]:.0%} of the mission; the longest {kind} lasts "
                         f"{m[outage]:.0f} h ({m[outage] / 24:.1f} days).")
    if ins.joint_visible_fraction is not None:
        lines.append(f"The Sun and Earth are visible together {ins.joint_visible_fraction:.0%} of the time "
                     f"(longest stretch {ins.longest_joint_window_h:.0f} h): the windows to charge and talk at once.")
    for name, series in (("Sun", ins.sun_hours_to_change), ("Earth", ins.earth_hours_to_change)):
        visible_now = (a.sun_visible if name == "Sun" else a.earth_visible)[0] == VISIBLE
        h = series[0]
        what = ("sets" if visible_now else "rises") if name == "Sun" else ("sets (Earthset)" if visible_now else "rises (Earthrise)")
        lines.append(f"At mission start the {name} is {'visible' if visible_now else 'hidden'}; it next {what} "
                     + (f"after {h:.0f} h." if h is not None else "after the mission ends."))
    lines.extend(o.text for o in ins.outages)
    return lines
