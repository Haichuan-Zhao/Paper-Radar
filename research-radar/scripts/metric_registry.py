#!/usr/bin/env python3
"""Manage and validate Research Radar metric-release freshness metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 1
KNOWN_SOURCES = ("jcr", "cas", "ccf")
DEFAULT_URLS = {
    "jcr": "https://clarivate.com/products/journal-citation-reports/",
    "cas": "https://www.fenqubiao.com/",
    "ccf": "https://www.ccf.org.cn/Academic_Evaluation/By_category/",
}
OFFICIAL_DOMAINS = {
    "jcr": ("clarivate.com",),
    "cas": ("fenqubiao.com",),
    "ccf": ("ccf.org.cn",),
}


class RegistryError(ValueError):
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return now_utc().isoformat()


def empty_source(source: str) -> dict[str, Any]:
    return {
        "status": "unconfigured",
        "latest_official_edition": None,
        "local_data_edition": None,
        "official_checked_at": None,
        "data_refreshed_at": None,
        "source_url": DEFAULT_URLS[source],
        "max_check_age_hours": 24,
        "notes": None,
    }


def empty_registry() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "sources": {source: empty_source(source) for source in KNOWN_SOURCES},
    }


def load_registry(path: Path, allow_missing: bool = False) -> dict[str, Any]:
    if not path.exists():
        if allow_missing:
            return empty_registry()
        raise RegistryError(f"Metric registry does not exist: {path}")
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryError(f"Cannot read metric registry {path}: {exc}") from exc
    if not isinstance(registry, dict) or registry.get("schema_version") != SCHEMA_VERSION:
        raise RegistryError("Unsupported or missing metric registry schema_version")
    if not isinstance(registry.get("sources"), dict):
        raise RegistryError("Metric registry sources must be an object")
    for source in KNOWN_SOURCES:
        if source not in registry["sources"]:
            registry["sources"][source] = empty_source(source)
    return registry


def atomic_write(path: Path, registry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def valid_official_url(source: str, value: Any) -> bool:
    try:
        parsed = urlparse(str(value or "").strip())
    except ValueError:
        return False
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host:
        return False
    return any(host == domain or host.endswith(f".{domain}") for domain in OFFICIAL_DOMAINS[source])


def source_state(source: str, entry: Any, at: datetime | None = None) -> dict[str, Any]:
    at = at or now_utc()
    if not isinstance(entry, dict):
        return {"source": source, "current": False, "problems": ["entry is not an object"]}
    problems: list[str] = []
    status = str(entry.get("status") or "").strip().lower()
    latest = str(entry.get("latest_official_edition") or "").strip()
    local = str(entry.get("local_data_edition") or "").strip()
    checked = parse_time(entry.get("official_checked_at"))
    refreshed = parse_time(entry.get("data_refreshed_at"))
    try:
        max_age = float(entry.get("max_check_age_hours", 24))
    except (TypeError, ValueError):
        max_age = math.nan

    if status != "verified":
        problems.append(f"status is {status or 'missing'}, not verified")
    if not latest:
        problems.append("latest_official_edition is missing")
    if not local:
        problems.append("local_data_edition is missing")
    if latest and local and latest != local:
        problems.append(f"local edition {local} differs from official edition {latest}")
    if checked is None:
        problems.append("official_checked_at is missing or invalid")
        age_hours = None
    else:
        age_hours = (at - checked).total_seconds() / 3600
        if age_hours < -0.1:
            problems.append("official_checked_at is in the future")
        if not math.isfinite(max_age) or max_age <= 0:
            problems.append("max_check_age_hours must be positive")
        elif age_hours > max_age:
            problems.append(f"official check is stale ({age_hours:.1f}h > {max_age:g}h)")
    if refreshed is None:
        problems.append("data_refreshed_at is missing or invalid")
    elif (refreshed - at).total_seconds() > 360:
        problems.append("data_refreshed_at is in the future")
    if not valid_official_url(source, entry.get("source_url")):
        problems.append("source_url is not an approved official HTTPS domain")
    return {
        "source": source,
        "current": not problems,
        "latest_official_edition": latest or None,
        "local_data_edition": local or None,
        "official_checked_at": entry.get("official_checked_at"),
        "data_refreshed_at": entry.get("data_refreshed_at"),
        "check_age_hours": round(age_hours, 2) if age_hours is not None else None,
        "max_check_age_hours": max_age if math.isfinite(max_age) else None,
        "source_url": entry.get("source_url"),
        "problems": problems,
    }


def registry_status(
    registry: dict[str, Any],
    sources: list[str] | tuple[str, ...] | None = None,
    at: datetime | None = None,
) -> dict[str, Any]:
    requested = list(sources or KNOWN_SOURCES)
    unknown = sorted(set(requested) - set(KNOWN_SOURCES))
    if unknown:
        raise RegistryError(f"Unknown metric sources: {', '.join(unknown)}")
    states = {
        source: source_state(source, registry["sources"].get(source), at=at)
        for source in requested
    }
    return {
        "current": all(state["current"] for state in states.values()),
        "sources": states,
        "registry_sha256": registry_hash(registry),
    }


def registry_hash(registry: dict[str, Any]) -> str:
    payload = json.dumps(registry, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def parse_sources(raw: str | None) -> list[str]:
    if not raw:
        return list(KNOWN_SOURCES)
    values = [value.strip().lower() for value in raw.split(",") if value.strip()]
    if not values:
        raise RegistryError("--sources must not be empty")
    return values


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create an unconfigured registry")

    update = subparsers.add_parser("update", help="Record a verified official release check")
    update.add_argument("--source", required=True, choices=KNOWN_SOURCES)
    update.add_argument("--status", choices=("verified", "unverified", "unavailable"), default="verified")
    update.add_argument("--latest-official-edition", required=True)
    update.add_argument("--local-data-edition", required=True)
    update.add_argument("--source-url", required=True)
    update.add_argument("--official-checked-at", default="now")
    update.add_argument("--data-refreshed-at", default="now")
    update.add_argument("--max-check-age-hours", type=float, default=24.0)
    update.add_argument("--notes")

    status = subparsers.add_parser("status", help="Show freshness status")
    status.add_argument("--sources")
    status.add_argument("--require-current", action="store_true")
    return parser.parse_args(argv)


def resolved_timestamp(value: str) -> str:
    if value == "now":
        return now_iso()
    parsed = parse_time(value)
    if parsed is None:
        raise RegistryError(f"Invalid timestamp: {value}")
    return parsed.isoformat()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        if args.command == "init":
            if args.registry.exists():
                raise RegistryError(f"Registry already exists: {args.registry}")
            registry = empty_registry()
            atomic_write(args.registry, registry)
            output = {"status": "initialized", "registry": str(args.registry), "hash": registry_hash(registry)}
        elif args.command == "update":
            registry = load_registry(args.registry, allow_missing=True)
            if args.max_check_age_hours <= 0:
                raise RegistryError("--max-check-age-hours must be positive")
            if not valid_official_url(args.source, args.source_url):
                allowed = ", ".join(OFFICIAL_DOMAINS[args.source])
                raise RegistryError(f"--source-url must use an official HTTPS domain: {allowed}")
            registry["sources"][args.source] = {
                "status": args.status,
                "latest_official_edition": str(args.latest_official_edition).strip(),
                "local_data_edition": str(args.local_data_edition).strip(),
                "official_checked_at": resolved_timestamp(args.official_checked_at),
                "data_refreshed_at": resolved_timestamp(args.data_refreshed_at),
                "source_url": str(args.source_url).strip(),
                "max_check_age_hours": args.max_check_age_hours,
                "notes": args.notes,
            }
            atomic_write(args.registry, registry)
            output = {
                "status": "updated",
                "source": args.source,
                "state": source_state(args.source, registry["sources"][args.source]),
                "registry_sha256": registry_hash(registry),
            }
        else:
            registry = load_registry(args.registry)
            sources = parse_sources(args.sources)
            output = registry_status(registry, sources)
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if output["current"] or not args.require_current else 3
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except RegistryError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
