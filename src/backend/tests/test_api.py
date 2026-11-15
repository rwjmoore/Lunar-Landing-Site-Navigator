"""
Filename: tests/test_api.py
Description: End-to-end tests of /sites, /analyze, /compare and
    /data-provenance against the real data (M3). Checks that responses follow
    the v1 contract, that the API returns exactly what the physics core
    computes, and that invalid requests get documented errors. Skipped
    automatically when the data artifacts are not present.
"""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.schemas import AnalyzeResponse
from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, parse_utc
from app.main import app
from app.physics.analysis import MissionWindow, Vehicle, analyze
from app.physics.horizon import HORIZON_DIR, SITES_PATH, TERRAIN_DIR, SiteTerrain, load_sites
from app.planning.constraints import Constraint

pytestmark = pytest.mark.skipif(
    not (SITES_PATH.exists() and DEFAULT_SKY_GRID_PATH.exists() and HORIZON_DIR.exists()
         and (TERRAIN_DIR / "site04" / "heights.npy").exists()),
    reason="analysis data not present",
)

SITE04 = {"name": "Shackleton rim", "latitude_deg": -89.780403, "longitude_deg_east": 203.803049}
SITE01 = {"latitude_deg": -89.463163, "longitude_deg_east": 222.510447}
MISSION = {"start_utc": "2030-11-20T12:00:00Z", "duration_hours": 336, "sample_step_seconds": 3600}
VEHICLE = {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0}
CONSTRAINTS = {"max_darkness_hours": 24, "max_earth_blackout_hours": 100}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def analyze_body(**overrides) -> dict:
    body = {"site": SITE04, "mission": MISSION, "vehicle": VEHICLE, "constraints": CONSTRAINTS}
    body.update(overrides)
    return body


def test_sites_lists_the_four_supported_sites(client):
    body = client.get("/sites").json()
    assert [s["id"] for s in body["sites"]] == ["site01", "site04", "site07", "site11"]
    assert body["supported_start_utc"] == "2026-01-01T00:00:00Z"
    assert body["vehicle_height_range_m"] == [0.0, 20.0]


def test_analyze_returns_a_full_v1_contract_response(client):
    response = client.post("/analyze", json=analyze_body())
    assert response.status_code == 200
    body = response.json()
    AnalyzeResponse.model_validate(body)  # strict v1 contract (extra fields rejected)
    c = body["candidate"]
    assert c["name"] == "Shackleton rim"
    assert len(c["horizons"]["azimuth_deg"]) == 1440
    assert len(c["series"]["timestamps_utc"]) == 337  # 336 h hourly, both ends
    assert c["series"]["timestamps_utc"][0] == "2030-11-20T12:00:00Z"
    assert c["feasibility"]["status"] in {"feasible", "infeasible"}
    assert all(v is not None for v in c["metrics"].values())
    assert body["computation_ms"] > 0


def test_analyze_matches_the_physics_core_exactly(client):
    body = client.post("/analyze", json=analyze_body()).json()["candidate"]
    site = load_sites()["site04"]
    direct = analyze(SiteTerrain.load(site), SkyGrid.load(),
                     MissionWindow(parse_utc(MISSION["start_utc"]), 336 * 3600.0, 3600),
                     Vehicle(2.0, 2.0),
                     [Constraint("max_continuous_darkness_hours", "<=", 24),
                      Constraint("max_continuous_earth_blackout_hours", "<=", 100)])
    for key, result in direct.metrics.items():
        assert body["metrics"][key] == pytest.approx(result.value)
    assert body["series"]["sun_visible"] == (direct.sun_visible == 1).tolist()
    np.testing.assert_allclose(body["horizons"]["sun_observer_horizon_elevation_deg"],
                               np.degrees(direct.sun_horizon.elevation_rad), atol=1e-6)
    assert body["feasibility"]["status"] == direct.feasibility


def test_raising_the_mast_changes_only_the_sun_side(client):
    low = client.post("/analyze", json=analyze_body(site=SITE01)).json()["candidate"]
    high = client.post("/analyze", json=analyze_body(
        site=SITE01, vehicle={"solar_panel_mast_height_m": 10.0, "antenna_height_m": 2.0})).json()["candidate"]
    assert high["series"]["earth_visible"] == low["series"]["earth_visible"]
    assert high["horizons"]["earth_observer_horizon_elevation_deg"] == low["horizons"]["earth_observer_horizon_elevation_deg"]
    assert high["metrics"]["sun_visible_fraction"] >= low["metrics"]["sun_visible_fraction"]


def test_without_constraints_feasibility_is_unknown(client):
    body = analyze_body()
    del body["constraints"]
    c = client.post("/analyze", json=body).json()["candidate"]
    assert c["feasibility"]["status"] == "unknown"
    assert any("No constraints" in d for d in c["diagnostics"])


def test_failed_constraint_is_reported_with_margin(client):
    c = client.post("/analyze", json=analyze_body(
        site=SITE01, constraints={"max_darkness_hours": 1})).json()["candidate"]
    assert c["feasibility"]["status"] == "infeasible"
    assert c["feasibility"]["failed_constraints"] == ["max_continuous_darkness_hours"]
    assert c["feasibility"]["margins"]["max_continuous_darkness_hours"] < 0


def test_compare_uses_one_shared_mission(client):
    response = client.post("/compare", json={"sites": [SITE04, SITE01], "mission": MISSION,
                                             "vehicle": VEHICLE, "constraints": CONSTRAINTS})
    assert response.status_code == 200
    a, b = response.json()["candidates"]
    assert a["series"]["timestamps_utc"] == b["series"]["timestamps_utc"]
    assert a["location"]["latitude_deg"] != b["location"]["latitude_deg"]


@pytest.mark.parametrize(
    "overrides, status, code",
    [
        ({"site": {"latitude_deg": -89.0, "longitude_deg_east": 10.0}}, 404, "site_unavailable"),
        ({"site": {"latitude_deg": 10.0, "longitude_deg_east": 10.0}}, 404, "site_unavailable"),
        ({"mission": {**MISSION, "start_utc": "2030-11-20T12:30:00Z"}}, 422, "mission_out_of_range"),
        ({"mission": {**MISSION, "start_utc": "2045-01-01T00:00:00Z"}}, 422, "mission_out_of_range"),
        ({"mission": {**MISSION, "start_utc": "not a date"}}, 422, "mission_out_of_range"),
    ],
)
def test_documented_service_errors(client, overrides, status, code):
    response = client.post("/analyze", json=analyze_body(**overrides))
    assert response.status_code == status
    assert response.json()["error"] == code


@pytest.mark.parametrize(
    "overrides",
    [
        {"vehicle": {"solar_panel_mast_height_m": 25.0, "antenna_height_m": 2.0}},
        {"vehicle": {"solar_panel_mast_height_m": -1.0, "antenna_height_m": 2.0}},
        {"mission": {**MISSION, "sample_step_seconds": 1800}},
        {"mission": {**MISSION, "duration_hours": 400 * 24}},
        {"constraints": {"max_darkness_hours": -5}},
        {"unexpected": 1},
    ],
)
def test_request_validation_rejects_bad_input(client, overrides):
    assert client.post("/analyze", json=analyze_body(**overrides)).status_code == 422


def test_compare_limits_number_of_sites(client):
    body = {"sites": [SITE04] * 5, "mission": MISSION, "vehicle": VEHICLE}
    assert client.post("/compare", json=body).status_code == 422
    body["sites"] = [SITE04]
    assert client.post("/compare", json=body).status_code == 422


def test_data_provenance_lists_sources(client):
    body = client.get("/data-provenance").json()
    assert {"kernels", "terrain"} <= set(body["manifests"])
    assert body["sky_grid"]["samples"] == 131_496
    assert set(body["far_horizons"]) == {"site01", "site04", "site07", "site11"}
