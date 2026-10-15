"""Conservative journal identity checks shared by local and live adapters."""
from __future__ import annotations

import re
import unicodedata
from typing import Any


def normalize_issn(value: Any) -> str | None:
    text = re.sub(r"[\s-]", "", str(value or "").upper())
    if not re.fullmatch(r"\d{7}[\dX]", text):
        return None
    check = (11 - sum(int(text[i]) * (8 - i) for i in range(7)) % 11) % 11
    if text[-1] != ("X" if check == 10 else str(check)):
        return None
    return text[:4] + "-" + text[4:]


def normalize_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.replace("&", " and ")
    return " ".join(re.sub(r"[\W_]+", " ", text).split())


def issns(venue: dict[str, Any]) -> set[str]:
    result = set()
    for field in ("issn_l", "issn", "eissn", "print_issn"):
        values = venue.get(field) or []
        if not isinstance(values, list):
            values = re.split(r"[;,|]", str(values))
        for value in values:
            normalized = normalize_issn(value)
            if normalized:
                result.add(normalized)
    return result


def compare_venues(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    """Never let a similar title override contradictory journal identifiers."""
    left_ids, right_ids = issns(left), issns(right)
    common = sorted(left_ids & right_ids)
    if left_ids and right_ids:
        return {"status": "matched" if common else "conflict", "method": "issn",
                "shared_issns": common, "left_issns": sorted(left_ids), "right_issns": sorted(right_ids)}
    left_title, right_title = normalize_title(left.get("name")), normalize_title(right.get("name"))
    aliases = right.get("aliases") or []
    if isinstance(aliases, str):
        aliases = aliases.split(";")
    titles = {right_title} | {normalize_title(x) for x in aliases}
    if left_title and left_title in titles:
        return {"status": "name_only", "method": "exact_title" if left_title == right_title else "explicit_alias"}
    return {"status": "unmatched", "method": None}
