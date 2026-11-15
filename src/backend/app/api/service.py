"""
Filename: app/api/service.py
Description: Bridges the HTTP layer and the physics core (M3).

    - Loads the sky grid, site list and per-site terrain once at startup.
    - Matches a requested latitude/longitude to a supported site within
      SITE_MATCH_TOLERANCE_M (PROJECT_PLAN.md section 7, "Site addressing").
    - Runs app.physics.analysis.analyze and maps the Assessment onto the
      agreed v1 JSON contract (app/api/schemas.py) without changing physics.

    Errors raised here are ServiceError subclasses carrying an HTTP status;
    routes.py turns them into documented JSON error responses.
"""

import json
import time
from dataclasses import dataclass, field

import numpy as np

from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, SkyGridRangeError, format_utc, parse_utc
from app.metrics.core import UNKNOWN
from app.physics.analysis import Assessment, MissionWindow, Vehicle, analyze
from app.physics.horizon import (
    HORIZON_DIR,
    MAX_OBSERVER_HEIGHT_M,
    REPO_DATA,
    SITES_PATH,
    SiteInfo,
    SiteTerrain,
    load_sites,
)
from app.planning.constraints import Constraint
from app.terrain.grid import polar_stereo_forward

from app.api import schemas

SITE_MATCH_TOLERANCE_M = 100.0
LOW_MAST_NOTE_BELOW_M = 1.0  # see docs/physics/validation.md section 9.2
_PROVENANCE_MANIFESTS = ("kernels.json", "terrain.json", "validation.json")


class ServiceError(Exception):
    """An error with an HTTP status and a stable machine-readable code."""

    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, **details):
        super().__init__(message)
        self.message = message
        self.details = details


class SiteUnavailable(ServiceError):
    status_code = 404
    code = "site_unavailable"


class MissionOutOfRange(ServiceError):
    status_code = 422
    code = "mission_out_of_range"


class DataUnavailable(ServiceError):
    status_code = 503
    code = "data_unavailable"


@dataclass
class AnalysisService:
    """Holds loaded datasets and serves analyses."""

    sky: SkyGrid | None = None
    sites: dict[str, SiteInfo] = field(default_factory=dict)
    terrains: dict[str, SiteTerrain] = field(default_factory=dict)
    load_errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "AnalysisService":
        """Load everything; record (rather than raise) what is missing, for /health."""
        service = cls()
        try:
            service.sky = SkyGrid.load(DEFAULT_SKY_GRID_PATH)
        except (OSError, KeyError, ValueError) as exc:
            service.load_errors["sky_grid"] = str(exc)
        try:
            service.sites = load_sites(SITES_PATH)
            service.terrains = {sid: SiteTerrain.load(s) for sid, s in service.sites.items()}
        except (OSError, KeyError, ValueError) as exc:
            service.load_errors["terrain"] = str(exc)
        return service

    # -- status ------------------------------------------------------------

    def datasets(self) -> dict[str, str]:
        return {
            "sky_grid": "loaded" if self.sky is not None else "missing",
            "sites": f"{len(self.sites)} loaded" if self.sites else "missing",
            "terrain": f"{len(self.terrains)} sites loaded" if self.terrains else "missing",
        }

    def _require_ready(self) -> None:
        if self.sky is None or not self.terrains:
            raise DataUnavailable("analysis data is not loaded on this server", missing=self.load_errors)

    # -- sites ---------------------------------------------------------------

    def site_summaries(self) -> schemas.SitesResponse:
        self._require_ready()
        raw = {s["id"]: s for s in json.loads(SITES_PATH.read_text(encoding="utf-8"))["sites"]}
        return schemas.SitesResponse(
            sites=[
                schemas.SiteSummary(
                    id=s.id, name=s.name, latitude_deg=s.latitude_deg,
                    longitude_deg_east=s.longitude_deg_east, surface_elevation_m=s.ground_height_m,
                    near_field_radius_m=s.near_field_radius_m,
                    coordinate_source=raw[s.id]["coordinate_source"],
                )
                for s in self.sites.values()
            ],
            site_match_tolerance_m=SITE_MATCH_TOLERANCE_M,
            supported_start_utc=format_utc(self.sky.utc_start),
            supported_end_utc=format_utc(self.sky.utc_end),
            sample_step_seconds_multiple=self.sky.step_s,
            vehicle_height_range_m=[0.0, MAX_OBSERVER_HEIGHT_M],
        )

    def match_site(self, request: schemas.SiteRequest) -> SiteInfo:
        """Nearest supported site within SITE_MATCH_TOLERANCE_M, else SiteUnavailable."""
        if request.latitude_deg > -88.0:
            raise SiteUnavailable("only south-pole sites near 88-90 S are supported",
                                  supported=self._site_list())
        x, y = polar_stereo_forward(np.radians(request.latitude_deg), np.radians(request.longitude_deg_east))
        best, best_distance = None, np.inf
        for site in self.sites.values():
            sx, sy = polar_stereo_forward(np.radians(site.latitude_deg), np.radians(site.longitude_deg_east))
            distance = float(np.hypot(x - sx, y - sy))
            if distance < best_distance:
                best, best_distance = site, distance
        if best is None or best_distance > SITE_MATCH_TOLERANCE_M:
            raise SiteUnavailable(
                f"no supported site within {SITE_MATCH_TOLERANCE_M:g} m of the requested coordinates",
                nearest_site=None if best is None else best.id,
                nearest_distance_m=None if best is None else round(best_distance, 1),
                supported=self._site_list(),
            )
        return best

    def _site_list(self) -> list[dict]:
        return [{"id": s.id, "name": s.name, "latitude_deg": s.latitude_deg,
                 "longitude_deg_east": s.longitude_deg_east} for s in self.sites.values()]

    # -- analysis ----------------------------------------------------------

    def analyze(self, request: schemas.AnalyzeRequest) -> schemas.AnalyzeResponse:
        started = time.perf_counter()
        candidate = self._candidate(request.site, request.mission, request.vehicle, request.constraints)
        return schemas.AnalyzeResponse(candidate=candidate, computation_ms=_ms_since(started))

    def compare(self, request: schemas.CompareRequest) -> schemas.CompareResponse:
        started = time.perf_counter()
        candidates = [self._candidate(site, request.mission, request.vehicle, request.constraints)
                      for site in request.sites]  # identical mission, vehicle, constraints by construction
        return schemas.CompareResponse(candidates=candidates, computation_ms=_ms_since(started))

    def _candidate(self, site_req, mission, vehicle_req, constraints_req) -> schemas.Candidate:
        self._require_ready()
        site = self.match_site(site_req)
        window = self._window(mission)
        vehicle = Vehicle(vehicle_req.solar_panel_mast_height_m, vehicle_req.antenna_height_m)
        constraints = _constraints(constraints_req)
        try:
            assessment = analyze(self.terrains[site.id], self.sky, window, vehicle, constraints)
        except SkyGridRangeError as exc:
            raise MissionOutOfRange(str(exc), **self._supported_range()) from exc
        return self._to_contract(site, site_req, assessment, constraints, vehicle_req, mission)

    def _window(self, mission: schemas.MissionRequest) -> MissionWindow:
        try:
            start = parse_utc(mission.start_utc)
        except ValueError as exc:
            raise MissionOutOfRange(f"invalid start_utc: {exc}") from exc
        return MissionWindow(start, mission.duration_hours * 3600.0, mission.sample_step_seconds)

    def _supported_range(self) -> dict:
        return {"supported_start_utc": format_utc(self.sky.utc_start),
                "supported_end_utc": format_utc(self.sky.utc_end),
                "sample_step_seconds_multiple": self.sky.step_s}

    def _to_contract(self, site, site_req, a: Assessment, constraints, vehicle_req, mission) -> schemas.Candidate:
        if (a.sun_visible == UNKNOWN).any() or (a.earth_visible == UNKNOWN).any():
            # Contract v1 visibility is boolean and cannot express "unknown";
            # never report unknown as visible or obstructed (PROJECT_PLAN.md 7.2).
            raise DataUnavailable("terrain data is missing in some directions for this request; "
                                  "unknown visibility needs contract v2 (PROJECT_PLAN.md section 7.2)")
        metrics = {k: r.value for k, r in a.metrics.items()}
        status = a.feasibility if constraints else "unknown"
        return schemas.Candidate(
            name=site_req.name or site.name,
            location=schemas.Location(latitude_deg=site.latitude_deg, longitude_deg_east=site.longitude_deg_east,
                                      surface_elevation_m=site.ground_height_m),
            vehicle=schemas.Vehicle(**vehicle_req.model_dump()),
            metrics=schemas.Metrics(**metrics),
            feasibility=schemas.Feasibility(
                status=status,
                failed_constraints=[c.constraint.metric_id for c in a.constraints if c.passed is False],
                margins={c.constraint.metric_id: c.margin for c in a.constraints if c.margin is not None},
            ),
            horizons=schemas.Horizons(
                azimuth_deg=_deg(a.sun_horizon.azimuth_rad),
                sun_observer_horizon_elevation_deg=_deg(a.sun_horizon.elevation_rad),
                earth_observer_horizon_elevation_deg=_deg(a.earth_horizon.elevation_rad),
            ),
            series=schemas.Series(
                timestamps_utc=a.sky.timestamps_utc,
                sun_azimuth_deg=_deg(a.sky.sun_azimuth), sun_elevation_deg=_deg(a.sky.sun_elevation),
                sun_visible=(a.sun_visible == 1).tolist(),
                earth_azimuth_deg=_deg(a.sky.earth_azimuth), earth_elevation_deg=_deg(a.sky.earth_elevation),
                earth_visible=(a.earth_visible == 1).tolist(),
            ),
            diagnostics=_diagnostics(site, a, constraints, vehicle_req),
            provenance=schemas.Provenance(
                dem_id=f"LOLA 5 m {site.id} DEM + LDEM_80S_40MPP_ADJ (data/manifests/terrain.json)",
                ephemeris_id="DE421 sky grid 2026-2040, hourly (data/manifests/kernels.json)",
                sample_step_seconds=mission.sample_step_seconds,
            ),
        )

    def provenance(self) -> dict:
        """Data sources, versions and assumptions for GET /data-provenance."""
        manifests = {}
        for name in _PROVENANCE_MANIFESTS:
            path = REPO_DATA / "manifests" / name
            if path.exists():
                manifests[name.removesuffix(".json")] = json.loads(path.read_text(encoding="utf-8"))
        far = {}
        for site_id in self.sites:
            path = HORIZON_DIR / f"{site_id}_far.npz"
            if path.exists():
                with np.load(path) as data:
                    far[site_id] = json.loads(str(data["provenance"]))
        return {
            "manifests": manifests,
            "sky_grid": json.loads(self.sky.provenance) if self.sky and self.sky.provenance else None,
            "far_horizons": far,
            "assumptions": [
                "Sun and Earth treated as points at their centres (docs/physics/horizon.md section 6).",
                "Terrain: LOLA 5 m site DEMs within each site's near-field radius, 40 m map beyond, "
                "out to 200 km; about 90% of 5 m pixels are interpolated (docs/physics/terrain.md).",
                "Visibility is geometric line of sight; it does not guarantee an RF link.",
                "Validated against NASA's published south-pole illumination maps "
                "(docs/physics/validation.md).",
            ],
            "physics_docs": ["docs/SCIENCE_CONVENTIONS.md", "docs/physics/frames.md", "docs/physics/sky.md",
                             "docs/physics/terrain.md", "docs/physics/horizon.md", "docs/metrics.md",
                             "docs/physics/validation.md"],
        }


def _constraints(req: schemas.ConstraintsRequest) -> list[Constraint]:
    out = []
    if req.max_darkness_hours is not None:
        out.append(Constraint("max_continuous_darkness_hours", "<=", req.max_darkness_hours))
    if req.max_earth_blackout_hours is not None:
        out.append(Constraint("max_continuous_earth_blackout_hours", "<=", req.max_earth_blackout_hours))
    return out


def _diagnostics(site: SiteInfo, a: Assessment, constraints, vehicle_req) -> list[str]:
    notes = []
    if not constraints:
        notes.append("No constraints were provided, so feasibility is 'unknown'.")
    for outcome in a.constraints:
        metric = a.metrics[outcome.constraint.metric_id]
        if outcome.value is None:
            notes.append(f"{outcome.constraint.metric_id} could not be computed: {outcome.reason}.")
            continue
        verdict = {True: "passes", False: "FAILS", None: "is uncertain"}[outcome.passed]
        line = (f"{outcome.constraint.metric_id} = {outcome.value:.1f} h {verdict} the limit of "
                f"{outcome.constraint.limit:g} h (margin {outcome.margin:+.1f} h)")
        if metric.worst_interval is not None:
            start = a.sky.timestamps_utc[metric.worst_interval.start_index]
            end = a.sky.timestamps_utc[metric.worst_interval.end_index]
            line += f"; longest outage starts {start}, last sample in it {end}"
            if metric.worst_interval.boundary_truncated:
                line += " (touches the mission boundary, may extend beyond it)"
        notes.append(line + ".")
    for result in a.metrics.values():
        notes.extend(n for n in result.notes if n not in notes)
    if min(vehicle_req.solar_panel_mast_height_m, vehicle_req.antenna_height_m) < LOW_MAST_NOTE_BELOW_M:
        notes.append("Heights below 1 m are the most sensitive to terrain uncertainty near the lander "
                     "(docs/physics/validation.md section 9.2).")
    notes.append("Sun and Earth are treated as points at their centres; geometric line of sight only.")
    return notes


def _deg(radians) -> list[float]:
    return np.round(np.degrees(np.asarray(radians, float)), 6).tolist()


def _ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000.0, 1)
