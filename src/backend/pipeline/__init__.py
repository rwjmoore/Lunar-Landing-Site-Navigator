"""
Filename: pipeline/__init__.py
Description: Offline data pipeline (PROJECT_PLAN.md section 8.1). Uses heavy
    dependencies (SpiceyPy, later rasterio) installed via the "pipeline" extra.
    The runtime server (package `app`) never imports this package.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPO_ROOT / "data"
