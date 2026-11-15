"""
Filename: app/api/schemas.py
Description: Pydantic models for the backend -> frontend JSON contract.

    These models mirror docs/frontend-backend_interface.json exactly. That JSON
    file is the agreement with the frontend engineer; if either side changes,
    update both together (PROJECT_PLAN.md section 13, rule 3). A test
    (tests/test_contract.py) validates the JSON fixture against these models so
    the two cannot silently drift apart.

    Conventions (see docs/SCIENCE_CONVENTIONS.md):
      - Angles are degrees; azimuth is clockwise from north in [0, 360).
      - Longitude is east-positive.
      - Timestamps are UTC ISO 8601 strings with a "Z" suffix.
      - Time series are parallel arrays (one list per quantity), all the same
        length; never lists of per-timestamp objects.

    Nullable metric values exist only so the placeholder fixture validates. A
    real analysis must never return null metrics as results; it must return
    feasibility status "unavailable" or a documented error instead.

    Request models (POST /analyze, /compare) are intentionally not defined yet:
    they are added with those endpoints, once the fixed-site request shape
    (site id vs. coordinates) is agreed.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Base for contract models: unknown fields are rejected so drift is caught."""

    model_config = ConfigDict(extra="forbid")


class Location(ContractModel):
    """Surface position of a candidate site."""

    latitude_deg: float = Field(ge=-90.0, le=90.0)
    longitude_deg_east: float = Field(ge=-180.0, lt=360.0)
    surface_elevation_m: float | None = Field(
        description="DEM height relative to the 1737.4 km reference sphere, in metres."
    )


class Vehicle(ContractModel):
    """Vehicle heights above local terrain, in metres."""

    solar_panel_mast_height_m: float = Field(ge=0.0)
    antenna_height_m: float = Field(ge=0.0)


class Metrics(ContractModel):
    """Mission summary metrics over the analysed window.

    Fractions are in [0, 1]; durations are in hours. Fixed fields for now; the
    planned reusable metric framework may change this shape (needs frontend
    agreement first).
    """

    sun_visible_fraction: float | None = Field(ge=0.0, le=1.0)
    max_continuous_darkness_hours: float | None = Field(ge=0.0)
    earth_visible_fraction: float | None = Field(ge=0.0, le=1.0)
    max_continuous_earth_blackout_hours: float | None = Field(ge=0.0)


class Feasibility(ContractModel):
    """Pass/fail result against the user's mission constraints.

    `failed_constraints` and `margins` contents are provisional until the
    constraint model is defined; margins are signed (positive = passing).
    """

    status: Literal["feasible", "infeasible", "unknown", "unavailable"]
    failed_constraints: list[str]
    margins: dict[str, float]


class Horizons(ContractModel):
    """Terrain horizon profiles: elevation of the horizon at each azimuth bin.

    Separate profiles exist because the solar mast and the antenna can sit at
    different heights, which changes the terrain horizon each one sees.
    """

    azimuth_deg: list[float]
    sun_observer_horizon_elevation_deg: list[float]
    earth_observer_horizon_elevation_deg: list[float]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "Horizons":
        _require_equal_lengths(
            azimuth_deg=self.azimuth_deg,
            sun_observer_horizon_elevation_deg=self.sun_observer_horizon_elevation_deg,
            earth_observer_horizon_elevation_deg=self.earth_observer_horizon_elevation_deg,
        )
        return self


class Series(ContractModel):
    """Time series of Sun/Earth direction and visibility, one entry per sample."""

    timestamps_utc: list[str]
    sun_azimuth_deg: list[float]
    sun_elevation_deg: list[float]
    sun_visible: list[bool]
    earth_azimuth_deg: list[float]
    earth_elevation_deg: list[float]
    earth_visible: list[bool]

    @model_validator(mode="after")
    def _equal_lengths(self) -> "Series":
        _require_equal_lengths(**{name: getattr(self, name) for name in type(self).model_fields})
        return self


class Provenance(ContractModel):
    """Identifies the data sources behind a result, for reproducibility."""

    dem_id: str | None
    ephemeris_id: str | None
    sample_step_seconds: int = Field(gt=0)


class Candidate(ContractModel):
    """One analysed site: its inputs echoed back plus all derived results."""

    name: str
    location: Location
    vehicle: Vehicle
    metrics: Metrics
    feasibility: Feasibility
    horizons: Horizons
    series: Series
    diagnostics: list[str] = Field(description="Provisional: human-readable explanations.")
    provenance: Provenance


class AnalyzeResponse(ContractModel):
    """Response body of POST /analyze."""

    candidate: Candidate
    computation_ms: float | None = Field(ge=0.0)


class HealthResponse(ContractModel):
    """Response body of GET /health."""

    status: Literal["ok"]
    version: str
    datasets: dict[str, str] = Field(
        description="Dataset name -> load status. Empty until artifacts exist (M1)."
    )


def _require_equal_lengths(**arrays: list) -> None:
    """Raise ValueError if the given parallel arrays differ in length."""
    lengths = {name: len(values) for name, values in arrays.items()}
    if len(set(lengths.values())) > 1:
        raise ValueError(f"parallel arrays must have equal length, got {lengths}")
