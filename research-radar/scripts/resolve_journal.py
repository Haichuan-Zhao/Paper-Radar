#!/usr/bin/env python3
"""Resolve journal names to public Crossref serial identities before scoping search."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from identifiers import normalize_issn, normalize_title

API = "https://api.crossref.org/journals"


def fetch(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ResearchRadar/1.1"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Crossref journal lookup http_{exc.code}") from None
    except (OSError, ValueError):
        raise ValueError("Crossref journal lookup failed") from None
    if not isinstance(data, dict):
        raise ValueError("Invalid Crossref journal response")
    return data


def resolve(name: str | None = None, identifier: str | None = None, fetcher=fetch) -> dict[str, Any]:
    normalized = normalize_issn(identifier) if identifier else None
    if identifier and not normalized:
        raise ValueError("Invalid ISSN or check digit")
    url = API + "/" + normalized if normalized else API + "?" + urllib.parse.urlencode({"query": name, "rows": 20})
    payload = fetcher(url)
    message = payload.get("message")
    if normalized:
        items = [message] if isinstance(message, dict) else []
    else:
        items = message.get("items", []) if isinstance(message, dict) else []
    candidates = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        values = item.get("ISSN") or []
        if isinstance(values, str):
            values = [values]
        ids = sorted({normalize_issn(x) for x in values if normalize_issn(x)})
        if not title or not ids:
            continue
        candidates.append({"name": title, "issn": ids, "publisher": item.get("publisher"),
                           "source": "Crossref", "source_url": API + "/" + ids[0]})
    exact = [c for c in candidates if normalized in c["issn"]] if normalized else [
        c for c in candidates if normalize_title(c["name"]) == normalize_title(name)]
    exact = list({(c["name"], tuple(c["issn"])): c for c in exact}.values())
    status = "resolved" if len(exact) == 1 else "ambiguous" if len(exact) > 1 else "needs_verification"
    if normalized and name and exact and normalize_title(exact[0]["name"]) != normalize_title(name):
        status = "name_identifier_conflict"
    return {"status": status, "query": {"name": name, "issn": normalized},
            "resolved": exact[0] if status == "resolved" else None, "candidates": candidates,
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "coverage": "Public Crossref serial registry; not a universal journal directory"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="Full journal name; fuzzy search hits remain suggestions")
    parser.add_argument("--issn", help="Exact print/electronic ISSN")
    args = parser.parse_args()
    if not args.name and not args.issn:
        parser.error("Provide --name and/or --issn")
    try:
        result = resolve(args.name, args.issn)
    except ValueError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "resolved" else 2


if __name__ == "__main__":
    sys.exit(main())
