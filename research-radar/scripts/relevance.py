"""Evidence-bearing concept screening; lexical matches are not scientific review."""
from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable


def _text(value: Any) -> str:
    return " ".join(re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", str(value or "")).casefold()).split())


def contains(text: str, term: str) -> bool:
    term = _text(term)
    # Chinese has no word separators; Latin abbreviations must not match substrings.
    if re.search(r"[\u4e00-\u9fff]", term):
        return term in text
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text))


def screen(record: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    groups = config.get("required_concepts") or []
    title, abstract = _text(record.get("title")), _text(record.get("abstract"))
    evidence = []
    for group in groups:
        hits = [{"term": term, "field": field} for term in group["terms"]
                for field, text in (("title", title), ("abstract", abstract)) if contains(text, term)]
        evidence.append({"concept": group["name"], "matched": bool(hits), "hits": hits})
    missing = [entry["concept"] for entry in evidence if not entry["matched"]]
    status = "not_configured" if not groups else "matched" if not missing else "needs_verification"
    if missing and abstract and config.get("mode") == "strict_keyword":
        status = "outside_scope"
    return {"status": status, "method": "concept_groups", "groups": evidence,
            "missing_concepts": missing, "abstract_available": bool(abstract),
            "assessment_level": "title_abstract_keyword_screen"}


def apply(records: Iterable[dict[str, Any]], config: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        record["topic_match"] = screen(record, config)
        status = record["topic_match"]["status"]
        counts[status] = counts.get(status, 0) + 1
    return counts
