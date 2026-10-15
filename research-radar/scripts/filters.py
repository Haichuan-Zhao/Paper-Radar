#!/usr/bin/env python3
"""Deterministic enforcement of the profile's filter "switches".

A switch such as "only CAS zone 1" must never silently drop a paper whose CAS
partition is unknown/unverified (that would be a false negative). This module
therefore produces one of three decisions per record:

- `exclude`            — a hard, evidence-backed reason to drop it;
- `needs_verification` — a gate the user turned on cannot be evaluated, so the
                         paper is kept but flagged for manual attention;
- `keep`               — every switched gate is satisfied.

Venue-metric gates only trust metrics flagged `verified: true`.
"""
from __future__ import annotations

from typing import Any, Iterable


def _verified_metric(record: dict[str, Any], key: str) -> tuple[Any, dict[str, Any]]:
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return None, {}
    obj = metrics.get(key)
    if (isinstance(obj, dict) and obj.get("verified") is True
            and not obj.get("conflict") and obj.get("identity_verified") is not False):
        return obj.get("value"), obj
    return None, obj if isinstance(obj, dict) else {}


def _venue(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("venue")
    return value if isinstance(value, dict) else {}


def _norm_cas(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        result = int(str(value).strip().replace("区", ""))
    except (TypeError, ValueError):
        return None
    return result if result in {1, 2, 3, 4} else None


def _norm_quartile(value: Any) -> str | None:
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


def _norm_ccf(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace("类", "")
    if text.startswith("CCF-"):
        text = text[4:]
    return text if text in {"A", "B", "C"} else None


def _float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _gate(checks: list[dict[str, Any]], field: str, matched: bool | None, detail: str) -> None:
    checks.append({"field": field, "matched": matched, "detail": detail})


def _canonical_type(value: Any) -> str:
    """Normalize a publication-type string so Crossref-native and record-level
    spellings agree (the discovery scripts normalize `proceedings-article` to
    `conference-paper` on the record)."""
    text = str(value or "").strip().lower().replace("_", "-")
    if text in {"proceedings-article", "proceedings", "conference", "conference-paper"}:
        return "conference-paper"
    if text == "article":
        return "journal-article"
    return text


def filter_record(record: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    """Return the filter decision object for one record."""
    include = filters.get("include_only") if isinstance(filters.get("include_only"), dict) else {}
    include = dict(include)
    exclude = filters.get("exclude") if isinstance(filters.get("exclude"), dict) else {}

    reasons: list[str] = []
    checks: list[dict[str, Any]] = []
    exclude_reasons: list[str] = []
    unknown_gates: list[str] = []

    if record.get("metadata_conflicts"):
        _gate(checks, "metadata_identity", None, "Sources disagree on paper/journal identity; inspect source_records")
        unknown_gates.append("metadata_identity")
    if any(m.get("status") in {"conflict", "ambiguous"} for m in record.get("venue_matches", [])):
        _gate(checks, "venue_identity", None, "Journal match is conflicting or ambiguous")
        unknown_gates.append("venue_identity")
    topic = record.get("topic_match") or {}
    if topic.get("status") == "outside_scope":
        exclude_reasons.append("missing required topic concepts: " + ", ".join(topic.get("missing_concepts", [])))
        _gate(checks, "topic_match", False, "Required concept groups failed explicit strict_keyword screening")
    elif topic.get("status") == "needs_verification":
        unknown_gates.append("topic_match")
        _gate(checks, "topic_match", None, "Missing lexical evidence for: " + ", ".join(topic.get("missing_concepts", [])))
    elif topic.get("status") == "matched":
        _gate(checks, "topic_match", True, "All configured concept groups have title/abstract evidence")
    membership = (record.get("discovery") or {}).get("date_membership") or {}
    if membership.get("status") == "needs_date_verification":
        unknown_gates.append("publication_date")
        _gate(checks, "publication_date", None, "Date basis or precision is unverified")
    scope = record.get("journal_scope_match") or {}
    if scope.get("status") == "outside_scope":
        exclude_reasons.append("journal ISSNs are outside the requested journal scope")
    elif scope.get("status") == "needs_verification":
        unknown_gates.append("journal_scope")

    publication_type = _canonical_type(record.get("publication_type"))
    if publication_type == "preprint" and filters.get("preprint_venue_policy", "separate") == "separate":
        skipped = [k for k in ("wos_indexes", "cas_partitions", "jcr_quartiles", "ccf_ranks", "min_jif") if include.get(k) is not None]
        for key in skipped:
            include.pop(key, None)
            checks.append({"field": key, "matched": "not_applicable", "detail": "Preprint evaluated in the separate content track; no journal rating inferred"})
    title = str(record.get("title") or "")

    # --- Exclude switches (hard drops) ---
    for token in exclude.get("publishers", []):
        publisher = str(_venue(record).get("publisher") or "").casefold()
        if str(token).strip().casefold() in publisher:
            exclude_reasons.append(f"publisher excluded: {token}")

    if publication_type in {_canonical_type(t) for t in exclude.get("types", [])}:
        exclude_reasons.append(f"excluded publication type: {publication_type}")

    for token in exclude.get("title_keywords", []):
        if str(token).strip().casefold() in title.casefold():
            exclude_reasons.append(f"excluded title keyword: {token}")

    # --- Include-only switches ---
    wanted_types = include.get("types")
    if wanted_types:
        allowed = {_canonical_type(t) for t in wanted_types}
        if not publication_type:
            unknown_gates.append("publication_type")
        elif publication_type not in allowed:
            exclude_reasons.append(f"type {publication_type or 'unknown'} not in include_only.types")
        else:
            _gate(checks, "types", True, f"type {publication_type} allowed")

    wos = include.get("wos_indexes")
    if wos:
        indexes, obj = _verified_metric(record, "wos_indexes")
        if not obj and _venue(record).get("wos_verified") is True:
            indexes = _venue(record).get("wos_indexes")
        if isinstance(indexes, str):
            indexes = [indexes]
        indexes = {str(x).strip().upper() for x in (indexes or []) if str(x).strip()}
        if indexes:
            hit = bool(indexes & {str(w).upper() for w in wos})
            _gate(checks, "wos_indexes", hit, f"venue indexes {sorted(indexes)} vs wanted {wos}")
            if not hit:
                exclude_reasons.append(f"venue not in WOS indexes {wos}")
        else:
            _gate(checks, "wos_indexes", None, "WOS index unknown/unverified")
            unknown_gates.append("wos_indexes")

    cas_wanted = include.get("cas_partitions")
    if cas_wanted:
        value, _ = _verified_metric(record, "cas_partition")
        cas = _norm_cas(value)
        if cas is not None:
            hit = cas in cas_wanted
            _gate(checks, "cas_partition", hit, f"CAS {cas} vs wanted {cas_wanted}")
            if not hit:
                exclude_reasons.append(f"CAS {cas} not in include_only.cas_partitions {cas_wanted}")
        else:
            _gate(checks, "cas_partition", None, "CAS partition unknown/unverified")
            unknown_gates.append("cas_partition")

    jcr_wanted = include.get("jcr_quartiles")
    if jcr_wanted:
        value, _ = _verified_metric(record, "jcr_quartile")
        q = _norm_quartile(value)
        if q is not None:
            hit = q in jcr_wanted
            _gate(checks, "jcr_quartiles", hit, f"JCR {q} vs wanted {jcr_wanted}")
            if not hit:
                exclude_reasons.append(f"JCR {q} not in include_only.jcr_quartiles {jcr_wanted}")
        else:
            _gate(checks, "jcr_quartiles", None, "JCR quartile unknown/unverified")
            unknown_gates.append("jcr_quartiles")

    ccf_wanted = include.get("ccf_ranks")
    if ccf_wanted:
        value, _ = _verified_metric(record, "ccf_rank")
        ccf = _norm_ccf(value)
        if ccf is not None:
            hit = ccf in ccf_wanted
            _gate(checks, "ccf_ranks", hit, f"CCF {ccf} vs wanted {ccf_wanted}")
            if not hit:
                exclude_reasons.append(f"CCF {ccf} not in include_only.ccf_ranks {ccf_wanted}")
        else:
            _gate(checks, "ccf_ranks", None, "CCF rank unknown/unverified")
            unknown_gates.append("ccf_ranks")

    min_jif = include.get("min_jif")
    if min_jif is not None:
        value, _ = _verified_metric(record, "jif")
        jif = _float(value)
        if jif is not None:
            hit = jif >= float(min_jif)
            _gate(checks, "min_jif", hit, f"JIF {jif} vs minimum {min_jif}")
            if not hit:
                exclude_reasons.append(f"JIF {jif} below include_only.min_jif {min_jif}")
        else:
            _gate(checks, "min_jif", None, "JIF unknown/unverified")
            unknown_gates.append("min_jif")

    if include.get("open_access_only"):
        oa = record.get("open_access")
        if oa is None:
            _gate(checks, "open_access_only", None, "open-access status unknown")
            unknown_gates.append("open_access_only")
        elif bool(oa) is False:
            _gate(checks, "open_access_only", False, "not open access")
            exclude_reasons.append("not open access (open_access_only switch)")
        else:
            _gate(checks, "open_access_only", True, "open access")

    if include.get("peer_reviewed_only"):
        pr = record.get("peer_review_status")
        if pr is None:
            _gate(checks, "peer_reviewed_only", None, "peer-review status unknown")
            unknown_gates.append("peer_reviewed_only")
        elif str(pr).casefold() in {"no", "false", "preprint", "not_peer_reviewed"}:
            _gate(checks, "peer_reviewed_only", False, "not peer reviewed")
            exclude_reasons.append("not peer reviewed (peer_reviewed_only switch)")
        elif str(pr).casefold() in {"yes", "true", "peer_reviewed", "peer-reviewed"}:
            _gate(checks, "peer_reviewed_only", True, "peer reviewed")
        else:
            _gate(checks, "peer_reviewed_only", None, "peer-review status unknown")
            unknown_gates.append("peer_reviewed_only")

    if exclude_reasons:
        decision = "exclude"
        reasons = exclude_reasons
    elif unknown_gates:
        decision = "needs_verification"
        reasons = [f"cannot evaluate switched gate(s): {', '.join(sorted(set(unknown_gates)))}"]
    else:
        decision = "keep"
        reasons = ["all switched filters satisfied"]

    return {"decision": decision, "reasons": reasons, "checks": checks}


def apply_filters(records: Iterable[dict[str, Any]], filters: dict[str, Any]) -> dict[str, int]:
    """Attach `record['filter']` to every record and return a decision count summary."""
    counts = {"keep": 0, "exclude": 0, "needs_verification": 0}
    for record in records:
        result = filter_record(record, filters)
        record["filter"] = result
        counts[result["decision"]] += 1
    return counts


def partition(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split records into kept / needs-verification / excluded lists."""
    kept: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for record in records:
        decision = (record.get("filter") or {}).get("decision", "keep")
        if decision == "exclude":
            excluded.append(record)
        elif decision == "needs_verification":
            pending.append(record)
        else:
            kept.append(record)
    return kept, pending, excluded


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 3:
        print("usage: filters.py <candidates.jsonl> <filters.json>", file=sys.stderr)
        raise SystemExit(2)
    records = [json.loads(line) for line in open(sys.argv[1], encoding="utf-8") if line.strip()]
    filters = json.load(open(sys.argv[2], encoding="utf-8"))
    counts = apply_filters(records, filters)
    print(json.dumps(counts, ensure_ascii=False))
