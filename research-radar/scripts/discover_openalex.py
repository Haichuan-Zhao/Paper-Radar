#!/usr/bin/env python3
"""Collect public OpenAlex metadata; never score, download, or write to Zotero.

No third-party packages. Optional user key in OPENALEX_API_KEY for pagination.
Exit 0 means the declared queries exhausted;
exit 2 means partial coverage, including an explicit page cap or interruption.
The normalized candidate records mirror ``discover_papers.py`` so downstream
merge/scoring works unchanged.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import html
import json
import math
import os
import re
import signal
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from itertools import product
from pathlib import Path
from typing import Any
from identifiers import normalize_issn

API = "https://api.openalex.org/works"
DEFAULT_TYPES = ["journal-article", "proceedings-article"]

# Requested (Crossref-style) types -> OpenAlex ``type`` filter values. A request
# without an OpenAlex equivalent is skipped and recorded in the ledger.
TYPE_MAP = {
    "journal-article": "article",
    "proceedings-article": "conference-paper",
    "article": "article",
    "conference-paper": "conference-paper",
    "preprint": "preprint",
    "book": "book",
    "book-chapter": "book-chapter",
    "book-section": "book-section",
    "dataset": "dataset",
    "dissertation": "dissertation",
    "editorial": "editorial",
    "erratum": "erratum",
    "letter": "letter",
    "other": "other",
    "paratext": "paratext",
    "peer-review": "peer-review",
    "reference-entry": "reference-entry",
    "report": "report",
    "review": "review",
    "standard": "standard",
}

# OpenAlex native type -> normalized ``publication_type`` used downstream.
OPENALEX_TYPE_NORMALIZED = {
    "article": "journal-article",
    "conference-paper": "conference-paper",
    "preprint": "preprint",
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(html.unescape(re.sub(r"<[^>]*>", " ", str(value))).split()) or None


def first(value: Any) -> Any:
    return value[0] if isinstance(value, list) and value else None


def doi(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    return text if re.fullmatch(r"10\.\d{4,9}/\S+", text) else None


def date_bounds(value: str) -> tuple[date, date]:
    parts = [int(p) for p in value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    start = date(year, month, day)
    end_month = month if len(parts) > 1 else 12
    end_day = day if len(parts) > 2 else calendar.monthrange(year, end_month)[1]
    return start, date(year, end_month, end_day)


def openalex_date(value: Any) -> str | None:
    """Validate OpenAlex ``publication_date`` (YYYY[-MM[-DD]]) and return it."""
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", text):
        return None
    try:
        date_bounds(text)
    except (ValueError, OverflowError):
        return None
    return text


def date_membership(record: dict, start: date, end: date, policy: str) -> dict:
    fields = (["published_online"] if policy == "online" else
              ["published", "published_online", "published_print", "issued"] if policy == "publication" else
              ["published_online", "published", "published_print", "issued"])
    field = next((f for f in fields if record.get(f)), None)
    if field is None:
        return {"status": "needs_date_verification", "field": None, "value": None}
    value = record[field]
    lower, upper = date_bounds(value)
    status = "outside" if upper < start or lower > end else (
        "within" if lower >= start and upper <= end else "needs_date_verification")
    return {"status": status, "field": field, "value": value,
            "precision": {4: "year", 7: "month", 10: "day"}[len(value)],
            "fallback_used": policy == "online-first" and field != "published_online"}


def identity(record: dict) -> str:
    if record["doi"]:
        return "doi:" + record["doi"]
    author = first(record.get("authors")) or {}
    normalize = lambda x: re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(x or "")).casefold()).strip()
    year = next((str(record[f])[:4] for f in ["published_online", "published", "published_print", "issued"] if record.get(f)), "")
    seed = [normalize(record["title"]), normalize(author.get("family") or author.get("name")), year]
    if not all(seed):
        # Generic titles without author/year evidence must not collapse distinct works.
        seed = {k: v for k, v in record.items() if k != "provenance"}
    return "local:" + hashlib.sha256(json.dumps(seed, ensure_ascii=False).encode()).hexdigest()[:20]


def split_name(display: str) -> tuple[str | None, str | None]:
    """Best-effort (given, family) from an OpenAlex ``display_name``.

    OpenAlex does not split given/family on the work record, so split the last
    whitespace token as the family name. Single-token names keep ``given`` null.
    """
    parts = display.split()
    if len(parts) <= 1:
        return None, display
    return " ".join(parts[:-1]), parts[-1]


def reconstruct_abstract(inverted: Any) -> str | None:
    """Rebuild prose from OpenAlex ``abstract_inverted_index`` word->positions."""
    if not isinstance(inverted, dict):
        return None
    positions: dict[int, str] = {}
    for word, indices in inverted.items():
        if isinstance(indices, list):
            for index in indices:
                if isinstance(index, int):
                    positions[index] = word
    if not positions:
        return None
    return " ".join(positions[i] for i in sorted(positions))


def normalize(item: dict, query_id: str, retrieved_at: str, raw_line: int) -> dict:
    if not isinstance(item, dict) or not clean(item.get("title")):
        raise ValueError("missing_title_or_invalid_record")
    identifier = doi(item.get("doi"))
    openalex_id = item.get("id")
    native_type = item.get("type")
    primary = item.get("primary_location") or {}
    source = primary.get("source") if isinstance(primary, dict) else {}
    source = source if isinstance(source, dict) else {}
    issn = [x for x in (source.get("issn") or []) if isinstance(x, str)]
    issn_l = source.get("issn_l")
    if isinstance(issn_l, str) and issn_l and issn_l not in issn:
        issn.append(issn_l)
    authors = []
    for entry in (item.get("authorships") or []):
        if not isinstance(entry, dict):
            continue
        author = entry.get("author") or {}
        if not isinstance(author, dict):
            continue
        display = clean(author.get("display_name"))
        if not display:
            continue
        given, family = split_name(display)
        authors.append({"given": given, "family": family, "name": display, "orcid": author.get("orcid"),
                        "affiliations": [{"name": i.get("display_name"), "ror": i.get("ror")}
                                         for i in (entry.get("institutions") or []) if isinstance(i, dict)]})
    record = {
        "doi": identifier, "title": clean(item.get("title")),
        "abstract": clean(reconstruct_abstract(item.get("abstract_inverted_index"))),
        "authors": authors,
        "url": "https://doi.org/" + identifier if identifier else openalex_id,
        "publication_type": OPENALEX_TYPE_NORMALIZED.get(native_type, native_type),
        "source_publication_type": native_type, "peer_review_status": "not_peer_reviewed" if native_type == "preprint" else None,
        "published_online": None,
        "published_print": None, "published": openalex_date(item.get("publication_date")), "issued": None, "accepted": None,
        "open_access": (item.get("open_access") or {}).get("is_oa"),
        "full_text_urls": [{"url": loc[field], "format": "pdf" if field == "pdf_url" else "landing",
                            "source": "OpenAlex", "reported_open_access": True,
                            "version": loc.get("version"), "license": loc.get("license"),
                            "source_id": (loc.get("source") or {}).get("id"), "retrieved_at": retrieved_at}
                           for loc in (item.get("locations") or []) if isinstance(loc, dict) and loc.get("is_oa") is True
                           for field in ("pdf_url", "landing_page_url") if loc.get(field)],
        "venue": {"name": clean(source.get("display_name")), "short_name": None,
                  "kind": "conference" if native_type == "conference-paper" else "journal" if native_type == "article" else None,
                  "publisher": clean(source.get("host_organization_name")), "issn": issn,
                  "issn_l": issn_l, "source_id": source.get("id"),
                  "wos_indexes": None, "volume": None, "issue": None, "pages": None,
                  "conference_track": None},
        "metrics": {}, "evaluation": {}, "artifacts": {}, "pdf_path": None,
        "provenance": [{"source": "OpenAlex", "url": openalex_id,
                        "retrieved_at": retrieved_at, "query_id": query_id,
                        "raw_file": "raw-openalex.jsonl", "raw_line": raw_line,
                        "fields": ["title", "abstract", "authors", "doi", "publication_type", "venue", "dates"]}],
    }
    record["id"] = identity(record)
    return record


class FetchError(Exception):
    """Intentionally contains only a safe status, never a request URL or body."""


def retry_seconds(value: str | None) -> float:
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


def fetch_json(params: dict, timeout: float, retries: int, events: list) -> dict:
    # Contact is kept in the User-Agent, never persisted in query URLs or reports.
    contact = os.environ.get("OPENALEX_CONTACT_EMAIL", "").strip()
    headers = {"Accept": "application/json", "User-Agent": "ResearchRadar/1.0" + (f" (mailto:{contact})" if contact else "")}
    api_key = os.environ.get("OPENALEX_API_KEY", "").strip()
    if params.get("cursor") not in {None, "*"} and not api_key:
        raise FetchError("openalex_api_key_required_for_cursor_paging")
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers=headers)
    for attempt in range(retries + 1):
        wait = 2 ** attempt
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            if not isinstance(data, dict):
                raise FetchError("invalid_response_object")
            return data
        except urllib.error.HTTPError as exc:
            reason = f"http_{exc.code}"
            events.append({"at": now(), "reason": reason, "attempt": attempt + 1})
            if exc.code not in {429, 500, 502, 503, 504}:
                raise FetchError(reason) from None
            wait = max(wait, retry_seconds(exc.headers.get("Retry-After")))
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeError) as exc:
            reason = type(exc).__name__
            events.append({"at": now(), "reason": reason, "attempt": attempt + 1})
        if attempt == retries or wait > 60:
            raise FetchError(reason + ("_retry_after_exceeds_60s" if wait > 60 else "_retries_exhausted"))
        time.sleep(wait)
    raise FetchError("retries_exhausted")


def write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def resolve_type(requested: str) -> str | None:
    return TYPE_MAP.get(requested)


def collect(args: argparse.Namespace, fetcher=fetch_json, sleeper=time.sleep) -> dict:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in ("candidates.jsonl", "search-coverage.json", "raw-openalex.jsonl")]
    if any(p.exists() for p in paths):
        raise ValueError("Output artifacts already exist; choose a new run directory to preserve earlier evidence")
    searches = []
    # OpenAlex exposes one publication_date, so each query/type is a single
    # search; the date filter always uses from/to_publication_date regardless of
    # --date-field, which only drives the post-hoc date_membership verification.
    for query, kind, identifier in product(dict.fromkeys(args.query), args.types, getattr(args, "issn", None) or [None]):
        filters = f"from_publication_date:{args.date_from},to_publication_date:{args.date_to},type:{kind}"
        if identifier:
            filters += f",primary_location.source.issn:{identifier}"
        searches.append({"id": f"openalex-{len(searches) + 1}", "source": "OpenAlex", "query": query,
                         "query_parameter": "search", "filters": filters, "pages_fetched": 0,
                         "records_returned": 0, "records_retained": 0, "outside_interval": 0,
                         "duplicates": 0, "malformed_records": 0, "reported_totals": [],
                         "cursor_exhausted": False, "status": "not_started", "events": []})
    notes = ["OpenAlex keyword search is not Boolean syntax or a relevance verdict.",
             "Metrics, artifact availability, review subtype and scientific quality require enrichment.",
             "OpenAlex publication_date is not proof of first online date; preserved as published."]
    if getattr(args, "skipped_types", None):
        notes.append("Skipped requested types without an OpenAlex equivalent: " + ", ".join(args.skipped_types))
    ledger = {"schema_version": 1, "started_at": now(), "date_from": args.date_from,
              "date_to": args.date_to, "date_field": args.date_field, "status": "partial",
              "source_scope": ["OpenAlex"], "page_size": args.rows, "max_pages_per_query": args.max_pages,
              "coverage_statement": "Only declared OpenAlex queries; source exhaustion is not global literature completeness.",
              "requested_types": getattr(args, "requested_types", args.types),
              "type_map": {t: resolve_type(t) for t in getattr(args, "requested_types", args.types)},
              "skipped_types": getattr(args, "skipped_types", []),
              "queries": searches, "notes": notes}
    records: dict[str, dict] = {}
    raw_line = 0
    start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)

    def checkpoint() -> None:
        temporary = paths[0].with_suffix(".jsonl.tmp")
        with temporary.open("w", encoding="utf-8") as target:
            for record in records.values():
                target.write(json.dumps(record, ensure_ascii=False) + "\n")
        temporary.replace(paths[0])
        ledger["updated_at"] = now()
        ledger["unique_candidates"] = len(records)
        ledger["raw_records"] = raw_line
        ledger["date_verification_candidates"] = sum(r["discovery"]["date_membership"]["status"] == "needs_date_verification" for r in records.values())
        write_json(paths[1], ledger)

    checkpoint()
    try:
        with paths[2].open("w", encoding="utf-8") as raw:
            for search in searches:
                search["status"] = "running"
                cursor = "*"
                seen_pages = set()
                try:
                    while True:
                        params = {"search": search["query"], "filter": search["filters"], "per-page": args.rows, "cursor": cursor}
                        payload = fetcher(params, args.timeout, args.retries, search["events"])
                        meta = payload.get("meta")
                        results = payload.get("results")
                        if not isinstance(meta, dict) or not isinstance(results, list):
                            raise FetchError("invalid_response_shape")
                        signature = hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()
                        if results and signature in seen_pages:
                            raise FetchError("repeated_page_without_progress")
                        seen_pages.add(signature)
                        search["pages_fetched"] += 1
                        search["records_returned"] += len(results)
                        total = meta.get("count")
                        if total not in search["reported_totals"]:
                            search["reported_totals"].append(total)
                        stamp = now()
                        for item in results:
                            raw_line += 1
                            raw.write(json.dumps({"query_id": search["id"], "retrieved_at": stamp, "record": item}, ensure_ascii=False) + "\n")
                            try:
                                record = normalize(item, search["id"], stamp, raw_line)
                            except (ValueError, TypeError, AttributeError):
                                search["malformed_records"] += 1
                                continue
                            membership = date_membership(record, start, end, args.date_field)
                            if args.date_field == "online":
                                membership["status"] = "needs_date_verification"
                            record["discovery"] = {"date_membership": membership, "status": "awaiting_enrichment"}
                            if membership["status"] == "outside":
                                search["outside_interval"] += 1
                                continue
                            search["records_retained"] += 1
                            if record["id"] in records:
                                search["duplicates"] += 1
                                previous = records[record["id"]]
                                previous["provenance"].extend(record["provenance"])
                                if not previous["abstract"] and record["abstract"]:
                                    previous["abstract"] = record["abstract"]
                            else:
                                records[record["id"]] = record
                        raw.flush()
                        next_cursor = meta.get("next_cursor")
                        if not next_cursor:
                            search["cursor_exhausted"] = True
                            search["status"] = "partial" if search["malformed_records"] else "complete"
                            if search["malformed_records"]:
                                search["reason"] = "malformed_records_preserved_in_raw"
                            break
                        if args.max_pages and search["pages_fetched"] >= args.max_pages:
                            search.update(status="partial", reason="explicit_max_pages")
                            break
                        cursor = next_cursor
                        checkpoint()
                        sleeper(args.pause)
                except FetchError as exc:
                    search.update(status="partial", reason=str(exc))
                checkpoint()
                sleeper(args.pause)
    except KeyboardInterrupt:
        ledger["interrupted"] = True
        for search in searches:
            if search["status"] == "running":
                search.update(status="partial", reason="interrupted")
    finally:
        ledger["status"] = "complete_query_coverage" if all(s["status"] == "complete" for s in searches) else "partial"
        ledger["finished_at"] = now()
        checkpoint()
    return ledger


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--query", action="append", required=True, help="Repeat for synonyms; plain keyword query, not Boolean")
    result.add_argument("--date-from", required=True, help="Inclusive YYYY-MM-DD")
    result.add_argument("--date-to", required=True, help="Inclusive YYYY-MM-DD")
    result.add_argument("--date-field", choices=["online-first", "online", "publication"], default="online-first")
    result.add_argument("--type", dest="types", action="append", help="Crossref-style type; defaults to journal-article and proceedings-article")
    result.add_argument("--issn", action="append", help="Exact primary journal ISSN scope (repeatable)")
    result.add_argument("--output-dir", required=True, help="New run directory (existing artifacts are never overwritten)")
    result.add_argument("--rows", type=int, default=100, help="Page size, 1–100")
    result.add_argument("--max-pages", type=int, help="Explicit per-query cap for smoke tests; incomplete retrieval is marked partial")
    result.add_argument("--timeout", type=float, default=30)
    result.add_argument("--retries", type=int, default=2)
    result.add_argument("--pause", type=float, default=1.0, help="Seconds between requests")
    return result


def main() -> int:
    cli = parser()
    args = cli.parse_args()
    try:
        start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
        if start.isoformat() != args.date_from or end.isoformat() != args.date_to or start > end:
            raise ValueError("Dates must be YYYY-MM-DD with date-from <= date-to")
        if not 1 <= args.rows <= 100 or args.max_pages is not None and args.max_pages < 1:
            raise ValueError("rows must be 1–100; max-pages must be positive")
        if args.issn:
            if any(normalize_issn(x) is None for x in args.issn):
                raise ValueError("Invalid ISSN or ISSN check digit")
            args.issn = list(dict.fromkeys(normalize_issn(x) for x in args.issn))
        if not math.isfinite(args.timeout) or not math.isfinite(args.pause) or args.timeout <= 0 or args.retries < 0 or args.pause < 0 or not all(q.strip() for q in args.query):
            raise ValueError("Invalid timeout, retries, pause, or empty query")
        args.requested_types = list(dict.fromkeys(args.types or DEFAULT_TYPES))
        if not all(re.fullmatch(r"[a-z]+(?:-[a-z]+)*", kind) for kind in args.requested_types):
            raise ValueError("types must be simple hyphenated names")
        resolved, skipped = [], []
        for kind in args.requested_types:
            mapped = resolve_type(kind)
            if mapped is None:
                skipped.append(kind)
            elif mapped not in resolved:
                resolved.append(mapped)
        args.types = resolved
        args.skipped_types = skipped
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        ledger = collect(args)
    except (ValueError, OSError) as exc:
        # Local file errors may contain a path; never print request objects or environment values.
        cli.exit(1, f"Discovery error: {exc}\n")
    print(json.dumps({"status": ledger["status"], "unique_candidates": ledger["unique_candidates"],
                      "queries": len(ledger["queries"])}, ensure_ascii=False))
    return 0 if ledger["status"] == "complete_query_coverage" else 2


if __name__ == "__main__":
    sys.exit(main())
