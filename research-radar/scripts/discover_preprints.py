#!/usr/bin/env python3
"""Auditable public metadata adapters for arXiv, bioRxiv and medRxiv.

arXiv supports fielded queries; plain queries become AND over title/abstract
tokens. Rxiv date/category feeds are screened locally using the same plain
query rule, with all fetched metadata retained. Exhaustion is query coverage,
not semantic completeness. No credentials or third-party packages required.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

from discover_papers import clean, doi, now
from relevance import contains, _text

ARXIV = "https://export.arxiv.org/api/query"
RXIV = "https://api.biorxiv.org/details"
NS = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom",
      "o": "http://a9.com/-/spec/opensearch/1.1/"}


def query_tokens(query):
    return re.findall(r'"[^"\n]+"|[\w-]+', query, re.UNICODE)


def arxiv_query(query, start, end):
    # Fielded expressions are deliberately supplied by the agent/user. Plain
    # Crossref phrases do not become one exact phrase in arXiv.
    if re.search(r"\b(?:ti|au|abs|cat|all|id):", query):
        expression = query
    else:
        tokens = query_tokens(query)
        expression = " AND ".join(f'(ti:{t} OR abs:{t})' for t in tokens)
    return f"({expression}) AND submittedDate:[{start.replace('-', '')}0000 TO {end.replace('-', '')}2359]"


def locally_matches(item, query):
    text = _text((clean(item.get("title")) or "") + " " + (clean(item.get("abstract")) or ""))
    tokens = [t.strip('"') for t in query_tokens(query)]
    return bool(tokens) and all(contains(text, token) for token in tokens)


def parse_atom(payload):
    root = ET.fromstring(payload)
    error = root.find("a:entry/a:id", NS)
    if error is not None and "/api/errors" in (error.text or ""):
        raise ValueError("arxiv_api_error")
    if root.tag != "{" + NS["a"] + "}feed":
        raise ValueError("invalid_atom_feed")
    total = root.findtext("o:totalResults", None, NS)
    if total is None or not total.isdigit():
        raise ValueError("missing_or_invalid_arxiv_total")
    return root, int(total)


def normalize_arxiv(entry, request_url, retrieved_at):
    text = lambda name: clean(entry.findtext(name, None, NS))
    native = re.sub(r"^https?://(?:export\.)?arxiv\.org/abs/", "", text("a:id") or "")
    match = re.fullmatch(r"((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))(?:v(\d+))?", native)
    if not match or not text("a:title"):
        raise ValueError("invalid_arxiv_identity")
    base, version = match.group(1), int(match.group(2) or 1)
    landing = f"https://arxiv.org/abs/{base}v{version}"
    published, updated = (text("a:published") or "")[:10], (text("a:updated") or "")[:10]
    date.fromisoformat(published)
    date.fromisoformat(updated)
    related = doi(text("x:doi"))
    return {
        "id": f"arxiv:{base}v{version}", "doi": None, "title": text("a:title"),
        "abstract": text("a:summary"), "authors": [{"name": clean(a.findtext("a:name", None, NS)),
            "affiliations": [clean(e.text) for e in a.findall("x:affiliation", NS)]}
            for a in entry.findall("a:author", NS)],
        "url": landing, "full_text_urls": [{"url": f"https://arxiv.org/pdf/{base}v{version}", "format": "pdf"},
            {"url": f"https://arxiv.org/html/{base}v{version}", "format": "html", "availability": "unverified"}],
        "publication_type": "preprint", "peer_review_status": "not_peer_reviewed", "open_access": True,
        "published_online": published, "published": published, "updated": updated,
        "version": version, "preprint": {"server": "arxiv", "native_id": base, "version": version,
            "journal_reference": text("x:journal_ref"), "categories": [e.get("term") for e in entry.findall("a:category", NS)]},
        "venue": {"name": "arXiv", "type": "repository", "issn": []}, "metrics": {},
        "relations": [{"type": "published_version", "doi": related, "source_url": landing}] if related else [],
        "provenance": [{"source": "arxiv", "source_url": request_url, "retrieved_at": retrieved_at}],
        "discovery": {"date_membership": {"status": "within", "field": "published_online", "value": published,
            "precision": "day", "basis": "preprint_first_submission", "fallback_used": False}},
    }


def normalize_rxiv(item, server, request_url, retrieved_at):
    identifier = doi(item.get("doi"))
    version = str(item.get("version") or "")
    posted = str(item.get("date") or "")
    if not identifier or not version.isdigit() or int(version) < 1 or not clean(item.get("title")):
        raise ValueError("invalid_rxiv_identity")
    date.fromisoformat(posted)
    landing = f"https://www.{server}.org/content/{identifier}v{version}"
    related = doi(item.get("published"))
    return {
        "id": f"{server}:{identifier}v{version}", "doi": identifier, "title": clean(item["title"]),
        "abstract": clean(item.get("abstract")),
        "authors": [{"name": name.strip()} for name in str(item.get("authors") or "").split(";") if name.strip()],
        "corresponding_author": {"name": item.get("author_corresponding"), "institution": item.get("author_corresponding_institution")},
        "url": landing, "full_text_urls": [{"url": landing + ".full", "format": "html"},
            {"url": landing + ".full.pdf", "format": "pdf"}],
        "publication_type": "preprint", "peer_review_status": "not_peer_reviewed", "open_access": True,
        "published_online": posted, "published": posted, "version": int(version),
        "preprint": {"server": server, "native_id": identifier, "version": int(version),
            "date_basis": "version_posted", "category": item.get("category"), "license": item.get("license"),
            "jats_url": item.get("jatsxml")},
        "venue": {"name": "bioRxiv" if server == "biorxiv" else "medRxiv", "type": "repository", "issn": []}, "metrics": {},
        "relations": [{"type": "published_version", "doi": related, "source_url": request_url}] if related else [],
        "provenance": [{"source": server, "source_url": request_url, "retrieved_at": retrieved_at}],
        "discovery": {"date_membership": {"status": "within", "field": "published_online", "value": posted,
            "precision": "day", "basis": "preprint_version_posted", "fallback_used": False}},
    }


def fetch(url, timeout, retries, pause):
    for attempt in range(retries + 1):
        request = urllib.request.Request(url, headers={"User-Agent": "ResearchRadar/3 public literature metadata", "Accept": "application/atom+xml, application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if exc.code not in {429, 500, 502, 503, 504} or attempt == retries:
                raise ValueError(f"http_status_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == retries:
                raise ValueError("network_failure") from None
        time.sleep(min(30, max(pause, 2 ** attempt)))
    raise ValueError("network_failure")


def collect(args, fetcher=fetch, sleeper=time.sleep):
    output = Path(args.output_dir)
    if any((output / name).exists() for name in ("coverage.json", "raw.jsonl", "candidates.jsonl")):
        raise ValueError("Output directory already contains evidence")
    output.mkdir(parents=True, exist_ok=True)
    records, raw, searches = {}, [], []
    ledger = {"source": args.server, "started_at": now(), "queries": searches,
              "query_rule": "arxiv_fielded_or_title_abstract_AND" if args.server == "arxiv" else "local_title_abstract_AND_per_query_OR_queries",
              "date_basis": "first_submission" if args.server == "arxiv" else "version_posted",
              "coverage_scope": "Declared lexical queries only; unseen synonyms may be missed", "invalid_records": 0}
    def checkpoint():
        ledger["unique_candidates"] = len(records)
        (output / "raw.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in raw), encoding="utf-8")
        (output / "candidates.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records.values()), encoding="utf-8")
        (output / "coverage.json").write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Rxiv queries share a date feed: fetch once per category, not once per phrase.
    units = args.query if args.server == "arxiv" else (args.category or [None])
    try:
        for unit_number, unit in enumerate(units):
            search = {"query": unit if args.server == "arxiv" else args.query, "category": unit if args.server != "arxiv" else None,
                      "pages": 0, "fetched_records": 0, "matched_records": 0, "status": "running"}
            searches.append(search)
            cursor, seen_pages = 0, set()
            while True:
                if args.server == "arxiv":
                    url = ARXIV + "?" + urllib.parse.urlencode({"search_query": arxiv_query(unit, args.date_from, args.date_to),
                        "start": cursor, "max_results": args.rows, "sortBy": "submittedDate", "sortOrder": "descending"})
                else:
                    url = f"{RXIV}/{args.server}/{args.date_from}/{args.date_to}/{cursor}/json"
                    if unit:
                        url += "?" + urllib.parse.urlencode({"category": unit})
                try:
                    body = fetcher(url, args.timeout, args.retries, args.pause)
                    retrieved = now()
                    if args.server == "arxiv":
                        root, total = parse_atom(body)
                        items = root.findall("a:entry", NS)
                        raw.append({"source_url": url, "retrieved_at": retrieved, "atom": body.decode("utf-8")})
                    else:
                        payload = json.loads(body)
                        messages = payload.get("messages") or []
                        if not messages or messages[0].get("status") not in {"ok", "no posts found"}:
                            raise ValueError("rxiv_api_error")
                        items = payload.get("collection") or []
                        if "total" not in messages[0] and items:
                            raise ValueError("missing_rxiv_pagination_total")
                        total = int(messages[0].get("total", 0))
                        if total < 0:
                            raise ValueError("invalid_rxiv_pagination_total")
                        raw.append({"source_url": url, "retrieved_at": retrieved, "payload": payload})
                    signature = tuple((ET.tostring(i, encoding="unicode") if args.server == "arxiv" else str(i.get("doi")) + "v" + str(i.get("version"))) for i in items)
                    if items and signature in seen_pages:
                        raise ValueError("pagination_repeated_page")
                    seen_pages.add(signature)
                    search["pages"] += 1
                    search["fetched_records"] += len(items)
                    search["reported_total"] = total
                    for item in items:
                        if args.server != "arxiv" and not any(locally_matches(item, q) for q in args.query):
                            continue
                        try:
                            record = (normalize_arxiv(item, url, retrieved) if args.server == "arxiv" else
                                      normalize_rxiv(item, args.server, url, retrieved))
                            posted = record["published_online"]
                            if not args.date_from <= posted <= args.date_to:
                                ledger["invalid_records"] += 1
                                continue
                            search["matched_records"] += 1
                            if record["id"] in records:
                                records[record["id"]]["provenance"].extend(record["provenance"])
                            else:
                                records[record["id"]] = record
                        except ValueError:
                            ledger["invalid_records"] += 1
                    cursor += len(items)
                    if not items and cursor < total:
                        search.update(status="partial", reason="empty_page_before_reported_total")
                    elif cursor >= total:
                        search["status"] = "complete"
                    elif args.max_pages and search["pages"] >= args.max_pages:
                        search.update(status="partial", reason="max_pages")
                    checkpoint()
                    if search["status"] != "running":
                        break
                    sleeper(args.pause)
                except (ValueError, KeyError, TypeError, ET.ParseError) as exc:
                    search.update(status="partial", reason=str(exc)[:120])
                    checkpoint()
                    break
            if unit_number < len(units) - 1:
                sleeper(args.pause)
    except KeyboardInterrupt:
        ledger["interrupted"] = True
        for search in searches:
            if search["status"] == "running":
                search.update(status="partial", reason="interrupted")
    ledger["status"] = "complete_query_coverage" if all(s["status"] == "complete" for s in searches) and not ledger["invalid_records"] else "partial"
    ledger["finished_at"] = now()
    checkpoint()
    return ledger


def parser():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--server", choices=["arxiv", "biorxiv", "medrxiv"], required=True)
    cli.add_argument("--query", action="append", required=True)
    cli.add_argument("--date-from", required=True)
    cli.add_argument("--date-to", required=True)
    cli.add_argument("--date-field", choices=["online-first", "online", "publication"], default="online-first")
    cli.add_argument("--category", action="append", help="Rxiv subject category; repeatable")
    cli.add_argument("--type", dest="types", action="append")
    cli.add_argument("--output-dir", required=True)
    cli.add_argument("--rows", type=int, default=100)
    cli.add_argument("--max-pages", type=int)
    cli.add_argument("--timeout", type=float, default=30)
    cli.add_argument("--retries", type=int, default=2)
    cli.add_argument("--pause", type=float, default=3)
    return cli


def main():
    cli = parser()
    args = cli.parse_args()
    try:
        start, end = date.fromisoformat(args.date_from), date.fromisoformat(args.date_to)
        if start > end or start.isoformat() != args.date_from or end.isoformat() != args.date_to:
            raise ValueError("Invalid inclusive date interval")
        if not 1 <= args.rows <= 2000 or args.max_pages is not None and args.max_pages < 1:
            raise ValueError("Invalid page size or cap")
        if not all(q.strip() for q in args.query) or not all(math.isfinite(v) for v in [args.pause, args.timeout]) or args.timeout <= 0 or args.pause < 3 or args.retries < 0:
            raise ValueError("Nonempty queries, positive timeout and at least 3 seconds between requests required")
        if args.server != "arxiv" and any(re.search(r"\b(?:AND|OR|NOT)\b|\b\w+:", q) for q in args.query):
            raise ValueError("Rxiv local queries are plain phrases; use separate queries for alternatives")
        ledger = collect(args)
    except (ValueError, OSError) as exc:
        cli.exit(1, f"Preprint discovery error: {exc}\n")
    print(json.dumps({"source": args.server, "status": ledger["status"], "unique_candidates": ledger["unique_candidates"]}))
    return 0 if ledger["status"] == "complete_query_coverage" else 2


if __name__ == "__main__":
    sys.exit(main())
