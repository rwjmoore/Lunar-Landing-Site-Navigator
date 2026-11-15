"""
Filename: tests/test_custom_points.py
Description: Tests for on-demand custom points anywhere in the covered area
    (app/physics/point_terrain.py, docs/physics/custom_points.md): agreement
    with the curated sites, the standard-detail tier's sampling convergence,
    coverage limits, the API behaviour for custom coordinates, and the
    on-demand nearby search in mission rescue. Skipped without data.
"""

from dataclasses import replace

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.service import AnalysisService
from app.main import app
from app.physics.horizon import AZIMUTHS_RAD, SITES_PATH, TERRAIN_DIR
from app.physics.point_terrain import COVERAGE_RADIUS_M, REGION_DIR, coverage_latitude_deg

pytestmark = pytest.mark.skipif(
    not (SITES_PATH.exists() and (REGION_DIR / "heights.npy").exists()
         and (TERRAIN_DIR / "site01" / "heights.npy").exists()),
    reason="terrain data not present",
)
STEP_TOL_DEG = 0.015   # the approved M2 step-halving tolerance (horizon.md section 11)


@pytest.fixture(scope="module")
def service():
    return AnalysisService.load()


def test_coverage_edge_is_about_86_7_south():
    assert coverage_latitude_deg() == pytest.approx(-86.70, abs=0.01)
    assert COVERAGE_RADIUS_M + 200_000 < 304_000   # every 200 km ray stays inside the 40 m map


@pytest.mark.parametrize("site_id", ["site01", "site04"])
def test_on_demand_point_matches_curated_site(service, site_id):
    """A point placed exactly at a curated site (high detail, far zone cast directly)
    must reproduce the curated horizon (far zone from stored points)."""
    site = service.sites[site_id]
    point = service.make_point(site.latitude_deg, site.longitude_deg_east)
    assert point.detail == "high"
    assert point.site.ground_height_m == pytest.approx(site.ground_height_m, abs=0.01)
    # The curated site list stores ground height rounded to 1 cm; a 5 mm difference seen
    # against terrain 80 m away is ~0.003 deg. Use the curated height so only the method differs.
    point.site = replace(point.site, ground_height_m=site.ground_height_m)
    diff = np.degrees(np.abs(point.horizon(2.0).elevation_rad - service.terrains[site_id].horizon(2.0).elevation_rad))
    assert diff.max() < 0.001


@pytest.mark.parametrize("lat, lon", [(-88.0, 45.0), (-89.2, 300.0), (-87.2, 160.0)])
def test_standard_detail_converges_under_step_halving(service, lat, lon):
    point = service.make_point(lat, lon)
    assert point.detail == "standard"
    subset = AZIMUTHS_RAD[::10]
    standard = point.compute(2.0, subset).elevation_rad
    finer = point.compute(2.0, subset, refine=2.0).elevation_rad
    assert np.degrees(np.max(np.abs(standard - finer))) <= STEP_TOL_DEG


def test_points_outside_coverage_are_refused(service):
    with pytest.raises(ValueError, match="outside the covered area"):
        service.make_point(-86.0, 10.0)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


MISSION = {"start_utc": "2030-12-01T00:00:00Z", "duration_hours": 336, "sample_step_seconds": 3600}
VEHICLE = {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0}


def test_sites_advertises_custom_coverage(client):
    body = client.get("/sites").json()
    assert body["custom_points_available"] is True
    assert body["custom_point_north_edge_latitude_deg"] == pytest.approx(-86.70, abs=0.01)


def test_custom_point_analysis(client):
    body = {"site": {"name": "My point", "latitude_deg": -88.0, "longitude_deg_east": 45.0},
            "mission": MISSION, "vehicle": VEHICLE, "constraints": {"max_darkness_hours": 24}}
    response = client.post("/analyze", json=body)
    assert response.status_code == 200
    c = response.json()["candidate"]
    assert c["name"] == "My point"
    assert (c["location"]["latitude_deg"], c["location"]["longitude_deg_east"]) == (-88.0, 45.0)
    assert "standard detail" in c["provenance"]["dem_id"]
    assert any("Standard detail" in d for d in c["diagnostics"])


def test_rescue_finds_a_nearby_point(client):
    body = {"site": {"latitude_deg": -89.463163, "longitude_deg_east": 222.510447}, "mission": MISSION,
            "vehicle": VEHICLE, "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 200}}
    options = client.post("/rescue", json=body).json()["options"]
    move = next(o for o in options if o["kind"] == "move_nearest")
    assert move["fixes"] and 0 < move["change"]["distance_m"] <= 1200
    # The reported outcome is exact: re-analysing that point must give the same darkness.
    point = {"latitude_deg": move["change"]["latitude_deg"], "longitude_deg_east": move["change"]["longitude_deg_east"]}
    again = client.post("/analyze", json={**body, "site": point}).json()["candidate"]
    assert again["metrics"]["max_continuous_darkness_hours"] == move["outcome"]["max_darkness_hours"]
