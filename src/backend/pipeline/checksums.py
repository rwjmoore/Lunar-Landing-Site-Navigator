"""
Filename: pipeline/checksums.py
Description: SHA-256 verification of downloaded source files against the
    manifests in data/manifests/ (kernels.json, terrain.json), so every
    pipeline output is traceable to exact input files.
"""

import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_manifest(manifest_path: Path) -> dict:
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def all_present(manifest_path: Path, directory: Path) -> bool:
    """True if every file in the manifest exists in `directory` (checksums not checked)."""
    return all((directory / f["name"]).exists() for f in read_manifest(manifest_path)["files"])


def verify(manifest_path: Path, directory: Path) -> list[dict]:
    """Check every manifest file exists in `directory` with the recorded SHA-256.

    Returns the manifest's file entries. Raises FileNotFoundError or ValueError.
    """
    files = read_manifest(manifest_path)["files"]
    for entry in files:
        path = directory / entry["name"]
        if not path.exists():
            raise FileNotFoundError(f"missing {path}; see {manifest_path}")
        if sha256(path) != entry["sha256"]:
            raise ValueError(f"checksum mismatch for {path}")
    return files
