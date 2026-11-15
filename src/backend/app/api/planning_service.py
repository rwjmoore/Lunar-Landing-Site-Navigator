"""
Filename: app/api/planning_service.py
Description: Serves the planning endpoints (docs/physics/planning.md):
    POST /calendar (date flexibility), POST /insights (explanations) and
    POST /rescue (smallest change that makes a mission pass). Reuses the
    AnalysisService's loaded data, site matching and request validation.
"""

import time
from datetime import timedelta

import numpy as np

from app.api import planning_schemas as ps
from app.api.service import AnalysisService, MissionOutOfRange, _constraints, _ms_since
from app.astronomy.sky import SkyGridRangeError, format_utc, parse_utc
from app.physics.analysis import Vehicle, analyze
from app.planning.calendar import calendar, grid_visibility
from app.planning.insights import explain
from app.planning.rescue import rescue


class TooManyStarts(MissionOutOfRange):
    code = "too_many_starts"


def _none(values) -> list:
    return [None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 6) for v in values]


def _grid_index(service: AnalysisService, text: str, label: str) -> int:
    try:
        when = parse_utc(text)
    except ValueError as exc:
        raise MissionOutOfRange(f"invalid {label}: {exc}") from exc
    offset = (when - service.sky.utc_start).total_seconds()
    if offset % 3600:
        raise MissionOutOfRange(f"{label} must fall on a whole UTC hour")
    return int(offset // 3600)


def calendar_view(service: AnalysisService, req: ps.CalendarRequest) -> ps.CalendarResponse:
    started = time.perf_counter()
    service._require_ready()
    terrain = service.terrain_for(req.site)
    site = terrain.site
    grid = service.sky
    last = grid.size - req.duration_hours - 1
    lo = 0 if req.start_from_utc is None else _grid_index(service, req.start_from_utc, "start_from_utc")
    hi = last if req.start_to_utc is None else _grid_index(service, req.start_to_utc, "start_to_utc")
    if lo < 0 or hi > last or lo > hi:
        raise MissionOutOfRange("the requested start range does not fit in the supported dates",
                                **service._supported_range())
    starts = np.arange(lo, hi + 1, req.start_step_hours)
    if len(starts) > ps.MAX_CALENDAR_STARTS:
        raise TooManyStarts(f"{len(starts)} candidate starts requested; the limit is {ps.MAX_CALENDAR_STARTS}. "
                            "Use a larger start_step_hours or a shorter range.")
    vis = grid_visibility(terrain, grid, req.vehicle.solar_panel_mast_height_m, req.vehicle.antenna_height_m)
    c = req.constraints
    cal = calendar(vis, starts, req.duration_hours, c.max_darkness_hours, c.max_earth_blackout_hours)
    feasible = np.flatnonzero(cal.status == "feasible")
    best = int(feasible[np.argmax(cal.worst_margin_h[feasible])]) if len(feasible) else None
    return ps.CalendarResponse(
        site_name=req.site.name or site.name,
        duration_hours=req.duration_hours,
        start_step_hours=req.start_step_hours,
        starts_utc=[format_utc(grid.utc_start + timedelta(hours=int(s))) for s in starts],
        sun_visible_fraction=_none(cal.sun.visible_fraction),
        max_darkness_hours=_none(cal.sun.longest_outage_h),
        earth_visible_fraction=_none(cal.earth.visible_fraction),
        max_earth_blackout_hours=_none(cal.earth.longest_outage_h),
        status=list(cal.status),
        worst_margin_hours=_none(cal.worst_margin_h),
        feasible_count=len(feasible),
        best_start_utc=None if best is None else format_utc(grid.utc_start + timedelta(hours=int(starts[best]))),
        best_worst_margin_hours=None if best is None else round(float(cal.worst_margin_h[best]), 6),
        computation_ms=_ms_since(started),
    )


def insights_view(service: AnalysisService, req) -> ps.InsightsResponse:
    started = time.perf_counter()
    service._require_ready()
    terrain = service.terrain_for(req.site)
    site = terrain.site
    window = service._window(req.mission)
    vehicle = Vehicle(req.vehicle.solar_panel_mast_height_m, req.vehicle.antenna_height_m)
    try:
        a = analyze(terrain, service.sky, window, vehicle, _constraints(req.constraints))
    except SkyGridRangeError as exc:
        raise MissionOutOfRange(str(exc), **service._supported_range()) from exc
    ins = explain(a, site)
    span = ins.longest_joint_window
    return ps.InsightsResponse(
        site_name=req.site.name or site.name,
        summary=ins.summary,
        events=[ps.EventModel(time_utc=e.time_utc, body=e.body, event=e.event) for e in ins.events],
        timestamps_utc=a.sky.timestamps_utc,
        sun_hours_to_change=ins.sun_hours_to_change,
        earth_hours_to_change=ins.earth_hours_to_change,
        joint_visible_fraction=ins.joint_visible_fraction,
        longest_joint_window_hours=ins.longest_joint_window_h,
        longest_joint_window_start_utc=span[0] if span else None,
        longest_joint_window_end_utc=span[1] if span else None,
        outages=[ps.OutageModel(
            body=o.body, start_utc=o.start_utc, end_utc=o.end_utc, duration_hours=o.duration_h,
            boundary_truncated=o.boundary_truncated, azimuth_from_deg=o.azimuth_from_deg,
            azimuth_to_deg=o.azimuth_to_deg, max_deficit_deg=o.max_deficit_deg, near_share=o.near_share,
            below_limb_share=o.below_limb_share, dominant=ps.BlockerModel(**o.dominant.__dict__), text=o.text,
        ) for o in ins.outages],
        computation_ms=_ms_since(started),
    )


def rescue_view(service: AnalysisService, req: ps.RescueRequest) -> ps.RescueResponse:
    started = time.perf_counter()
    service._require_ready()
    terrain = service.terrain_for(req.site)
    site = terrain.site
    window = service._window(req.mission)
    if req.mission.sample_step_seconds != 3600 or req.mission.duration_hours != int(req.mission.duration_hours):
        raise MissionOutOfRange("mission rescue needs hourly sampling and a whole number of hours")
    vehicle = Vehicle(req.vehicle.solar_panel_mast_height_m, req.vehicle.antenna_height_m)
    try:
        r = rescue(terrain, service.sky, window, vehicle, req.constraints.max_darkness_hours,
                   req.constraints.max_earth_blackout_hours, region=service.region,
                   make_terrain=service.make_point if service.region is not None else None,
                   max_shift_days=req.max_shift_days)
    except SkyGridRangeError as exc:
        raise MissionOutOfRange(str(exc), **service._supported_range()) from exc

    def outcome(o):
        return ps.OutcomeModel(sun_visible_fraction=o.sun_visible_fraction, max_darkness_hours=o.max_darkness_h,
                               earth_visible_fraction=o.earth_visible_fraction,
                               max_earth_blackout_hours=o.max_blackout_h, status=o.status)
    return ps.RescueResponse(
        site_name=req.site.name or site.name,
        baseline=outcome(r.baseline),
        options=[ps.OptionModel(kind=o.kind, fixes=o.fixes, change=o.change, outcome=outcome(o.outcome), text=o.text)
                 for o in r.options],
        notes=r.notes,
        computation_ms=_ms_since(started),
    )
