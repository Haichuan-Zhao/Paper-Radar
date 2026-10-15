#!/usr/bin/env python3
"""Match local venue-metric tables (CSV/JSON) to candidate records by identifier.

This is the accuracy backbone for the venue "switches" (only CAS 1, only SCI,
only CCF A, JCR Q1, ...). Metrics come from a user- or institution-supplied file,
never from scraping licensed databases. Every injected metric keeps its source,
edition year, data year, and a `verified: true` flag plus the match method.
"""
from __future__ import annotations

import csv
import copy
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from identifiers import compare_venues, issns, normalize_issn, normalize_title

def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    text = str(value).strip().replace(",", "").replace("%", "")
    if not text:
        return None
    try:
        result = float(text)
        return result if math.isfinite(result) else None
    except ValueError:
        return None


def _quartile(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace(" ", "")
    if text in {"1", "Q1"}:
        return "Q1"
    if text in {"2", "Q2"}:
        return "Q2"
    if text in {"3", "Q3"}:
        return "Q3"
    if text in {"4", "Q4"}:
        return "Q4"
    return None


def _partition(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip().replace("区", "")
    try:
        result = int(text)
    except ValueError:
        return None
    return result if result in {1, 2, 3, 4} else None


def _ccf_rank(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace("类", "")
    if text.startswith("CCF-"):
        text = text[4:]
    return text if text in {"A", "B", "C"} else None


def _top(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "top", "是", "top期刊"}:
        return True
    if text in {"0", "false", "no", "n", "否"}:
        return False
    return None


def _split_csv(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(part).strip() for part in value if str(part).strip()]
    return [part.strip() for part in re.split(r"[;,|]", str(value)) if part.strip()]


def _bool_cell(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "journal": ("journal", "journal_title", "期刊名", "刊名", "期刊", "杂志"),
    "issn_l": ("issn_l", "issn-l", "issn_l(链接issn)", "issn_l（链接issn）", "链接issn", "链接issn_l"),
    "issn": ("issn", "print_issn", "印刷issn", "issn(印刷)", "issn（印刷）", "pissn"),
    "eissn": ("eissn", "electronic_issn", "e-issn", "电子issn", "eissn(电子)", "eissn（电子）"),
    "source": ("source", "来源", "数据来源", "指标来源"),
    "source_url": ("source_url", "url", "来源链接", "来源网址", "出处"),
    "edition_year": ("edition_year", "版次年", "版本年", "release_year", "发布年"),
    "data_year": ("data_year", "数据年", "指标年", "metric_year"),
    "category": ("category", "学科分类", "学科", "类别", "category_name"),
    "jcr_quartile": ("jcr_quartile", "jcr分区", "jcr_q", "jcr", "quartile"),
    "jcr_percentile": ("jcr_percentile", "jcr百分位", "jcr_pct"),
    "jif": ("jif", "影响因子", "if", "impact_factor", "journal_impact_factor"),
    "jif_percentile": ("jif_percentile", "jif百分位", "if百分位", "if_pct"),
    "cas_large_zone": ("cas_large_zone", "中科院大类分区", "cas大类", "大类分区", "中科院分区"),
    "cas_small_zone": ("cas_small_zone", "中科院小类分区", "cas小类", "小类分区"),
    "cas_top": ("cas_top", "是否top", "是否top期刊", "top期刊", "top"),
    "ccf_rank": ("ccf_rank", "ccf等级", "ccf", "ccf类别"),
    "wos_indexes": ("wos_indexes", "wos索引", "收录索引", "索引", "wos", "sci", "scie"),
    "journal_grade": ("journal_grade", "期刊等级", "分级", "grade"),
    "grade_score": ("grade_score", "等级分值", "等级分数", "grade_points"),
    "verified": ("verified", "已核验"),
    "aliases": ("aliases", "刊名别名"),
    "checked_at": ("checked_at", "核验时间"),
}


def _resolve_headers(fieldnames: list[str]) -> dict[str, str]:
    """Map an actual CSV/JSON header to a canonical field name, or None."""
    lower = {name.strip().casefold(): name for name in fieldnames}
    resolved: dict[str, str] = {}
    for canonical, aliases in HEADER_ALIASES.items():
        for alias in aliases:
            if alias.casefold() in lower:
                resolved[canonical] = lower[alias.casefold()]
                break
    return resolved


def _row_to_metrics(row: dict[str, str], defaults: dict[str, Any]) -> dict[str, Any] | None:
    """Convert one table row (with resolved headers) into an injected-metrics object."""
    resolved = row
    edition = str(resolved.get("edition_year") or defaults.get("edition_year") or "").strip()
    data_year = str(resolved.get("data_year") or defaults.get("data_year") or "").strip()
    source = str(resolved.get("source") or defaults.get("source") or "venue_metrics_file").strip()
    source_url = str(resolved.get("source_url") or defaults.get("source_url") or "").strip()
    # JCR release year and JIF data year are different; never infer either.
    edition = edition or None
    data_year = data_year or None

    metrics: dict[str, Any] = {}
    q = _quartile(resolved.get("jcr_quartile"))
    pct = _number(resolved.get("jcr_percentile"))
    category = str(resolved.get("category") or "").strip()
    if q:
        categories = []
        if category:
            entry: dict[str, Any] = {"name": category, "quartile": q}
            if pct is not None:
                entry["percentile"] = pct
            categories.append(entry)
        metrics["jcr_quartile"] = {
            "value": q, "categories": categories,
            "year": data_year, "edition": edition,
            "source_url": source_url, "verified": True, "source": source,
        }
    jif = _number(resolved.get("jif"))
    if jif is not None and jif >= 0:
        metrics["jif"] = {
            "value": jif, "year": data_year, "edition": edition,
            "source_url": source_url, "verified": True, "source": source,
        }
    jif_pct = _number(resolved.get("jif_percentile"))
    if jif_pct is not None and 0 <= jif_pct <= 100:
        metrics["jif_percentile"] = {
            "value": jif_pct, "year": data_year, "edition": edition,
            "category": category, "source_url": source_url, "verified": True, "source": source,
        }
    cas = _partition(resolved.get("cas_large_zone")) or _partition(resolved.get("cas_small_zone"))
    if cas is not None:
        top = _top(resolved.get("cas_top"))
        metric: dict[str, Any] = {
            "value": cas, "broad_category": str(resolved.get("cas_large_zone") or "").strip() or None,
            "narrow_categories": [{"name": category or None, "value": _partition(resolved.get("cas_small_zone"))}]
                                 if _partition(resolved.get("cas_small_zone")) else [],
            "year": data_year, "edition": edition,
            "source_url": source_url, "verified": True, "source": source,
        }
        if top is not None:
            metric["top"] = top
        metrics["cas_partition"] = metric
    ccf = _ccf_rank(resolved.get("ccf_rank"))
    if ccf:
        metrics["ccf_rank"] = {
            "value": ccf, "field": category or None, "directory_version": edition,
            "edition": edition, "source_url": source_url, "verified": True, "source": source,
        }
    wos = [x.upper() for x in _split_csv(resolved.get("wos_indexes")) if x.upper() in {"SCIE", "SSCI", "ESCI", "AHCI"}]
    if wos:
        metrics["wos_indexes"] = {"value": wos, "source": source, "source_url": source_url,
                                  "edition": edition, "year": data_year, "checked_at": resolved.get("checked_at")}
    for key, metric in metrics.items():
        explicit = _bool_cell(resolved.get("verified", defaults.get("verified")))
        versioned = bool(data_year) if key in {"jif", "jif_percentile"} else bool(
            edition or data_year or (key == "wos_indexes" and resolved.get("checked_at")))
        metric["verified"] = bool(explicit and versioned)
        metric["verification_status"] = "user_verified_table" if metric["verified"] else "unverified_table_or_version"
        metric["retrieved_at"] = datetime.now(timezone.utc).isoformat()
        if defaults.get("source_file"):
            metric["source_file"] = defaults["source_file"]
    if not metrics:
        return None
    return metrics


class VenueTable:
    """In-memory index of venue metrics, matched by ISSN-L then ISSN then title."""

    def __init__(self) -> None:
        self.by_issnl: dict[str, list[dict[str, Any]]] = {}
        self.by_issn: dict[str, list[dict[str, Any]]] = {}
        self.by_title: dict[str, list[dict[str, Any]]] = {}
        self.rows: list[dict[str, Any]] = []

    def add_row(self, metrics: dict[str, Any], keys: dict[str, Any]) -> None:
        entry = {"metrics": metrics, **keys}
        self.rows.append(entry)
        issn_l = normalize_issn(keys.get("issn_l"))
        title = normalize_title(keys.get("journal"))
        if issn_l:
            self.by_issnl.setdefault(issn_l, []).append(entry)
        for identifier in issns(keys):
            self.by_issn.setdefault(identifier, []).append(entry)
        if title:
            self.by_title.setdefault(title, []).append(entry)
        for alias in _split_csv(keys.get("aliases")):
            normalized = normalize_title(alias)
            if normalized and normalized != title:
                self.by_title.setdefault(normalized, []).append(entry)

    def match(self, record: dict[str, Any]) -> tuple[str | None, list[dict[str, Any]]]:
        venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
        identifiers = issns(venue)
        entries = []
        method = "issn"
        for identifier in sorted(identifiers):
            if identifier in self.by_issnl:
                method = "issn_l"
            for entry in self.by_issn.get(identifier, []):
                if not any(entry is previous for previous in entries):
                    entries.append(entry)
        if entries:
            # Disconnected journals reached via contradictory candidate ISSNs
            # must not be merged into one journal's metrics.
            components = [issns(entry) for entry in entries]
            joined = set(components[0])
            remaining = components[1:]
            while remaining:
                next_remaining = [ids for ids in remaining if not ids & joined]
                for ids in remaining:
                    if ids & joined:
                        joined.update(ids)
                if len(next_remaining) == len(remaining):
                    return "conflict", entries
                remaining = next_remaining
            return method, entries
        title = normalize_title(venue.get("name"))
        if title and title in self.by_title:
            entries = self.by_title[title]
            comparisons = [compare_venues(venue, {"name": e.get("journal"), **e}) for e in entries]
            if any(c["status"] == "conflict" for c in comparisons):
                return "conflict", entries
            identifiers = [issns(entry) for entry in entries if issns(entry)]
            if any(not left & right for left in identifiers for right in identifiers):
                return "ambiguous", entries
            return "title", entries
        return None, []

    def apply(self, records: Iterable[dict[str, Any]]) -> dict[str, Any]:
        matched = 0
        unmatched = 0
        unresolved = 0
        for record in records:
            if record.get("publication_type") == "preprint":
                record.setdefault("venue_matches", []).append({"provider": "local_table", "status": "not_applicable", "reason": "preprint_repository"})
                continue
            method, entries = self.match(record)
            if not entries:
                record.setdefault("venue_matches", []).append({"provider": "local_table", "status": "unmatched",
                    "method": None, "input_issns": sorted(issns(record.get("venue") or {}))})
                unmatched += 1
                continue
            audit = {"provider": "local_table", "method": method,
                     "status": "matched" if method in {"issn", "issn_l"} else "name_only" if method == "title" else method,
                     "input_issns": sorted(issns(record.get("venue") or {})),
                     "matched_journals": sorted({str(e.get("journal") or "") for e in entries})}
            record.setdefault("venue_matches", []).append(audit)
            if method in {"conflict", "ambiguous"} or record.get("metadata_conflicts"):
                unresolved += 1
                continue
            # Merge all rows (multi-category journals) into the record's metrics.
            record.setdefault("metrics", {})
            record.setdefault("venue", {})
            keys = {key for entry in entries for key in entry["metrics"]}
            for key in keys:
                observations = [copy.deepcopy(e["metrics"][key]) for e in entries if key in e["metrics"]]
                metric = observations[0]
                versions = {(m.get("edition"), m.get("year")) for m in observations}
                values = {json.dumps(m.get("value"), sort_keys=True) for m in observations}
                categories = [c for m in observations for c in m.get("categories", [])]
                category_rows = key == "jcr_quartile" and len(versions) == 1 and all(m.get("categories") for m in observations)
                if category_rows:
                    metric["categories"] = list({json.dumps(c, sort_keys=True): c for c in categories}.values())
                    # The conservative default requires all listed categories to pass.
                    metric["value"] = max(m["value"] for m in observations)
                    metric["category_policy"] = "worst_listed_category"
                    by_category: dict[str, set[str]] = {}
                    for category in categories:
                        by_category.setdefault(category.get("name") or "", set()).add(str(category.get("quartile")))
                    if any(len(values) > 1 for values in by_category.values()):
                        metric["conflict"] = True
                elif len(values) > 1 or len(versions) > 1:
                    metric["conflict"] = True
                metric["observations"] = observations
                metric["match_method"] = method
                metric["identity_verified"] = method in {"issn", "issn_l"}
                metric["verified"] = bool(metric["identity_verified"] and all(m.get("verified") for m in observations) and not metric.get("conflict"))
                if record["metrics"].get(key) is None:
                    record["metrics"][key] = metric
                else:
                    existing = record["metrics"][key]
                    existing.setdefault("observations", []).extend(observations)
                    if existing.get("value") != metric.get("value") or existing.get("edition") != metric.get("edition"):
                        existing["conflict"] = True
                        existing["verified"] = False
                if key == "wos_indexes" and metric["verified"]:
                    record["venue"]["wos_indexes"] = metric["value"]
            matched += 1
        return {"matched": matched, "unmatched": unmatched, "unresolved": unresolved, "total_rows": len(self.rows)}


def load_csv(path: Path, defaults: dict[str, Any]) -> VenueTable:
    table = VenueTable()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return table
        resolved = _resolve_headers(list(reader.fieldnames))
        for raw in reader:
            row = {canonical: raw.get(header, "").strip() for canonical, header in resolved.items() if header}
            metrics = _row_to_metrics(row, defaults)
            if metrics is None:
                continue
            table.add_row(metrics, {
                "journal": row.get("journal", ""), "issn_l": row.get("issn_l"),
                "issn": row.get("issn"), "eissn": row.get("eissn"),
                "wos_indexes": row.get("wos_indexes"), "aliases": row.get("aliases"),
            })
    return table


def load_json(path: Path, defaults: dict[str, Any]) -> VenueTable:
    table = VenueTable()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("journals"), list):
        extra_defaults = {k: v for k, v in payload.items() if k != "journals"}
        defaults = {**defaults, **extra_defaults}
        rows = payload["journals"]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"Venue JSON must be a list or an object with a 'journals' list: {path}")
    for item in rows:
        if not isinstance(item, dict):
            continue
        metrics = _row_to_metrics(item, defaults)
        if metrics is None:
            continue
        table.add_row(metrics, {
            "journal": item.get("journal") or item.get("journal_title"),
            "issn_l": item.get("issn_l"), "issn": item.get("issn"), "eissn": item.get("eissn"),
            "wos_indexes": item.get("wos_indexes"), "aliases": item.get("aliases"),
        })
    return table


def load_venue_tables(files: Iterable[str | Path]) -> VenueTable:
    """Load one or more CSV/JSON venue files into a single combined index."""
    combined = VenueTable()
    for file in files:
        path = Path(file)
        if not path.exists():
            raise FileNotFoundError(f"Venue metrics file not found: {path}")
        defaults: dict[str, Any] = {"source_file": str(path.resolve())}
        if path.suffix.casefold() == ".csv":
            table = load_csv(path, defaults)
        elif path.suffix.casefold() == ".json":
            table = load_json(path, defaults)
        else:
            raise ValueError(f"Unsupported venue metrics file type: {path.suffix}")
        # Merge tables into the combined index.
        for entry in table.rows:
            keys = {k: v for k, v in entry.items() if k != "metrics"}
            combined.add_row(entry["metrics"], keys)
    return combined


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("usage: venue_table.py <file.csv|file.json> [more files...]", file=sys.stderr)
        raise SystemExit(2)
    try:
        table = load_venue_tables(sys.argv[1:])
    except (FileNotFoundError, ValueError) as exc:
        print(f"venue table error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    print(json.dumps({"rows": len(table.rows), "ok": True}, ensure_ascii=False))
