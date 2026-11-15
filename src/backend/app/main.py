"""
Filename: app/main.py
Description: FastAPI application entry point. Run locally with:
    uvicorn app.main:app --reload   (from src/backend)
"""

from fastapi import FastAPI

from app import __version__
from app.api.routes import router

app = FastAPI(title="Lunar Landing Site Navigator API", version=__version__)
app.include_router(router)
