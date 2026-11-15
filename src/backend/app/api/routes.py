"""
Filename: app/api/routes.py
Description: HTTP endpoints. M0 provides only GET /health; analysis endpoints
    (/sites, /analyze, /compare, /data-provenance) are added once the physics
    core they expose exists, so no endpoint claims to work before it does.
"""

from fastapi import APIRouter

from app import __version__
from app.api.schemas import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report readiness. `datasets` lists loaded artifacts; none exist yet in M0."""
    return HealthResponse(status="ok", version=__version__, datasets={})
