"""
Filename: app/api/routes.py
Description: HTTP endpoints (PROJECT_PLAN.md section 7).

    GET  /health            readiness and dataset status
    GET  /sites             supported sites, date range and request limits
    POST /analyze           one site: horizons, Sun/Earth series, metrics, feasibility
    POST /compare           2-4 sites with one shared mission, vehicle and constraints
    GET  /data-provenance   data sources, versions, assumptions and physics docs

    Service errors become JSON bodies {"error": code, "message": ..., ...details}
    with the error's HTTP status (see app/api/service.py).
"""

from fastapi import APIRouter, Request

from app import __version__
from app.api.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    CompareRequest,
    CompareResponse,
    HealthResponse,
    SitesResponse,
)
from app.api.service import AnalysisService

router = APIRouter()


def _service(request: Request) -> AnalysisService:
    return request.app.state.service


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    """Report readiness and which datasets are loaded."""
    return HealthResponse(status="ok", version=__version__, datasets=_service(request).datasets())


@router.get("/sites", response_model=SitesResponse)
def sites(request: Request) -> SitesResponse:
    """Supported sites with coordinates, plus the supported dates and limits."""
    return _service(request).site_summaries()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze(body: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Analyse one site for a mission window and vehicle."""
    return _service(request).analyze(body)


@router.post("/compare", response_model=CompareResponse)
def compare(body: CompareRequest, request: Request) -> CompareResponse:
    """Analyse several sites under identical mission, vehicle and constraints."""
    return _service(request).compare(body)


@router.get("/data-provenance")
def data_provenance(request: Request) -> dict:
    """Data sources, file checksums, build provenance and modelling assumptions."""
    return _service(request).provenance()
