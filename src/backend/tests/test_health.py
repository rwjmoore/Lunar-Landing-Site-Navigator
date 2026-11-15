"""
Filename: tests/test_health.py
Description: Tests for GET /health, the readiness endpoint.
"""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app


def test_health_reports_ok_version_and_datasets():
    with TestClient(app) as client:  # runs startup, which loads the datasets
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert set(body["datasets"]) == {"sky_grid", "sites", "terrain", "region_terrain"}
