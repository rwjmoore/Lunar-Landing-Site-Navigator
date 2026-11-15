"""
Filename: tests/test_planning.py
Description: Tests for the planning tools (docs/physics/planning.md):
    the calendar's window metrics against brute force and against
    app.physics.analysis.analyze, joint Sun+Earth states, the explanation
    helpers, the mission-rescue height search against a full scan, and the
    /calendar, /insights and /rescue endpoints. Real-data tests are skipped
    automatically when the data artifacts are not present.
"""

from datetime import timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.astronomy.sky import DEFAULT_SKY_GRID_PATH, SkyGrid, parse_utc
from app.main import app
from app.metrics.core import OBSTRUCTED as O
from app.metrics.core import UNKNOWN as U
from app.metrics.core import VISIBLE as V
from app.physics.analysis import MissionWindow, Vehicle, analyze
from app.physics.horizon import HORIZON_DIR, SITES_PATH, TERRAIN_DIR, SiteTerrain, load_sites
from app.planning.calendar import _longest_runs, calendar, grid_visibility, joint_states, window_metrics
from app.planning.constraints import Constraint
from app.planning.insights import _circular_range, _events, _hours_to_change
from app.planning.rescue import _Mission, _smallest_height

HAVE_DATA = (SITES_PATH.exists() and DEFAULT_SKY_GRID_PATH.exists() and HORIZON_DIR.exists()
             and (TERRAIN_DIR / "site01" / "heights.npy").exists())
needs_data = pytest.mark.skipif(not HAVE_DATA, reason="analysis data not present")


# -- pure logic (no data needed) --------------------------------------------------------

def brute_longest(flags, s, e):
    best = run = 0
    for v in flags[s:e + 1]:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def test_longest_runs_matches_brute_force():
    rng = np.random.default_rng(3)
    for density in (0.2, 0.5, 0.9):
        flags = rng.random(500) < density
        starts = rng.integers(0, 450, 300)
        lengths = rng.integers(1, 50, 300)
        ends = np.minimum(starts + lengths - 1, 499)
        got = _longest_runs(flags, starts, ends)
        assert list(got) == [brute_longest(flags, s, e) for s, e in zip(starts, ends)]


def test_longest_runs_edge_cases():
    assert list(_longest_runs(np.zeros(10, bool), np.array([0, 5]), np.array([9, 9]))) == [0, 0]
    assert list(_longest_runs(np.ones(10, bool), np.array([0, 3]), np.array([9, 5]))) == [10, 3]


def test_window_metrics_with_unknowns():
    states = np.array([V, O, O, U, O, V, V, O], dtype=np.int8)
    m = window_metrics(states, np.array([0, 3]), 5)
    assert m.visible_fraction[0] == pytest.approx(1 / 4)     # window 0..4: V O O U O -> 1 of 4 known
    assert m.longest_outage_h[0] == 2                         # unknown breaks the run
    assert m.coverage[0] == pytest.approx(4 / 5)
    assert m.longest_outage_h[1] == 1 and m.visible_fraction[1] == pytest.approx(2 / 4)


def test_joint_states_truth_table():
    a = np.array([V, V, V, O, O, O, U, U, U], dtype=np.int8)
    b = np.array([V, O, U, V, O, U, V, O, U], dtype=np.int8)
    assert list(joint_states(a, b)) == [V, O, U, O, O, O, U, O, U]


def test_events_and_hours_to_change():
    states = np.array([O, O, V, V, V, O, U, V], dtype=np.int8)
    times = [f"t{i}" for i in range(8)]
    assert [(e.time_utc, e.event) for e in _events(states, times, "sun")] == [("t2", "rise"), ("t5", "set")]
    assert _hours_to_change(states, 1.0) == [2.0, 1.0, 3.0, 2.0, 1.0, 1.0, None, None]


def test_circular_range_wraps_north():
    assert _circular_range(np.array([350.0, 355.0, 5.0, 10.0])) == (350.0, 10.0)
    assert _circular_range(np.array([100.0, 120.0])) == (100.0, 120.0)


def test_smallest_height_finds_the_threshold():
    calls = []

    def passes(h):
        calls.append(h)
        return h >= 7.0
    assert _smallest_height(passes, 2.0) == 7.0
    assert len(calls) <= 7                           # bisection, not a full scan
    assert _smallest_height(lambda h: False, 2.0) is None
    assert _smallest_height(lambda h: True, 19.8) == 20.0


# -- real data -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sky():
    return SkyGrid.load()


@pytest.fixture(scope="module")
def site01():
    return SiteTerrain.load(load_sites()["site01"])


LIMITS = [Constraint("max_continuous_darkness_hours", "<=", 100.0),
          Constraint("max_continuous_earth_blackout_hours", "<=", 200.0)]


@needs_data
@pytest.mark.parametrize("hours", [24, 336])
def test_calendar_equals_analyze(sky, site01, hours):
    """Every calendar entry must equal the approved /analyze metrics for that start."""
    vis = grid_visibility(site01, sky, 2.0, 2.0)
    starts = np.random.default_rng(hours).integers(0, sky.size - hours - 1, 25)
    cal = calendar(vis, starts, hours, 100.0, 200.0)
    for i, s in enumerate(starts):
        a = analyze(site01, sky, MissionWindow(sky.utc_start + timedelta(hours=int(s)), hours * 3600.0, 3600),
                    Vehicle(2.0, 2.0), LIMITS)
        assert cal.sun.visible_fraction[i] == a.metrics["sun_visible_fraction"].value
        assert cal.sun.longest_outage_h[i] == a.metrics["max_continuous_darkness_hours"].value
        assert cal.earth.visible_fraction[i] == a.metrics["earth_visible_fraction"].value
        assert cal.earth.longest_outage_h[i] == a.metrics["max_continuous_earth_blackout_hours"].value
        assert cal.status[i] == a.feasibility


@needs_data
def test_rescue_mast_height_is_the_true_minimum(sky, site01):
    """The bisected mast height must pass, and every lower 0.5 m step must fail."""
    window = MissionWindow(parse_utc("2030-12-01T00:00:00Z"), 336 * 3600.0, 3600)
    mission = _Mission(site01, sky, window)

    def passes(h):
        m = window_metrics(mission.sun(h), np.array([0]), mission.length)
        return m.longest_outage_h[0] <= 24.0
    found = _smallest_height(passes, 2.0)
    assert found is not None and passes(found)
    assert not any(passes(h) for h in np.arange(2.5, found, 0.5))


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


SITE01 = {"latitude_deg": -89.463163, "longitude_deg_east": 222.510447}
VEHICLE = {"solar_panel_mast_height_m": 2.0, "antenna_height_m": 2.0}
FAILING = {"site": SITE01, "mission": {"start_utc": "2030-12-01T00:00:00Z", "duration_hours": 336,
                                       "sample_step_seconds": 3600},
           "vehicle": VEHICLE, "constraints": {"max_darkness_hours": 24, "max_earth_blackout_hours": 200}}


@needs_data
def test_calendar_endpoint_matches_analyze_endpoint(client):
    body = {"site": SITE01, "vehicle": VEHICLE, "constraints": FAILING["constraints"], "duration_hours": 336,
            "start_from_utc": "2030-11-01T00:00:00Z", "start_to_utc": "2030-12-31T00:00:00Z", "start_step_hours": 24}
    cal = client.post("/calendar", json=body).json()
    assert len(cal["starts_utc"]) == 61 and cal["starts_utc"][30] == "2030-12-01T00:00:00Z"
    analysis = client.post("/analyze", json=FAILING).json()["candidate"]
    assert cal["max_darkness_hours"][30] == analysis["metrics"]["max_continuous_darkness_hours"]
    assert cal["status"][30] == analysis["feasibility"]["status"]
    assert cal["feasible_count"] == cal["status"].count("feasible")


@needs_data
def test_calendar_rejects_too_many_starts(client):
    body = {"site": SITE01, "vehicle": VEHICLE, "duration_hours": 24, "start_step_hours": 1}
    response = client.post("/calendar", json=body)
    assert response.status_code == 422 and response.json()["error"] == "too_many_starts"


@needs_data
def test_insights_endpoint(client):
    body = client.post("/insights", json=FAILING).json()
    assert body["summary"] and body["outages"]
    assert len(body["sun_hours_to_change"]) == len(body["timestamps_utc"]) == 337
    assert 0 <= body["joint_visible_fraction"] <= 1


@needs_data
def test_rescue_endpoint_offers_a_taller_mast(client):
    body = client.post("/rescue", json=FAILING).json()
    assert body["baseline"]["status"] == "infeasible"
    mast = next(o for o in body["options"] if o["kind"] == "mast")
    assert mast["fixes"] and mast["change"]["solar_mast_height_m"] > 2.0
    assert mast["outcome"]["max_darkness_hours"] <= 24


@needs_data
def test_rescue_requires_hourly_sampling(client):
    body = {**FAILING, "mission": {**FAILING["mission"], "sample_step_seconds": 7200}}
    assert client.post("/rescue", json=body).status_code == 422
