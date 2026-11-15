"""
Filename: app/physics/analysis.py
Description: One-call site analysis (docs/physics/horizon.md section 8):
    site + mission window + vehicle + constraints -> horizons, Sun/Earth sky
    track, visibility series, metrics and feasibility. Framework-independent;
    the API layer maps an Assessment onto the JSON contract (M3).
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from app.astronomy.sky import SkyGrid, SkyTrack, sky_track
from app.metrics.core import EvaluationContext, MetricResult, compute_metrics
from app.metrics.registry import DEFAULT_METRICS
from app.physics.horizon import HorizonProfile, SiteTerrain
from app.physics.visibility import visibility
from app.planning.constraints import (
    Constraint,
    ConstraintResult,
    FeasibilityStatus,
    evaluate_constraints,
    feasibility_status,
)


@dataclass(frozen=True)
class Vehicle:
    """Heights above local ground, metres (0-20 m, enforced by the horizon)."""

    solar_panel_mast_height_m: float
    antenna_height_m: float


@dataclass(frozen=True)
class MissionWindow:
    """Mission sampling. Start on a whole UTC hour; step a whole number of hours."""

    start_utc: datetime
    duration_s: float
    step_s: int


@dataclass(frozen=True)
class Assessment:
    """Everything computed for one site, mission and vehicle."""

    site_id: str
    vehicle: Vehicle
    window: MissionWindow
    sun_horizon: HorizonProfile
    earth_horizon: HorizonProfile
    sky: SkyTrack
    sun_visible: np.ndarray    # int8 VISIBLE / OBSTRUCTED / UNKNOWN per sample
    earth_visible: np.ndarray
    metrics: dict[str, MetricResult]
    constraints: list[ConstraintResult]
    feasibility: FeasibilityStatus


def analyze(
    terrain: SiteTerrain,
    grid: SkyGrid,
    window: MissionWindow,
    vehicle: Vehicle,
    constraints: list[Constraint],
) -> Assessment:
    """Run the full physics chain for one site."""
    sun_horizon = terrain.horizon(vehicle.solar_panel_mast_height_m)
    earth_horizon = terrain.horizon(vehicle.antenna_height_m)

    # The sky track is seen from the site at ground level; observer heights of
    # metres change Sun/Earth directions negligibly (sky.md section 5), and only
    # the horizon geometry depends on vehicle height (SCIENCE_CONVENTIONS.md 6).
    sky = sky_track(grid, terrain.site.frame(0.0), window.start_utc, window.duration_s, window.step_s)
    sun_visible = visibility(sun_horizon, sky.sun_azimuth, sky.sun_elevation)
    earth_visible = visibility(earth_horizon, sky.earth_azimuth, sky.earth_elevation)

    context = EvaluationContext.from_window(
        window.duration_s, window.step_s, {"sun_visible": sun_visible, "earth_visible": earth_visible}
    )
    metrics = compute_metrics(context, DEFAULT_METRICS)
    outcomes = evaluate_constraints(metrics, constraints)
    return Assessment(
        site_id=terrain.site.id,
        vehicle=vehicle,
        window=window,
        sun_horizon=sun_horizon,
        earth_horizon=earth_horizon,
        sky=sky,
        sun_visible=sun_visible,
        earth_visible=earth_visible,
        metrics=metrics,
        constraints=outcomes,
        feasibility=feasibility_status(outcomes),
    )
