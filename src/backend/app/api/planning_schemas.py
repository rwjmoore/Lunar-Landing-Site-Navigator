"""
Filename: app/api/planning_schemas.py
Description: Request/response models for the planning endpoints
    (POST /calendar, /insights, /rescue). These are new endpoints, separate
    from the agreed v1 /analyze contract in schemas.py, which is unchanged.
    Units: hours, degrees, metres; fractions 0-1; None = not computable.
"""

from typing import Literal

from pydantic import Field

from app.api.schemas import (
    MAX_DURATION_HOURS,
    AnalyzeRequest,
    ConstraintsRequest,
    ContractModel,
    SiteRequest,
    VehicleRequest,
)

MAX_CALENDAR_STARTS = 20_000
Status = Literal["feasible", "infeasible", "unknown"]


# -- /calendar -------------------------------------------------------------------

class CalendarRequest(ContractModel):
    """Evaluate one mission length at many start dates (hourly sampling)."""

    site: SiteRequest
    vehicle: VehicleRequest
    constraints: ConstraintsRequest = Field(default_factory=ConstraintsRequest)
    duration_hours: int = Field(ge=1, le=MAX_DURATION_HOURS)
    start_step_hours: int = Field(default=24, ge=1, le=720, description="Spacing of candidate starts")
    start_from_utc: str | None = Field(default=None, description="Earliest start (whole UTC hour); default: first supported")
    start_to_utc: str | None = Field(default=None, description="Latest start (whole UTC hour); default: last that fits")


class CalendarResponse(ContractModel):
    site_name: str
    duration_hours: int
    start_step_hours: int
    starts_utc: list[str]
    sun_visible_fraction: list[float | None]
    max_darkness_hours: list[float | None]
    earth_visible_fraction: list[float | None]
    max_earth_blackout_hours: list[float | None]
    status: list[Status]
    worst_margin_hours: list[float | None] = Field(description="Smallest signed margin across limits")
    feasible_count: int
    best_start_utc: str | None = Field(description="Feasible start with the largest worst-case margin")
    best_worst_margin_hours: float | None
    computation_ms: float


# -- /insights -------------------------------------------------------------------

class EventModel(ContractModel):
    time_utc: str
    body: Literal["sun", "earth"]
    event: Literal["rise", "set"]


class BlockerModel(ContractModel):
    sector_from_deg: float
    sector_to_deg: float
    hours: float
    azimuth_deg: float
    distance_m: float
    latitude_deg: float
    longitude_deg_east: float
    zone: Literal["near", "far"]


class OutageModel(ContractModel):
    body: Literal["sun", "earth"]
    start_utc: str
    end_utc: str
    duration_hours: float
    boundary_truncated: bool
    azimuth_from_deg: float
    azimuth_to_deg: float
    max_deficit_deg: float
    near_share: float
    below_limb_share: float
    dominant: BlockerModel
    text: str


class InsightsResponse(ContractModel):
    site_name: str
    summary: list[str]
    events: list[EventModel]
    timestamps_utc: list[str]
    sun_hours_to_change: list[float | None]
    earth_hours_to_change: list[float | None]
    joint_visible_fraction: float | None
    longest_joint_window_hours: float | None
    longest_joint_window_start_utc: str | None
    longest_joint_window_end_utc: str | None
    outages: list[OutageModel]
    computation_ms: float


# -- /rescue ---------------------------------------------------------------------

class RescueRequest(AnalyzeRequest):
    """Same as /analyze, plus how far to search for a different start date."""

    max_shift_days: int = Field(default=60, ge=1, le=366)


class OutcomeModel(ContractModel):
    sun_visible_fraction: float | None
    max_darkness_hours: float | None
    earth_visible_fraction: float | None
    max_earth_blackout_hours: float | None
    status: Status


class OptionModel(ContractModel):
    kind: Literal["mast", "antenna", "date_earlier", "date_later", "move_nearest", "move_best"]
    fixes: bool
    change: dict
    outcome: OutcomeModel
    text: str


class RescueResponse(ContractModel):
    site_name: str
    baseline: OutcomeModel
    options: list[OptionModel]
    notes: list[str]
    computation_ms: float
