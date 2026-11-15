"""
Filename: tests/test_fetch_data.py
Description: Tests for the data download script (pipeline/fetch_data.py)
    using a local file:// "server": downloads are checksum-verified, valid
    files are skipped, and a corrupted download leaves nothing behind.
"""

import hashlib
import json

import pytest

from pipeline.fetch_data import GROUPS, fetch_manifest


def make_source(tmp_path, content: bytes, recorded_sha: str | None = None):
    """A source folder with one file and a manifest pointing at it via file://."""
    source = tmp_path / "source"
    source.mkdir()
    (source / "data.bin").write_bytes(content)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "source_base_url": source.as_uri() + "/",
        "files": [{"name": "data.bin", "path": "data.bin", "bytes": len(content),
                   "sha256": recorded_sha or hashlib.sha256(content).hexdigest()}],
    }), encoding="utf-8")
    return manifest


def test_downloads_and_verifies(tmp_path):
    manifest = make_source(tmp_path, b"lunar terrain")
    destination = tmp_path / "out"

    fetch_manifest(manifest, destination)

    assert (destination / "data.bin").read_bytes() == b"lunar terrain"
    assert not (destination / "data.bin.part").exists()


def test_skips_files_already_present(tmp_path, capsys):
    manifest = make_source(tmp_path, b"lunar terrain")
    destination = tmp_path / "out"
    fetch_manifest(manifest, destination)

    fetch_manifest(manifest, destination)

    assert "already present" in capsys.readouterr().out


def test_corrupted_download_keeps_nothing(tmp_path):
    manifest = make_source(tmp_path, b"lunar terrain", recorded_sha="0" * 64)
    destination = tmp_path / "out"

    with pytest.raises(SystemExit, match="checksum mismatch"):
        fetch_manifest(manifest, destination)

    assert list(destination.iterdir()) == []


def test_every_group_has_a_manifest():
    for manifest_path, _ in GROUPS.values():
        files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
        assert files and all({"name", "path", "bytes", "sha256"} <= set(f) for f in files)
