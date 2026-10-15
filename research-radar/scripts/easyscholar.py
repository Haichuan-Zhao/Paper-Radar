#!/usr/bin/env python3
"""EasyScholar venue-metric adapter.

Queries the EasyScholar public ranking API
(https://www.easyscholar.cc/open/getPublicationRank) for a journal name and maps
the response into Research Radar's `metrics` schema (JCR quartile, JIF, CAS
partition + Top, CCF rank). The secret key comes from an environment variable
(never from committed files) so each user can plug in their own key.

The adapter is defensive: one failed journal must not fail the whole run, and
raw responses are cached locally so repeated runs do not re-consume quota.
"""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from credentials import CredentialError, redact, resolve_key
from identifiers import compare_venues, issns, normalize_title

API_BASE = "https://www.easyscholar.cc/open"
DEFAULT_SECRET_ENV = "EASYSCHOLAR_SECRET_KEY"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Value normalizers (accept several spellings EasyScholar may return)
# --------------------------------------------------------------------------- #

def _strip_cn_rank(text: str) -> str:
    # "中科院1区" / "1区" / "一区" -> keep the digit via a lookup
    mapping = {"一": "1", "二": "2", "三": "3", "四": "4"}
    return "".join(mapping.get(ch, ch) for ch in text)


def _norm_quartile(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = _strip_cn_rank(str(value)).strip().upper().replace(" ", "")
    text = re.sub(r"^(?:SSCI|SCI)", "", text.replace("区", ""))
    if text in {"1", "Q1"}:
        return "Q1"
    if text in {"2", "Q2"}:
        return "Q2"
    if text in {"3", "Q3"}:
        return "Q3"
    if text in {"4", "Q4"}:
        return "Q4"
    return None


def _norm_partition(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    text = _strip_cn_rank(str(value)).strip()
    text = re.sub(r"[^0-9]", "", text)
    if text in {"1", "2", "3", "4"}:
        return int(text)
    return None


def _norm_ccf(value: Any) -> str | None:
    if value is None:
        return None
    text = _strip_cn_rank(str(value)).strip().upper().replace("类", "")
    if text.startswith("CCF-"):
        text = text[4:]
    text = text.replace(" ", "")
    if text in {"A", "B", "C"}:
        return text
    return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    text = str(value).strip().replace(",", "")
    try:
        result = float(text)
        return result if math.isfinite(result) and result >= 0 else None
    except ValueError:
        return None


def _top(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    if text in {"1", "true", "yes", "y", "top", "是"}:
        return True
    if text in {"0", "false", "no", "n", "否", "否否"}:
        return False
    return None


def map_to_metrics(raw: dict[str, Any], journal_name: str, retrieved_at: str | None = None,
                   dataset_versions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Convert one EasyScholar response into Research Radar metric objects."""
    retrieved_at = retrieved_at or now_iso()
    if not isinstance(raw, dict) or raw.get("code") != 200:
        return {}
    payload = raw.get("data")
    if not isinstance(payload, dict):
        return {}
    official_rank = payload.get("officialRank") or {}
    all_rank = official_rank.get("all") if isinstance(official_rank, dict) else {}
    select_rank = official_rank.get("select") if isinstance(official_rank, dict) else {}
    if not isinstance(all_rank, dict):
        all_rank = {}
    if not isinstance(select_rank, dict):
        select_rank = {}

    metrics: dict[str, Any] = {}
    # Account-selected datasets are a subset of all, not an identity check.
    ranks = {**all_rank, **select_rank}

    q = _norm_quartile(ranks.get("sci")) or _norm_quartile(ranks.get("ssci"))
    if q is not None:
        metrics["jcr_quartile"] = {
            "value": q, "year": None, "edition": "EasyScholar live",
            "source": "EasyScholar", "source_url": "https://www.easyscholar.cc/",
            "retrieved_at": retrieved_at, "verified": True,
        }
    jif = _number(ranks.get("sciif"))
    if jif is not None:
        metrics["jif"] = {
            "value": jif, "year": None, "edition": "EasyScholar live",
            "source": "EasyScholar", "source_url": "https://www.easyscholar.cc/",
            "retrieved_at": retrieved_at, "verified": True,
        }
    cas = _norm_partition(ranks.get("sciUp")) or _norm_partition(ranks.get("sciBase"))
    if cas is not None:
        metric: dict[str, Any] = {
            "value": cas, "year": None, "edition": "EasyScholar live",
            "source": "EasyScholar", "source_url": "https://www.easyscholar.cc/",
            "retrieved_at": retrieved_at, "verified": True,
            "broad_category": None,
        }
        top = _top(ranks.get("sciUpTop"))
        if top is not None:
            metric["top"] = top
        if ranks.get("sciwarn") or ranks.get("sciWarning"):
            metric["warning"] = str(ranks.get("sciwarn") or ranks.get("sciWarning")).strip()
        metrics["cas_partition"] = metric
    ccf = _norm_ccf(ranks.get("ccf") or ranks.get("ccfJournal") or ranks.get("ccfConference"))
    if ccf is not None:
        metrics["ccf_rank"] = {
            "value": ccf, "field": None, "directory_version": None, "edition": "EasyScholar live",
            "source": "EasyScholar", "source_url": "https://www.easyscholar.cc/",
            "retrieved_at": retrieved_at, "verified": True,
        }
    datasets = {"jcr_quartile": "sci" if _norm_quartile(ranks.get("sci")) else "ssci", "jif": "sciif", "ccf_rank": "ccf",
                "cas_partition": "sciUp" if _norm_partition(ranks.get("sciUp")) else "sciBase"}
    for key, metric in metrics.items():
        dataset = datasets[key]
        version = (dataset_versions or {}).get(dataset) or {}
        metric.update({"dataset_key": dataset, "query_name": journal_name,
                       "year": version.get("data_year"), "edition": version.get("edition_year"),
                       "version_source": "user_configuration" if version else None,
                       "verified": False, "identity_verified": False,
                       "verification_status": "provider_observation_unconfirmed"})
        if key == "ccf_rank":
            metric["directory_version"] = version.get("edition_year")
    return metrics


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #

class EasyScholarError(RuntimeError):
    """Safe error carrying only a status/reason, never the secret key or URL."""


def resolve_secret_key(config: dict[str, Any]) -> str | None:
    return resolve_key(config, "easyscholar")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        # The key is in the provider's required query string; never forward it.
        raise EasyScholarError("redirect_not_followed")


def query_publication(name: str, secret_key: str, timeout: float = 15.0) -> dict[str, Any]:
    params = urllib.parse.urlencode({"secretKey": secret_key, "publicationName": name})
    url = f"{API_BASE}/getPublicationRank?{params}"
    headers = {"Accept": "application/json", "User-Agent": "ResearchRadar/1.0"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise EasyScholarError(f"http_{exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise EasyScholarError(type(exc).__name__) from None
    if not isinstance(payload, dict):
        raise EasyScholarError("invalid_response")
    return payload


# --------------------------------------------------------------------------- #
# Enrichment with caching
# --------------------------------------------------------------------------- #

def _journal_name(record: dict[str, Any]) -> str | None:
    venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
    name = str(venue.get("name") or "").strip()
    return name or None


def _normalize_name(name: str) -> str:
    text = unicodedata.normalize("NFKC", name).casefold()
    return re.sub(r"\s+", " ", text).strip()


def _load_cache(path: Path, account: str, ttl_hours: float) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                stamp = datetime.fromisoformat(entry.get("retrieved_at", "").replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600
            except (ValueError, TypeError, AttributeError):
                continue
            if (isinstance(entry, dict) and entry.get("name") and entry.get("account") == account
                    and entry.get("schema_version") == 2 and 0 <= age < ttl_hours
                    and isinstance(entry.get("raw"), dict) and entry["raw"].get("code") == 200
                    and isinstance(entry["raw"].get("data"), dict)):
                cache[_normalize_name(entry["name"])] = entry
    except (OSError, json.JSONDecodeError):
        return cache
    return cache


def enrich(records: Iterable[dict[str, Any]], secret_key: str, cache_path: Path | None = None,
           pause: float = 1.0, timeout: float = 15.0, cache_ttl_hours: float = 168,
           dataset_versions: dict[str, Any] | None = None) -> dict[str, Any]:
    """Query EasyScholar for each unique journal name and inject metrics.

    Returns a report; never raises on per-journal failures.
    """
    account = hashlib.sha256(secret_key.encode()).hexdigest()
    cache = _load_cache(cache_path, account, cache_ttl_hours) if cache_path else {}
    records = list(records)
    # Unique journal names that have no cached entry.
    names: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("publication_type") == "preprint":
            continue
        if (record.get("metadata_conflicts") or (record.get("topic_match") or {}).get("status") == "outside_scope"
                or (record.get("journal_scope_match") or {}).get("status") == "outside_scope"):
            continue
        name = _journal_name(record)
        if not name:
            continue
        key = _normalize_name(name)
        names.setdefault(key, []).append(record)

    queried = 0
    matched = 0
    failed: list[dict[str, str]] = []
    cache_hits = 0
    observed = 0
    for key, group in names.items():
        entry = cache.get(key)
        raw = entry.get("raw") if entry else None
        if raw is None:
            queried += 1
            try:
                raw = query_publication(group[0]["venue"]["name"], secret_key, timeout)
            except EasyScholarError as exc:
                failed.append({"journal": group[0]["venue"]["name"], "error": str(exc)})
                if pause > 0:
                    time.sleep(pause)
                continue
            raw = redact(raw, (secret_key,))
            if raw.get("code") != 200 or not isinstance(raw.get("data"), dict):
                code = raw.get("code")
                failed.append({"journal": group[0]["venue"]["name"],
                               "error": f"provider_code_{code}" if isinstance(code, int) else "invalid_provider_response"})
                if pause > 0:
                    time.sleep(pause)
                continue
            retrieved_at = now_iso()
            entry = {"schema_version": 2, "account": account, "name": group[0]["venue"]["name"], "retrieved_at": retrieved_at, "raw": raw}
            cache[key] = entry
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(cache_path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            if pause > 0:
                time.sleep(pause)
        else:
            cache_hits += 1
        metrics = map_to_metrics(raw, group[0]["venue"]["name"], entry.get("retrieved_at"), dataset_versions)
        data = raw.get("data") or {}
        official = data.get("officialRank") or {}
        custom = data.get("customRank") or {}
        official = official if isinstance(official, dict) else {}
        custom = custom if isinstance(custom, dict) else {}
        if metrics or official.get("all") or official.get("select") or custom.get("rank"):
            observed += len(group)
        for record in group:
            payload = raw.get("data") or {}
            # Some response versions omit journal identity entirely. A successful
            # name query then remains an observation, never an ISSN-verified match.
            returned = {"name": payload.get("publicationName") or payload.get("journalName"),
                        "issn": payload.get("issn"), "issn_l": payload.get("issn_l"), "eissn": payload.get("eissn")}
            comparison = compare_venues(record.get("venue") or {}, returned)
            if comparison["status"] == "unmatched":
                comparison["status"] = "name_query_unconfirmed" if not returned["name"] and not issns(returned) else "conflict"
            record.setdefault("venue_matches", []).append({"provider": "EasyScholar", **comparison,
                                                          "query_name": record["venue"]["name"], "retrieved_at": entry.get("retrieved_at")})
            record.setdefault("venue_ratings", {})["easyscholar"] = {
                "official": payload.get("officialRank") or {}, "custom": payload.get("customRank") or {},
                "retrieved_at": entry.get("retrieved_at"), "identity_status": comparison["status"]}
            if comparison["status"] == "conflict" or record.get("metadata_conflicts"):
                continue
            record.setdefault("metrics", {})
            provider_verified = False
            for metric_key, metric in metrics.items():
                metric = json.loads(json.dumps(metric))
                metric["identity_verified"] = comparison["status"] == "matched"
                metric["match_method"] = comparison["method"] or "name_query"
                versioned = metric.get("year") if metric_key == "jif" else metric.get("year") or metric.get("edition")
                metric["verified"] = bool(metric["identity_verified"] and versioned)
                if metric["verified"]:
                    metric["verification_status"] = "identifier_match_with_user_supplied_version"
                existing = record["metrics"].get(metric_key)
                if existing is None:
                    record["metrics"][metric_key] = metric
                    provider_verified = provider_verified or metric["verified"]
                else:
                    existing.setdefault("observations", []).append(metric)
                    # Only compare observations of the same explicitly dated edition.
                    if (metric.get("edition") and existing.get("edition") == metric["edition"]
                            and existing.get("value") != metric.get("value")):
                        existing["conflict"] = True
                        existing["verified"] = False
            matched += int(provider_verified)
    return {"journals_queried": queried, "cache_hits": cache_hits, "papers_observed": observed,
            "papers_enriched": matched, "failures": failed}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Query EasyScholar ranking for journal names")
    parser.add_argument("--name", action="append", help="Journal name (repeatable)")
    parser.add_argument("--secret-key-env", default=DEFAULT_SECRET_ENV)
    parser.add_argument("--credentials-file", type=Path, help="Private JSON containing the user's key")
    parser.add_argument("--candidates", type=Path, help="Candidate JSONL to enrich in place (writes enriched JSONL to --output)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cache", type=Path)
    args = parser.parse_args()

    try:
        secret_key = resolve_secret_key({"secret_key_env": args.secret_key_env, "credentials_file": args.credentials_file})
    except CredentialError as exc:
        print(f"credential error: {exc}", file=sys.stderr)
        return 2
    if not secret_key:
        print(f"error: set {args.secret_key_env} before running", file=sys.stderr)
        return 2

    if args.name:
        for name in args.name:
            try:
                raw = redact(query_publication(name, secret_key), (secret_key,))
            except EasyScholarError as exc:
                print(json.dumps({"name": name, "error": str(exc)}, ensure_ascii=False))
                continue
            print(json.dumps({"name": name, "metrics": map_to_metrics(raw, name), "raw": raw}, ensure_ascii=False, indent=2))
        return 0

    if args.candidates and args.output:
        records = [json.loads(line) for line in args.candidates.read_text(encoding="utf-8").splitlines() if line.strip()]
        report = enrich(records, secret_key, args.cache)
        args.output.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
