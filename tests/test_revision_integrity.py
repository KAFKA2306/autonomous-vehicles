import copy
import json
from pathlib import Path

import pytest

from collect_nhtsa_sgo import DOWNLOADS, csv_inventory, revision_id, write_revision
from update_av_evidence import dmv_revision_id, sha256, write_dmv_revision


def nhtsa_raw() -> dict[str, bytes]:
    return {
        category: f"Report ID,Report Version\n{category},1\n".encode()
        for category in DOWNLOADS
    }


def nhtsa_manifest(raw_files: dict[str, bytes], retrieved_at: str = "2026-09-12T00:00:00+00:00") -> dict[str, object]:
    datasets = [
        {
            "category": category,
            "filename": f"{category}.csv",
            "url": DOWNLOADS[category],
            **csv_inventory(raw_files[category]),
        }
        for category in DOWNLOADS
    ]
    return {
        "schema_version": 2,
        "publisher": "National Highway Traffic Safety Administration",
        "dataset": "Standing General Order incident reports",
        "first_retrieved_at": retrieved_at,
        "source_page": "https://www.nhtsa.gov/es/node/103486",
        "datasets": datasets,
        "revision_id": revision_id(datasets),
    }


def dmv_raw() -> dict[str, bytes]:
    return {
        "2024-mileage.csv": b"Manufacturer,Permit Number\nExample,AVT001\n",
        "2024-vehicle-disengagement.csv": b"Manufacturer,Permit Number\nExample,AVT001\n",
    }


def dmv_manifest(raw_files: dict[str, bytes], retrieved_at: str = "2026-09-12T00:00:00+00:00") -> dict[str, object]:
    sources = [
        {
            "year": 2024,
            "kind": "mileage",
            "url": "https://example.invalid/2024-mileage.csv",
            "http_status": 200,
            "filename": "2024-mileage.csv",
            "rows": 1,
            "bytes": len(raw_files["2024-mileage.csv"]),
            "sha256": sha256(raw_files["2024-mileage.csv"]),
        },
        {
            "year": 2024,
            "kind": "vehicle-disengagement",
            "url": "https://example.invalid/2024-vehicle-disengagement.csv",
            "http_status": 200,
            "filename": "2024-vehicle-disengagement.csv",
            "rows": 1,
            "bytes": len(raw_files["2024-vehicle-disengagement.csv"]),
            "sha256": sha256(raw_files["2024-vehicle-disengagement.csv"]),
        },
        {
            "year": 2025,
            "kind": "mileage",
            "url": "https://example.invalid/2025-mileage.csv",
            "http_status": 404,
        },
    ]
    return {
        "schema_version": 1,
        "publisher": "California Department of Motor Vehicles",
        "retrieved_at": retrieved_at,
        "sources": sources,
        "revision_id": dmv_revision_id(sources),
    }


def test_intact_revisions_are_reused_without_rewriting_manifest(tmp_path: Path):
    n_raw = nhtsa_raw()
    n_first = nhtsa_manifest(n_raw)
    n_path = write_revision(n_first, n_raw, tmp_path / "nhtsa")
    n_original = n_path.read_bytes()
    n_second = nhtsa_manifest(n_raw, "2026-09-13T00:00:00+00:00")
    assert write_revision(n_second, n_raw, tmp_path / "nhtsa") == n_path
    assert n_path.read_bytes() == n_original

    d_raw = dmv_raw()
    d_first = dmv_manifest(d_raw)
    d_path = write_dmv_revision(d_first, d_raw, tmp_path / "dmv")
    d_original = d_path.read_bytes()
    d_second = dmv_manifest(d_raw, "2026-09-13T00:00:00+00:00")
    assert write_dmv_revision(d_second, d_raw, tmp_path / "dmv") == d_path
    assert d_path.read_bytes() == d_original


def test_nhtsa_reuse_fails_when_raw_file_is_missing(tmp_path: Path):
    raw_files = nhtsa_raw()
    manifest = nhtsa_manifest(raw_files)
    path = write_revision(manifest, raw_files, tmp_path)
    (path.parent / "ads.csv").unlink()

    with pytest.raises(ValueError, match="raw file missing"):
        write_revision(manifest, raw_files, tmp_path)


def test_nhtsa_reuse_fails_when_raw_bytes_change(tmp_path: Path):
    raw_files = nhtsa_raw()
    manifest = nhtsa_manifest(raw_files)
    path = write_revision(manifest, raw_files, tmp_path)
    (path.parent / "ads.csv").write_bytes(raw_files["ads"] + b"x")

    with pytest.raises(ValueError, match="raw bytes mismatch"):
        write_revision(manifest, raw_files, tmp_path)


def test_nhtsa_reuse_fails_when_manifest_sha_changes(tmp_path: Path):
    raw_files = nhtsa_raw()
    manifest = nhtsa_manifest(raw_files)
    path = write_revision(manifest, raw_files, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["datasets"][0]["sha256"] = "0" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ValueError, match="source identity mismatch"):
        write_revision(manifest, raw_files, tmp_path)


def test_dmv_reuse_fails_when_raw_bytes_change(tmp_path: Path):
    raw_files = dmv_raw()
    manifest = dmv_manifest(raw_files)
    path = write_dmv_revision(manifest, raw_files, tmp_path)
    target = path.parent / "2024-mileage.csv"
    target.write_bytes(target.read_bytes() + b"x")

    with pytest.raises(ValueError, match="raw bytes mismatch"):
        write_dmv_revision(manifest, raw_files, tmp_path)


def test_dmv_reuse_fails_when_manifest_revision_id_changes(tmp_path: Path):
    raw_files = dmv_raw()
    manifest = dmv_manifest(raw_files)
    path = write_dmv_revision(manifest, raw_files, tmp_path)
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["revision_id"] = "0" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(ValueError, match="manifest id mismatch"):
        write_dmv_revision(manifest, raw_files, tmp_path)


def test_incoming_manifest_must_match_current_source_bytes(tmp_path: Path):
    raw_files = dmv_raw()
    manifest = dmv_manifest(raw_files)
    tampered = copy.deepcopy(manifest)
    tampered["sources"][0]["sha256"] = "0" * 64

    with pytest.raises(ValueError, match="source identity mismatch"):
        write_dmv_revision(tampered, raw_files, tmp_path)
