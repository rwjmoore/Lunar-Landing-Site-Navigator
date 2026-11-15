"""
Filename: tests/test_health.py
Description: Tests for GET /health, the readiness endpoint.
"""

from fastapi.testclient import TestClient

from app import __version__
from app.main import app

client = TestClient(app)


def test_health_reports_ok_and_version():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "datasets": {}}
