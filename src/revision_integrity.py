"""Fail-closed integrity checks for content-addressed evidence revisions."""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_revision_integrity(
    *,
    target: Path | None,
    expected_revision_id: str,
    manifest_revision_id: str,
    recomputed_revision_id: str,
    raw_files: Mapping[str, bytes],
    manifest_file_hashes: Mapping[str, str],
) -> None:
    """Verify manifest identity, expected source bytes, and optionally stored raw files."""
    if manifest_revision_id != expected_revision_id:
        raise ValueError(
            "revision manifest id mismatch: "
            f"expected {expected_revision_id}, got {manifest_revision_id}"
        )
    if recomputed_revision_id != expected_revision_id:
        raise ValueError(
            "revision manifest source identity mismatch: "
            f"expected {expected_revision_id}, got {recomputed_revision_id}"
        )

    expected_names = set(raw_files)
    recorded_names = set(manifest_file_hashes)
    if recorded_names != expected_names:
        missing = sorted(expected_names - recorded_names)
        extra = sorted(recorded_names - expected_names)
        raise ValueError(
            f"revision manifest raw file set mismatch: missing={missing}, extra={extra}"
        )

    for filename, raw in raw_files.items():
        recorded_sha = manifest_file_hashes[filename]
        current_sha = sha256(raw)
        if recorded_sha != current_sha:
            raise ValueError(
                f"revision manifest SHA-256 mismatch for {filename}: "
                f"expected {current_sha}, got {recorded_sha}"
            )
        if target is None:
            continue
        path = target / filename
        if not path.is_file():
            raise ValueError(f"revision raw file missing: {path}")
        stored = path.read_bytes()
        if stored != raw:
            raise ValueError(f"revision raw bytes mismatch: {path}")
        if sha256(stored) != recorded_sha:
            raise ValueError(f"revision raw SHA-256 mismatch: {path}")
