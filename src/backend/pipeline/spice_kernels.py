"""
Filename: pipeline/spice_kernels.py
Description: Verifies and loads the DE421 SPICE kernel set listed in
    data/manifests/kernels.json (docs/physics/sky.md section 2). Every kernel's
    SHA-256 is checked before loading so results are reproducible.
"""

from pathlib import Path

import spiceypy

from pipeline import DATA_DIR
from pipeline.checksums import all_present, verify

MANIFEST_PATH = DATA_DIR / "manifests" / "kernels.json"
KERNEL_DIR = DATA_DIR / "kernels"

# Load order matters only in that the leapseconds kernel must come first.
_LOAD_ORDER = (".tls", ".bsp", ".bpc", ".tf")


def kernels_available() -> bool:
    """True if every kernel in the manifest exists locally (checksums not checked)."""
    return all_present(MANIFEST_PATH, KERNEL_DIR)


def load_kernels() -> list[dict]:
    """Verify checksums, then furnish all kernels. Returns the manifest file entries.

    Raises FileNotFoundError or ValueError if a kernel is missing or altered.
    """
    files = verify(MANIFEST_PATH, KERNEL_DIR)
    spiceypy.kclear()
    loadable = [f for f in files if Path(f["name"]).suffix in _LOAD_ORDER]
    for entry in sorted(loadable, key=lambda f: _LOAD_ORDER.index(Path(f["name"]).suffix)):
        spiceypy.furnsh(str(KERNEL_DIR / entry["name"]))
    return files
