#!/usr/bin/env python3
"""Collect public Crossref metadata; never score, download, or write to Zotero.

No third-party packages or API keys. Exit 0 means the declared queries exhausted;
exit 2 means partial coverage, including an explicit page cap or interruption.
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

API = "https://api.crossref.org/works"
DEFAULT_TYPES = ["journal-article", "proceedings-article"]


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


def date_value(value: Any) -> str | None:
    try:
        parts = value["date-parts"][0]
        if not 1 <= len(parts) <= 3 or any(type(p) is not int for p in parts):
            return None
        text = "-".join(str(p).zfill(4 if i == 0 else 2) for i, p in enumerate(parts))
        date_bounds(text)
        return text
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def date_bounds(value: str) -> tuple[date, date]:
    parts = [int(p) for p in value.split("-")]
    year = parts[0]
    month = parts[1] if len(parts) > 1 else 1
    day = parts[2] if len(parts) > 2 else 1
    start = date(year, month, day)
    end_month = month if len(parts) > 1 else 12
    end_day = day if len(parts) > 2 else calendar.monthrange(year, end_month)[1]
    return start, date(year, end_month, end_day)


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


def normalize(item: dict, query_id: str, retrieved_at: str, raw_line: int) -> dict:
    if not isinstance(item, dict) or not clean(first(item.get("title"))):
        raise ValueError("missing_title_or_invalid_record")
    identifier = doi(item.get("DOI"))
    source_url = API + "/" + urllib.parse.quote(identifier, safe="/") if identifier else API
    native_type = item.get("type")
    authors = [{"given": clean(a.get("given")), "family": clean(a.get("family")),
                "name": clean(a.get("name")), "orcid": a.get("ORCID"),
                "affiliations": [clean(i.get("name")) for i in (a.get("affiliation") or []) if isinstance(i, dict)]}
               for a in (item.get("author") or []) if isinstance(a, dict)]
    record = {
        "doi": identifier, "title": clean(first(item.get("title"))),
        "abstract": clean(item.get("abstract")), "authors": authors,
        "url": "https://doi.org/" + identifier if identifier else item.get("URL"),
        "full_text_urls": [{"url": link["URL"], "source": "Crossref", "reported_open_access": False,
                            "format": "pdf" if link.get("content-type") == "application/pdf" else "landing",
                            "version": {"vor": "publishedVersion", "am": "acceptedVersion"}.get(link.get("content-version"), "unknown"),
                            "intended_application": link.get("intended-application"), "retrieved_at": retrieved_at}
                           for link in (item.get("link") or []) if isinstance(link, dict) and link.get("URL")],
        "publication_type": "conference-paper" if native_type == "proceedings-article" else "preprint" if native_type == "posted-content" and item.get("subtype") == "preprint" else native_type,
        "source_publication_type": native_type, "peer_review_status": "not_peer_reviewed" if native_type == "posted-content" and item.get("subtype") == "preprint" else None,
        "published_online": date_value(item.get("published-online")),
        "published_print": date_value(item.get("published-print")),
        "published": date_value(item.get("published")), "issued": date_value(item.get("issued")),
        "accepted": date_value(item.get("accepted")),
        "venue": {"name": clean(first(item.get("container-title"))),
                  "short_name": clean(first(item.get("short-container-title"))),
                  "kind": "conference" if native_type == "proceedings-article" else "journal" if native_type == "journal-article" else None,
                  "publisher": clean(item.get("publisher")), "issn": item.get("ISSN", []),
                  "wos_indexes": None, "volume": item.get("volume"), "issue": item.get("issue"),
                  "pages": item.get("page"), "conference_track": None},
        "metrics": {}, "evaluation": {}, "artifacts": {}, "pdf_path": None,
        "provenance": [{"source": "Crossref", "url": source_url,
                        "retrieved_at": retrieved_at, "query_id": query_id,
                        "raw_file": "raw-crossref.jsonl", "raw_line": raw_line,
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
    contact = os.environ.get("CROSSREF_CONTACT_EMAIL", "").strip()
    headers = {"Accept": "application/json", "User-Agent": "ResearchRadar/1.0" + (f" (mailto:{contact})" if contact else "")}
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


def collect(args: argparse.Namespace, fetcher=fetch_json, sleeper=time.sleep) -> dict:
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    paths = [output / name for name in ("candidates.jsonl", "search-coverage.json", "raw-crossref.jsonl")]
    if any(p.exists() for p in paths):
        raise ValueError("Output artifacts already exist; choose a new run directory to preserve earlier evidence")
    searches = []
    # The online pass captures online dates even when another deposited date is earlier.
    modes = ["online-pub-date", "pub-date"] if args.date_field == "online-first" else ["online-pub-date" if args.date_field == "online" else "pub-date"]
    for query, kind, mode, identifier in product(dict.fromkeys(args.query), args.types, modes, getattr(args, "issn", None) or [None]):
        filters = f"from-{mode}:{args.date_from},until-{mode}:{args.date_to},type:{kind}"
        if identifier:
            filters += f",issn:{identifier}"
        searches.append({"id": f"crossref-{len(searches) + 1}", "source": "Crossref", "query": query,
                         "query_parameter": "query", "sort": "score", "order": "desc",
                         "filters": filters, "pages_fetched": 0,
                         "records_returned": 0, "records_retained": 0, "outside_interval": 0,
                         "duplicates": 0, "malformed_records": 0, "reported_totals": [],
                         "cursor_exhausted": False, "status": "not_started", "events": []})
    ledger = {"schema_version": 1, "started_at": now(), "date_from": args.date_from,
              "date_to": args.date_to, "date_field": args.date_field, "status": "partial",
              "source_scope": ["Crossref"], "page_size": args.rows, "max_pages_per_query": args.max_pages,
              "coverage_statement": "Only declared Crossref queries; source exhaustion is not global literature completeness.",
              "queries": searches, "notes": ["Crossref keyword search is not Boolean syntax or a relevance verdict.",
                                             "Metrics, artifact availability, review subtype and scientific quality require enrichment."]}
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
                        # Cursor searches do not reliably default to relevance order.
                        # Keep an explicit order on every page, especially for bounded runs.
                        params = {"query": search["query"], "filter": search["filters"],
                                  "sort": search["sort"], "order": search["order"],
                                  "rows": args.rows, "cursor": cursor}
                        payload = fetcher(params, args.timeout, args.retries, search["events"])
                        message = payload.get("message")
                        if not isinstance(message, dict) or not isinstance(message.get("items"), list):
                            raise FetchError("invalid_response_shape")
                        items = message["items"]
                        signature = hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()
                        if items and signature in seen_pages:
                            raise FetchError("repeated_page_without_progress")
                        seen_pages.add(signature)
                        search["pages_fetched"] += 1
                        search["records_returned"] += len(items)
                        total = message.get("total-results")
                        if total not in search["reported_totals"]:
                            search["reported_totals"].append(total)
                        stamp = now()
                        for item in items:
                            raw_line += 1
                            raw.write(json.dumps({"query_id": search["id"], "retrieved_at": stamp, "record": item}, ensure_ascii=False) + "\n")
                            try:
                                record = normalize(item, search["id"], stamp, raw_line)
                            except (ValueError, TypeError, AttributeError):
                                search["malformed_records"] += 1
                                continue
                            membership = date_membership(record, start, end, args.date_field)
                            record["discovery"] = {"date_membership": membership, "status": "awaiting_enrichment"}
                            if membership["status"] == "outside":
                                search["outside_interval"] += 1
                                continue
                            search["records_retained"] += 1
                            if record["id"] in records:
                                search["duplicates"] += 1
                                previous = records[record["id"]]
                                previous["provenance"].extend(record["provenance"])
                                # Preserve every source record; fill only a missing abstract.
                                if not previous["abstract"] and record["abstract"]:
                                    previous["abstract"] = record["abstract"]
                            else:
                                records[record["id"]] = record
                        raw.flush()
                        next_cursor = message.get("next-cursor")
                        # Crossref can reuse the cursor string; page content detects loops.
                        if len(items) < args.rows:
                            search["cursor_exhausted"] = True
                            search["status"] = "partial" if search["malformed_records"] else "complete"
                            if search["malformed_records"]:
                                search["reason"] = "malformed_records_preserved_in_raw"
                            break
                        if not next_cursor:
                            search.update(status="partial", reason="missing_cursor_on_full_page")
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
    result.add_argument("--type", dest="types", action="append", help="Crossref type; defaults to journal-article and proceedings-article")
    result.add_argument("--issn", action="append", help="Exact journal ISSN scope (repeatable, OR across journals)")
    result.add_argument("--output-dir", required=True, help="New run directory (existing artifacts are never overwritten)")
    result.add_argument("--rows", type=int, default=100, help="Page size, 1–1000; not a result limit")
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
        if not 1 <= args.rows <= 1000 or args.max_pages is not None and args.max_pages < 1:
            raise ValueError("rows must be 1–1000; max-pages must be positive")
        if not math.isfinite(args.timeout) or not math.isfinite(args.pause) or args.timeout <= 0 or args.retries < 0 or args.pause < 0 or not all(q.strip() for q in args.query):
            raise ValueError("Invalid timeout, retries, pause, or empty query")
        args.types = list(dict.fromkeys(args.types or DEFAULT_TYPES))
        if args.issn:
            if any(normalize_issn(x) is None for x in args.issn):
                raise ValueError("Invalid ISSN or ISSN check digit")
            args.issn = list(dict.fromkeys(normalize_issn(x) for x in args.issn))
        if not all(re.fullmatch(r"[a-z]+(?:-[a-z]+)*", kind) for kind in args.types):
            raise ValueError("Crossref types must be simple hyphenated names")
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
