"""
Filename: pipeline/fetch_data.py
Description: Downloads the source data listed in data/manifests/ and verifies
    every file's SHA-256 checksum. Files that are already present with the
    right checksum are skipped, so it is safe to re-run.

    Groups (destination, approximate size):
      terrain     data/raw/terrain/     ~1.04 GB  needed to run the API
      kernels     data/kernels/          ~19 MB   needed only to rebuild the sky grid
      validation  data/raw/validation/  ~102 MB   needed only to rerun the NASA validation

    Run from src/backend:
      python -m pipeline.fetch_data                 # terrain only (enough to run the API)
      python -m pipeline.fetch_data --all           # everything
      python -m pipeline.fetch_data kernels validation
"""

import argparse
import shutil
import sys
import urllib.request
from pathlib import Path

from pipeline import DATA_DIR
from pipeline.checksums import read_manifest, sha256

GROUPS = {
    "terrain": (DATA_DIR / "manifests" / "terrain.json", DATA_DIR / "raw" / "terrain"),
    "kernels": (DATA_DIR / "manifests" / "kernels.json", DATA_DIR / "kernels"),
    "validation": (DATA_DIR / "manifests" / "validation.json", DATA_DIR / "raw" / "validation"),
}
DEFAULT_GROUPS = ("terrain",)


def fetch_group(name: str) -> None:
    manifest_path, destination = GROUPS[name]
    fetch_manifest(manifest_path, destination, name)


def fetch_manifest(manifest_path: Path, destination: Path, label: str = "") -> None:
    """Download every file in a manifest into `destination`, verifying checksums.

    Each download is written to '<name>.part' and only renamed into place once
    its SHA-256 matches, so a failed or corrupted download never leaves a file
    that looks valid.
    """
    manifest = read_manifest(manifest_path)
    destination.mkdir(parents=True, exist_ok=True)
    total_mb = sum(f["bytes"] for f in manifest["files"]) / 1e6
    print(f"[{label}] {len(manifest['files'])} files, {total_mb:,.0f} MB -> {destination}")

    for entry in manifest["files"]:
        target = destination / entry["name"]
        if target.exists() and sha256(target) == entry["sha256"]:
            print(f"  ok       {entry['name']} (already present)")
            continue
        url = manifest["source_base_url"] + entry["path"]
        partial = target.with_name(target.name + ".part")
        print(f"  download {entry['name']} ({entry['bytes'] / 1e6:,.1f} MB)", flush=True)
        with urllib.request.urlopen(url, timeout=120) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out, length=1 << 20)
        if sha256(partial) != entry["sha256"]:
            partial.unlink()
            raise SystemExit(f"checksum mismatch for {entry['name']} from {url}; nothing was kept")
        partial.replace(target)
        print(f"  ok       {entry['name']} (checksum verified)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and verify the project's source data.")
    parser.add_argument("groups", nargs="*", choices=list(GROUPS),
                        help="which data to fetch (default: terrain)")
    parser.add_argument("--all", action="store_true", help="fetch every group")
    args = parser.parse_args()
    groups = list(GROUPS) if args.all else (args.groups or list(DEFAULT_GROUPS))
    for name in groups:
        fetch_group(name)
    print("done")


if __name__ == "__main__":
    sys.exit(main())
