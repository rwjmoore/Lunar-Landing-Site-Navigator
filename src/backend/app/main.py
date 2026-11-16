"""
Filename: app/main.py
Description: FastAPI application entry point. Run locally with:
    uvicorn app.main:app --reload   (from src/backend)

    Datasets (sky grid, sites, terrain) are loaded once at startup into an
    AnalysisService; /health reports what loaded. Cross-origin access for the
    separately hosted frontend is enabled by listing its origins, comma
    separated, in the LLSN_CORS_ORIGINS environment variable.

    /tiles/elevation/ serves the map's elevation overlay tiles (display only),
    built offline by pipeline.build_elevation_tiles; it returns 404s if they
    haven't been built.
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.routes import router
from app.api.service import AnalysisService, ServiceError
from app.terrain.elevation_tiles import ELEVATION_TILES_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.service = AnalysisService.load()
    yield


app = FastAPI(title="Lunar Landing Site Navigator API", version=__version__, lifespan=lifespan)
app.include_router(router)
app.mount("/tiles/elevation", StaticFiles(directory=ELEVATION_TILES_DIR, check_dir=False), name="elevation-tiles")

_origins = [o.strip() for o in os.environ.get("LLSN_CORS_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Content-Type"])


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code,
                        content={"error": exc.code, "message": exc.message, **exc.details})
