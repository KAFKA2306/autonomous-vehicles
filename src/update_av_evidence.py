#!/usr/bin/env python3
"""Publish government-source AV evidence without inventing exposure-adjusted safety rates."""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from collect_nhtsa_sgo import DOWNLOADS, collect_sources, write_revision
from revision_integrity import verify_revision_integrity

ROOT = Path(__file__).resolve().parents[1]
DMV_REPORT_YEARS = (2023, 2024, 2025)
DMV_URL = "https://www.dmv.ca.gov/portal/file/{year}-autonomous-{kind}-reports-csv/"
DMV_PERMITS = ROOT / "data" / "california-dmv-permits.json"
DMV_STATEWIDE = ROOT / "data" / "california-dmv-testing.json"
DMV_PROGRAM_URL = "https://www.dmv.ca.gov/portal/vehicle-industry-services/autonomous-vehicles/"
DMV_RESOURCES_URL = (
    DMV_PROGRAM_URL + "autonomous-vehicles-program-permit-resources/"
)
UA = "autonomous-vehicles/1.0 github.com/KAFKA2306/autonomous-vehicles"


def dump(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def fetch_optional(url: str) -> tuple[int, bytes | None]:
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "text/csv,*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return 404, None
        raise


def read_csv(raw: bytes) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="replace")))
    rows = [
        {str(key or "").strip(): str(value or "").strip() for key, value in row.items()}
        for row in reader
    ]
    if not reader.fieldnames or not rows:
        raise ValueError("government CSV is empty")
    return rows


def number(value: str) -> float | None:
    text = value.replace(",", "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def integer(value: str) -> int | None:
    parsed = number(value)
    return int(parsed) if parsed is not None and parsed.is_integer() else None


def iso_date(value: str) -> str | None:
    for pattern in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value.strip(), pattern).date().isoformat()
        except ValueError:
            continue
    return None


def month_period(value: str) -> str | None:
    try:
        return datetime.strptime(value.strip().upper(), "%b-%Y").strftime("%Y-%m")
    except ValueError:
        return None


def report_period(year: int) -> dict[str, str]:
    return {"start": f"{year - 1}-12-01", "end": f"{year}-11-30"}


def dmv_revision_id(sources: list[dict[str, Any]]) -> str:
    identity = "\n".join(
        sorted(
            f"{item['year']}:{item['kind']}:{item.get('sha256', item['http_status'])}"
            for item in sources
        )
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def collect_dmv() -> tuple[dict[str, Any], dict[str, bytes]]:
    raw_files: dict[str, bytes] = {}
    sources: list[dict[str, Any]] = []
    for year in DMV_REPORT_YEARS:
        for kind in ("vehicle-disengagement", "mileage"):
            url = DMV_URL.format(year=year, kind=kind)
            status, raw = fetch_optional(url)
            item: dict[str, Any] = {
                "year": year,
                "kind": kind,
                "url": url,
                "http_status": status,
            }
            if raw is not None:
                rows = read_csv(raw)
                filename = f"{year}-{kind}.csv"
                raw_files[filename] = raw
                item.update(
                    {
                        "filename": filename,
                        "rows": len(rows),
                        "bytes": len(raw),
                        "sha256": sha256(raw),
                    }
                )
            sources.append(item)
    required = {(2024, "vehicle-disengagement"), (2024, "mileage")}
    available = {
        (item["year"], item["kind"])
        for item in sources
        if item["http_status"] == 200
    }
    if not required <= available:
        raise ValueError(
            f"required 2024 California DMV sources unavailable: {required - available}"
        )
    return (
        {
            "schema_version": 1,
            "publisher": "California Department of Motor Vehicles",
            "retrieved_at": datetime.now(UTC).isoformat(),
            "sources": sources,
            "revision_id": dmv_revision_id(sources),
        },
        raw_files,
    )


def _dmv_file_hashes(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        str(item["filename"]): str(item["sha256"])
        for item in manifest["sources"]
        if item.get("http_status") == 200
    }


def write_dmv_revision(
    manifest: dict[str, Any], raw_files: dict[str, bytes], root: Path
) -> Path:
    revision = str(manifest["revision_id"])
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        raise ValueError("California DMV revision manifest sources must be a list")
    verify_revision_integrity(
        target=None,
        expected_revision_id=revision,
        manifest_revision_id=revision,
        recomputed_revision_id=dmv_revision_id(sources),
        raw_files=raw_files,
        manifest_file_hashes=_dmv_file_hashes(manifest),
    )

    target = root / revision
    manifest_path = target / "manifest.json"
    if manifest_path.exists():
        stored = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            raise ValueError("California DMV revision manifest must be a JSON object")
        stored_sources = stored.get("sources")
        if not isinstance(stored_sources, list):
            raise ValueError("California DMV revision manifest sources must be a list")
        verify_revision_integrity(
            target=target,
            expected_revision_id=revision,
            manifest_revision_id=str(stored.get("revision_id", "")),
            recomputed_revision_id=dmv_revision_id(stored_sources),
            raw_files=raw_files,
            manifest_file_hashes=_dmv_file_hashes(stored),
        )
        return manifest_path
    target.mkdir(parents=True, exist_ok=True)
    for filename, raw in raw_files.items():
        (target / filename).write_bytes(raw)
    manifest_path.write_bytes(dump(manifest))
    return manifest_path


def dmv_company_view(
    year: int, disengagement_raw: bytes, mileage_raw: bytes
) -> dict[str, Any]:
    events = read_csv(disengagement_raw)
    mileage = read_csv(mileage_raw)
    event_counts: Counter[tuple[str, str]] = Counter()
    event_records: list[dict[str, Any]] = []
    for index, row in enumerate(events, start=1):
        identity = (row.get("Permit Number", ""), row.get("Manufacturer", ""))
        event_counts[identity] += 1
        event_records.append(
            {
                "source_row": index,
                "manufacturer": identity[1],
                "permit_number": identity[0],
                "event_date": iso_date(row.get("DATE", "")),
                "vehicle_capable_driverless": row.get(
                    "VEHICLE IS CAPABLE OF OPERATING WITHOUT A DRIVER\n(Yes or No)", ""
                ),
                "driver_present": row.get("DRIVER PRESENT\n(Yes or No)", ""),
                "initiated_by": row.get(
                    "DISENGAGEMENT INITIATED BY\n"
                    "(AV System, Test Driver, Remote Operator, or Passenger)",
                    "",
                ),
                "location": row.get(
                    "DISENGAGEMENT\nLOCATION\n"
                    "(Interstate, Freeway, Highway, Rural Road, Street, or Parking Facility)",
                    "",
                ),
                "facts": row.get("DESCRIPTION OF FACTS CAUSING DISENGAGEMENT", ""),
            }
        )

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in mileage:
        identity = (row.get("Permit Number", ""), row.get("Manufacturer", ""))
        item = grouped.setdefault(
            identity,
            {
                "manufacturer": identity[1],
                "permit_number": identity[0],
                "vehicle_rows": 0,
                "autonomous_testing_miles": 0.0,
                "reported_disengagements": 0,
            },
        )
        item["vehicle_rows"] += 1
        miles = number(row.get("ANNUAL TOTAL", ""))
        disengagements = integer(row.get("Annual Total of Disengagements", ""))
        if miles is not None:
            item["autonomous_testing_miles"] += miles
        if disengagements is not None:
            item["reported_disengagements"] += disengagements

    companies: list[dict[str, Any]] = []
    for identity, item in grouped.items():
        event_count = event_counts.get(identity, 0)
        reported = int(item["reported_disengagements"])
        miles = round(float(item["autonomous_testing_miles"]), 3)
        count_match = event_count == reported
        ratio = round(miles / reported, 6) if count_match and reported > 0 else None
        companies.append(
            {
                **item,
                "autonomous_testing_miles": miles,
                "event_row_count": event_count,
                "source_count_match": count_match,
                "testing_miles_per_disengagement": ratio,
                "comparison_status": (
                    "same_period_same_permit_denominator"
                    if ratio is not None
                    else "no_comparable_nonzero_denominator"
                ),
            }
        )
    companies.sort(
        key=lambda item: (str(item["manufacturer"]), str(item["permit_number"]))
    )
    return {
        "schema_version": 1,
        "report_year": year,
        "period": report_period(year),
        "jurisdiction": "California",
        "scope": "public-road autonomous testing under California DMV testing permits",
        "metric_warning": (
            "testing_miles_per_disengagement is an operational testing metric, not a safety rate "
            "or cross-company safety ranking"
        ),
        "event_count": len(event_records),
        "events": event_records,
        "companies": companies,
    }


def latest_nhtsa_reports(
    category: str, raw: bytes, source_sha: str
) -> list[dict[str, Any]]:
    rows = read_csv(raw)
    by_report: dict[str, dict[str, str]] = {}
    for row in rows:
        report_id = row.get("Report ID", "")
        if not report_id:
            continue
        current = by_report.get(report_id)
        version = integer(row.get("Report Version", "")) or 0
        current_version = integer(current.get("Report Version", "")) if current else -1
        if current is None or version > (current_version or 0):
            by_report[report_id] = row
    records = []
    for report_id, row in by_report.items():
        records.append(
            {
                "category": category,
                "report_id": report_id,
                "report_version": integer(row.get("Report Version", "")),
                "reporting_entity": row.get("Reporting Entity", ""),
                "operating_entity": row.get("Operating Entity", ""),
                "report_type": row.get("Report Type", ""),
                "report_submission_date": row.get("Report Submission Date", ""),
                "automation_system_engaged": row.get("Automation System Engaged?", ""),
                "engagement_status": row.get("Engagement Status", ""),
                "driver_operator_type": row.get("Driver / Operator Type", ""),
                "incident_month": month_period(row.get("Incident Date", "")),
                "same_incident_id": row.get("Same Incident ID", ""),
                "state": row.get("State", ""),
                "make": row.get("Make", ""),
                "model": row.get("Model", ""),
                "model_year": row.get("Model Year", ""),
                "crash_with": row.get("Crash With", ""),
                "highest_injury_severity_alleged": row.get(
                    "Highest Injury Severity Alleged", ""
                ),
                "source_url": DOWNLOADS[category],
                "source_sha256": source_sha,
            }
        )
    return sorted(
        records, key=lambda item: (str(item["incident_month"]), item["report_id"])
    )


def nhtsa_view(manifest: dict[str, Any], raw_files: dict[str, bytes]) -> dict[str, Any]:
    source_sha = {
        str(item["category"]): str(item["sha256"]) for item in manifest["datasets"]
    }
    categories: dict[str, Any] = {}
    for category in ("ads", "level_2_adas", "other"):
        records = latest_nhtsa_reports(category, raw_files[category], source_sha[category])
        recent = [
            item
            for item in records
            if item["incident_month"] and str(item["incident_month"]) >= "2024-01"
        ]
        monthly: Counter[str] = Counter(str(item["incident_month"]) for item in recent)
        entities: Counter[str] = Counter(str(item["reporting_entity"]) for item in recent)
        california = [item for item in recent if item["state"] == "CA"]
        california_monthly: Counter[str] = Counter(
            str(item["incident_month"]) for item in california
        )
        incident_ids = {
            item["same_incident_id"] for item in california if item["same_incident_id"]
        }
        categories[category] = {
            "latest_report_count": len(records),
            "records": records,
            "monthly_report_counts_2024_plus": dict(sorted(monthly.items())),
            "reporting_entity_counts_2024_plus": dict(sorted(entities.items())),
            "california_report_count_2024_plus": len(california),
            "california_monthly_report_counts_2024_plus": dict(
                sorted(california_monthly.items())
            ),
            "california_distinct_same_incident_id_count_2024_plus": len(incident_ids),
        }
    return {
        "schema_version": 1,
        "publisher": manifest["publisher"],
        "dataset": "NHTSA Standing General Order crash reports",
        "source_page": manifest["source_page"],
        "source_revision_id": manifest["revision_id"],
        "categories": categories,
        "comparison_warning": (
            "report counts are not exposure-normalized; ADS and Level 2 ADAS stay separate, "
            "and no company safety rate is produced without a matching mileage denominator"
        ),
        "california_crash_view_rule": (
            "California crash history uses NHTSA SGO rows with state=CA; report counts and "
            "Same Incident ID counts are both exposed because reports can be revised or duplicated"
        ),
    }


def build_dmv_view(
    manifest: dict[str, Any], raw_files: dict[str, bytes]
) -> dict[str, Any]:
    available: dict[int, dict[str, str]] = defaultdict(dict)
    source_meta: dict[tuple[int, str], dict[str, Any]] = {}
    for item in manifest["sources"]:
        year = int(item["year"])
        kind = str(item["kind"])
        source_meta[(year, kind)] = item
        if item["http_status"] == 200:
            available[year][kind] = str(item["filename"])

    reports: dict[str, Any] = {}
    for year, files in sorted(available.items()):
        if {"vehicle-disengagement", "mileage"} <= files.keys():
            view = dmv_company_view(
                year,
                raw_files[files["vehicle-disengagement"]],
                raw_files[files["mileage"]],
            )
            view["sources"] = {
                kind: {
                    "url": source_meta[(year, kind)]["url"],
                    "sha256": source_meta[(year, kind)]["sha256"],
                }
                for kind in ("vehicle-disengagement", "mileage")
            }
            reports[str(year)] = view

    statewide = json.loads(DMV_STATEWIDE.read_text(encoding="utf-8"))
    permits = json.loads(DMV_PERMITS.read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "publisher": manifest["publisher"],
        "source_revision_id": manifest["revision_id"],
        "company_testing_reports": reports,
        "statewide_testing_observations": statewide["observations"],
        "permit_snapshot": permits,
        "unavailable_sources": [
            {
                "year": item["year"],
                "kind": item["kind"],
                "url": item["url"],
                "http_status": 404,
            }
            for item in manifest["sources"]
            if item["http_status"] == 404
        ],
        "current_reporting_surface": {
            "source_url": DMV_RESOURCES_URL,
            "metrics": [
                "vehicle miles traveled",
                "dynamic-driving-task performance relevant system failures",
                "vehicle immobilizations",
                "braking events",
                "collisions",
                "notices of autonomous vehicle noncompliance",
            ],
        },
    }


def publish(
    evidence_root: Path,
    api_dir: Path,
    nhtsa_manifest: dict[str, Any],
    nhtsa_raw: dict[str, bytes],
    dmv_manifest: dict[str, Any],
    dmv_raw: dict[str, bytes],
) -> dict[str, Any]:
    nhtsa_manifest_path = write_revision(
        nhtsa_manifest, nhtsa_raw, evidence_root / "nhtsa" / "sgo" / "revisions"
    )
    dmv_manifest_path = write_dmv_revision(
        dmv_manifest, dmv_raw, evidence_root / "california" / "dmv" / "revisions"
    )
    nhtsa = nhtsa_view(nhtsa_manifest, nhtsa_raw)
    dmv = build_dmv_view(dmv_manifest, dmv_raw)
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "nhtsa-sgo.json").write_bytes(dump(nhtsa))
    (api_dir / "california-dmv.json").write_bytes(dump(dmv))
    index = {
        "schema_version": 1,
        "dataset": "Autonomous Vehicles government evidence",
        "views": {
            "nhtsa_sgo": "nhtsa-sgo.json",
            "california_dmv": "california-dmv.json",
        },
        "evidence": {
            "nhtsa_revision_manifest": display_path(nhtsa_manifest_path),
            "california_dmv_revision_manifest": display_path(dmv_manifest_path),
        },
        "rules": [
            "ADS and Level 2 ADAS are separate categories",
            "testing and deployment are separate scopes",
            (
                "latest report version is selected per NHTSA Report ID while raw revisions "
                "remain stored"
            ),
            "no exposure-adjusted safety rate is produced without a same-period denominator",
            "California testing miles per disengagement is not a safety ranking",
        ],
        "sources": [nhtsa_manifest["source_page"], DMV_PROGRAM_URL, DMV_RESOURCES_URL],
    }
    (api_dir / "index.json").write_bytes(dump(index))
    return {"nhtsa": nhtsa, "dmv": dmv, "index": index}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--api-dir", type=Path, default=ROOT / "api" / "v1" / "autonomous-vehicles"
    )
    args = parser.parse_args()
    nhtsa_manifest, nhtsa_raw = collect_sources()
    dmv_manifest, dmv_raw = collect_dmv()
    result = publish(
        args.evidence_root,
        args.api_dir,
        nhtsa_manifest,
        nhtsa_raw,
        dmv_manifest,
        dmv_raw,
    )
    print(
        json.dumps(
            {
                "nhtsa_ads": result["nhtsa"]["categories"]["ads"]["latest_report_count"],
                "nhtsa_level_2_adas": result["nhtsa"]["categories"]["level_2_adas"][
                    "latest_report_count"
                ],
                "dmv_company_report_years": sorted(
                    result["dmv"]["company_testing_reports"].keys()
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
