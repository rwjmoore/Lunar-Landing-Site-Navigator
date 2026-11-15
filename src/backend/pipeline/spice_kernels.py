"""
Filename: pipeline/spice_kernels.py
Description: Verifies and loads the DE421 SPICE kernel set listed in
    data/manifests/kernels.json (docs/physics/sky.md section 2). Every kernel's
    SHA-256 is checked before loading so results are reproducible.
"""

import hashlib
import json
from pathlib import Path

import spiceypy

from pipeline import DATA_DIR

MANIFEST_PATH = DATA_DIR / "manifests" / "kernels.json"
KERNEL_DIR = DATA_DIR / "kernels"

# Load order matters only in that the leapseconds kernel must come first.
_LOAD_ORDER = (".tls", ".bsp", ".bpc", ".tf")


def read_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def kernels_available() -> bool:
    """True if every kernel in the manifest exists locally (checksums not checked)."""
    return all((KERNEL_DIR / f["name"]).exists() for f in read_manifest()["files"])


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_kernels() -> list[dict]:
    """Verify checksums, then furnish all kernels. Returns the manifest file entries.

    Raises FileNotFoundError or ValueError if a kernel is missing or altered.
    """
    files = read_manifest()["files"]
    for entry in files:
        path = KERNEL_DIR / entry["name"]
        if not path.exists():
            raise FileNotFoundError(f"missing kernel {path}; see data/manifests/kernels.json")
        if _sha256(path) != entry["sha256"]:
            raise ValueError(f"checksum mismatch for {path}")

    spiceypy.kclear()
    loadable = [f for f in files if Path(f["name"]).suffix in _LOAD_ORDER]
    for entry in sorted(loadable, key=lambda f: _LOAD_ORDER.index(Path(f["name"]).suffix)):
        spiceypy.furnsh(str(KERNEL_DIR / entry["name"]))
    return files
