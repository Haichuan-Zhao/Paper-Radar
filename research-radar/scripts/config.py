#!/usr/bin/env python3
"""Load and validate the unified Research Radar profile (the user-facing switches).

The profile is JSON or a Markdown document with one fenced JSON block. It captures the research question, the
discovery window, the include-only/exclude filters ("switches"), the scoring
parameters, the venue-metric input files, and the optional automation/notification
settings. One profile = one reproducible literature-radar configuration, usable
for any research direction.
"""
from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

from credentials import redact
from identifiers import normalize_issn
import assessment as assessment_mod
import fulltext_access as access_mod
import search_strategy

PROFILE_SCHEMA_VERSION = 1

# Allowed value sets for the filter switches. Everything is validated so a typo
# (e.g. "Q5" or a CAS partition "5") fails loudly instead of silently dropping
# every paper.
ALLOWED_WOS_INDEXES = ("SCIE", "SSCI", "ESCI", "AHCI")
ALLOWED_CAS_PARTITIONS = (1, 2, 3, 4)
ALLOWED_JCR_QUARTILES = ("Q1", "Q2", "Q3", "Q4")
ALLOWED_CCF_RANKS = ("A", "B", "C")
ALLOWED_DATE_BASIS = ("online-first", "online", "publication")

# Sensible default filters: hard-exclude non-research material, never silently
# drop by venue rank unless the user explicitly turns a switch on.
DEFAULT_EXCLUDED_TYPES = [
    "editorial", "correction", "retraction", "news", "book-review",
    "erratum", "letter", "comment", "reply",
]

class ProfileError(ValueError):
    """Raised when a profile is missing a required field or holds an invalid value."""


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, int, float)):
        return [value]
    raise ProfileError(f"expected a list or single value, got {type(value).__name__}")


def _as_str_list(value: Any, field: str) -> list[str]:
    items = _as_list(value)
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise ProfileError(f"{field} must contain non-empty strings")
    return [str(item).strip() for item in items]


def _optional_int_list(value: Any, allowed: tuple[int, ...], field: str) -> list[int] | None:
    if value is None:
        return None
    items = _as_list(value)
    result: list[int] = []
    for item in items:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or int(item) != item:
            raise ProfileError(f"{field} must be a list of integers from {allowed}")
        if int(item) not in allowed:
            raise ProfileError(f"{field} has {item!r}; allowed values are {allowed}")
        result.append(int(item))
    return sorted(set(result))


def _optional_enum_list(value: Any, allowed: tuple[str, ...], field: str) -> list[str] | None:
    if value is None:
        return None
    items = _as_list(value)
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if text.upper() not in allowed:
            raise ProfileError(f"{field} has {item!r}; allowed values are {allowed}")
        result.append(text.upper())
    return sorted(set(result))


def _bounded(value: Any, field: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileError(f"{field} must be a number")
    number = float(value)
    if not math.isfinite(number) or not low <= number <= high:
        raise ProfileError(f"{field} must be between {low:g} and {high:g}")
    return number


def _validate_date(value: Any, field: str, allow_today: bool = False) -> str:
    text = str(value or "").strip()
    if allow_today and text.lower() in {"today", "auto", "now"}:
        return text.lower()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ProfileError(f"{field} must be YYYY-MM-DD (or 'today'), got {value!r}") from exc


def _validate_filters(filters: Any) -> dict[str, Any]:
    if filters is None:
        return {"include_only": {}, "exclude": {"types": list(DEFAULT_EXCLUDED_TYPES)}, "preprint_venue_policy": "separate"}
    if not isinstance(filters, dict):
        raise ProfileError("filters must be an object")

    include = filters.get("include_only")
    include = include if isinstance(include, dict) else {}
    exclude = filters.get("exclude")
    exclude = exclude if isinstance(exclude, dict) else {}

    include_only: dict[str, Any] = {}
    policy = filters.get("preprint_venue_policy", "separate")
    if policy not in {"separate", "apply"}:
        raise ProfileError("filters.preprint_venue_policy must be separate|apply")
    if include.get("wos_indexes") is not None:
        include_only["wos_indexes"] = _optional_enum_list(include["wos_indexes"], ALLOWED_WOS_INDEXES, "filters.include_only.wos_indexes")
    if include.get("cas_partitions") is not None:
        include_only["cas_partitions"] = _optional_int_list(include["cas_partitions"], ALLOWED_CAS_PARTITIONS, "filters.include_only.cas_partitions")
    if include.get("jcr_quartiles") is not None:
        include_only["jcr_quartiles"] = _optional_enum_list(include["jcr_quartiles"], ALLOWED_JCR_QUARTILES, "filters.include_only.jcr_quartiles")
    if include.get("ccf_ranks") is not None:
        include_only["ccf_ranks"] = _optional_enum_list(include["ccf_ranks"], ALLOWED_CCF_RANKS, "filters.include_only.ccf_ranks")
    if include.get("types") is not None:
        include_only["types"] = _as_str_list(include["types"], "filters.include_only.types")
    if include.get("min_jif") is not None:
        include_only["min_jif"] = _bounded(include["min_jif"], "filters.include_only.min_jif", 0, 1000)
    for flag in ("open_access_only", "peer_reviewed_only"):
        if include.get(flag) is not None:
            if not isinstance(include[flag], bool):
                raise ProfileError(f"filters.include_only.{flag} must be a boolean")
            include_only[flag] = include[flag]

    excluded_types = _as_str_list(exclude.get("types"), "filters.exclude.types") if exclude.get("types") is not None else list(DEFAULT_EXCLUDED_TYPES)
    excluded: dict[str, Any] = {"types": excluded_types}
    if exclude.get("publishers") is not None:
        excluded["publishers"] = _as_str_list(exclude["publishers"], "filters.exclude.publishers")
    if exclude.get("title_keywords") is not None:
        excluded["title_keywords"] = _as_str_list(exclude["title_keywords"], "filters.exclude.title_keywords")
    return {"include_only": include_only, "exclude": excluded, "preprint_venue_policy": policy}


def _validate_automation(automation: Any) -> dict[str, Any]:
    if automation is None:
        return {"enabled": False, "schedule": "0 9 * * 1", "incremental": True, "notify": {"on": "new_shortlist"}}
    if not isinstance(automation, dict):
        raise ProfileError("automation must be an object")
    result = {
        "enabled": bool(automation.get("enabled", False)),
        "schedule": str(automation.get("schedule") or "0 9 * * 1"),
        "incremental": bool(automation.get("incremental", True)),
    }
    if automation.get("notify") is None:
        result["notify"] = {"on": "new_shortlist"}
    elif not isinstance(automation["notify"], dict):
        raise ProfileError("automation.notify must be an object")
    else:
        notify = automation["notify"]
        on = str(notify.get("on") or "new_shortlist").strip().lower()
        if on not in {"never", "always", "new_shortlist", "errors"}:
            raise ProfileError("automation.notify.on must be never|always|new_shortlist|errors")
        result["notify"] = dict(notify)
        result["notify"]["on"] = on
    return result


def _validate_easyscholar(value: Any) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ProfileError("easyscholar must be an object")
    if not isinstance(value.get("enabled", False), bool):
        raise ProfileError("easyscholar.enabled must be a boolean")
    result = {
        "enabled": value.get("enabled", False),
        "secret_key_env": str(value.get("secret_key_env") or "EASYSCHOLAR_SECRET_KEY"),
        "secret_key": value.get("secret_key"),
        "credentials_file": str(value.get("credentials_file") or "") or None,
        "cache_file": str(value.get("cache_file") or "") or None,
        "pause": _bounded(value.get("pause", 1.0), "easyscholar.pause", 0, 60),
        "timeout": _bounded(value.get("timeout", 15.0), "easyscholar.timeout", 0.1, 120),
        "cache_ttl_hours": _bounded(value.get("cache_ttl_hours", 168), "easyscholar.cache_ttl_hours", 0, 8760),
        "dataset_versions": value.get("dataset_versions") or {},
    }
    if result["secret_key"] is not None and not isinstance(result["secret_key"], str):
        raise ProfileError("easyscholar.secret_key must be a string")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", result["secret_key_env"]):
        raise ProfileError("easyscholar.secret_key_env must be an environment variable name")
    versions = result["dataset_versions"]
    if not isinstance(versions, dict) or any(not isinstance(v, dict) for v in versions.values()):
        raise ProfileError("easyscholar.dataset_versions must map dataset keys to version objects")
    for version in versions.values():
        if version.get("data_year") is not None and (isinstance(version["data_year"], bool)
                or not re.fullmatch(r"\d{4}", str(version["data_year"]))):
            raise ProfileError("easyscholar.dataset_versions.data_year must be a four-digit year")
        if version.get("edition_year") is not None and (isinstance(version["edition_year"], bool)
                or not isinstance(version["edition_year"], (str, int)) or not str(version["edition_year"]).strip()):
            raise ProfileError("easyscholar.dataset_versions.edition_year must be a version label")
    return result


def _validate_relevance(value: Any) -> dict[str, Any]:
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ProfileError("relevance must be an object")
    mode = value.get("mode", "review")
    if mode not in {"review", "strict_keyword"}:
        raise ProfileError("relevance.mode must be review|strict_keyword")
    groups = value.get("required_concepts", [])
    if not isinstance(groups, list):
        raise ProfileError("relevance.required_concepts must be a list")
    cleaned = []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("name"), str) or not group["name"].strip():
            raise ProfileError("Each required concept needs a name and terms")
        terms = _as_str_list(group.get("terms"), "relevance.required_concepts.terms")
        if not terms:
            raise ProfileError("Each required concept needs at least one term")
        cleaned.append({"name": group["name"].strip(), "terms": terms})
    if len({group["name"] for group in cleaned}) != len(cleaned):
        raise ProfileError("Required concept names must be unique")
    return {"mode": mode, "required_concepts": cleaned}


def _resolve_date_value(value: str, today: date) -> str:
    return today.isoformat() if value in {"today", "auto", "now"} else value


def read_profile_document(path: str | Path) -> dict[str, Any]:
    """Read data only: never evaluate Markdown or accept ambiguous JSON blocks."""
    path = Path(path).expanduser().resolve()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProfileError(f"Cannot read profile {path}") from None
    if path.suffix.casefold() in {".md", ".markdown"}:
        blocks = re.findall(r"^```json[ \t]*\n(.*?)^```[ \t]*$", text, re.M | re.S)
        if len(blocks) != 1:
            raise ProfileError("A Markdown profile must contain exactly one fenced json block")
        text = blocks[0]
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise ProfileError("Invalid JSON in profile (check syntax)") from None
    if not isinstance(raw, dict):
        raise ProfileError("Profile must be a JSON object")
    if "scoring" in raw:
        raise ProfileError("The obsolete scoring block is unsupported; configure content quality/fit using assessment")
    return raw


def load_profile(path: str | Path) -> dict[str, Any]:
    """Read the user document, apply defaults, validate, and normalize paths/dates."""
    profile_path = Path(path).expanduser().resolve()
    raw = read_profile_document(profile_path)

    if not isinstance(raw.get("topic"), str) or not raw["topic"].strip():
        raise ProfileError("profile.topic (研究主题) is required")

    queries = _as_str_list(raw.get("queries"), "queries")
    synonyms = _as_str_list(raw.get("synonyms"), "synonyms")
    if not queries and not synonyms:
        raise ProfileError("Provide at least one of profile.queries (检索词) or profile.synonyms (同义词)")

    date_cfg = raw.get("date") if isinstance(raw.get("date"), dict) else {}
    today = date.today()
    date_from_raw = date_cfg.get("from")
    if not date_from_raw:
        raise ProfileError("profile.date.from is required")
    date_from = _validate_date(date_from_raw, "date.from")
    date_to_raw = date_cfg.get("to", "today")
    date_to = _resolve_date_value(_validate_date(date_to_raw, "date.to", allow_today=True), today)
    if date_from > date_to:
        raise ProfileError("date.from must be <= date.to")
    if date_to > today.isoformat():
        raise ProfileError("date.to must not be later than today; future literature is not observable")

    basis = str(date_cfg.get("basis") or "online-first")
    if basis == "online_first":  # accept the underscore spelling as an alias
        basis = "online-first"
    if basis not in ALLOWED_DATE_BASIS:
        raise ProfileError(f"date.basis must be one of {ALLOWED_DATE_BASIS}")

    count = raw.get("count", 20)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) != count or not 1 <= int(count) <= 200:
        raise ProfileError("count must be an integer from 1 to 200")

    venue_files = _as_str_list(raw.get("venue_metrics_files"), "venue_metrics_files")

    def resolve_path(value: str | None) -> str | None:
        if not value:
            return None
        local = Path(value).expanduser()
        return str((profile_path.parent / local).resolve())

    es = _validate_easyscholar(raw.get("easyscholar"))
    for field in ("credentials_file", "cache_file"):
        es[field] = resolve_path(es[field])
    openalex = raw.get("openalex") or {}
    if not isinstance(openalex, dict):
        raise ProfileError("openalex must be an object")
    key_env = openalex.get("api_key_env") or "OPENALEX_API_KEY"
    if not isinstance(key_env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_env):
        raise ProfileError("openalex.api_key_env must be an environment variable name")
    if openalex.get("api_key") is not None and not isinstance(openalex["api_key"], str):
        raise ProfileError("openalex.api_key must be a string")
    sources = _as_str_list(raw.get("sources", ["crossref", "openalex"]), "sources")
    if not sources or any(s not in {"crossref", "openalex", "arxiv", "biorxiv", "medrxiv"} for s in sources):
        raise ProfileError("sources must use crossref/openalex/arxiv/biorxiv/medrxiv")
    scope = _as_str_list(raw.get("journal_issns"), "journal_issns")
    if any(normalize_issn(x) is None for x in scope):
        raise ProfileError("journal_issns must contain valid ISSNs including their check digits")

    user_prompt = raw.get("user_prompt", raw["topic"])
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise ProfileError("user_prompt must preserve a nonempty original request")
    requirements = raw.get("requirements") or {}
    if not isinstance(requirements, dict) or set(requirements) - {"purpose", "preferred_methods", "context", "hard_constraints"}:
        raise ProfileError("requirements accepts purpose/preferred_methods/context/hard_constraints")
    requirements = dict(requirements)
    for key in ("purpose", "context"):
        if key in requirements and not isinstance(requirements[key], str):
            raise ProfileError(f"requirements.{key} must be a string")
    requirements["preferred_methods"] = _as_str_list(requirements.get("preferred_methods"), "requirements.preferred_methods")
    constraints = requirements.get("hard_constraints", [])
    if not isinstance(constraints, list) or any(not isinstance(c, dict) or not isinstance(c.get("id"), str) or not c["id"].strip() or not isinstance(c.get("description"), str) or not c["description"].strip() for c in constraints):
        raise ProfileError("hard_constraints requires objects with nonempty id and description")
    if len({c["id"] for c in constraints}) != len(constraints):
        raise ProfileError("Hard constraint IDs must be unique")
    requirements["hard_constraints"] = constraints
    preprints = raw.get("preprints") or {}
    if not isinstance(preprints, dict) or set(preprints) - {"arxiv_queries", "biorxiv_categories", "medrxiv_categories"}:
        raise ProfileError("preprints accepts arxiv_queries/biorxiv_categories/medrxiv_categories")
    preprints = {k: _as_str_list(preprints.get(k), "preprints." + k) for k in ("arxiv_queries", "biorxiv_categories", "medrxiv_categories")}
    try:
        search = search_strategy.settings(raw.get("search"))
    except ValueError as exc:
        raise ProfileError(str(exc)) from exc
    try:
        assessment = assessment_mod.config(raw.get("assessment"))
        access = access_mod.settings(raw.get("fulltext_access"))
        access["institution"]["config_file"] = resolve_path(access["institution"]["config_file"])
        routing = access["institution"].get("routing")
        if routing and routing.get("credential_source"):
            routing["credential_source"]["credentials_file"] = resolve_path(routing["credential_source"].get("credentials_file"))
        if routing is not None and access["institution"]["enabled"]:
            access_mod.institution_route(access)
    except assessment_mod.AssessmentError as exc:
        raise ProfileError(str(exc)) from exc
    except access_mod.AccessError as exc:
        raise ProfileError(str(exc)) from exc

    return {
        "schema_version": PROFILE_SCHEMA_VERSION,
        "profile_name": str(raw.get("profile_name") or "").strip(),
        "topic": raw["topic"].strip(),
        "topic_en": str(raw.get("topic_en") or "").strip(),
        "user_prompt": user_prompt.strip(),
        "requirements": requirements,
        "assessment": assessment,
        "search": search,
        "fulltext_access": access,
        "preprints": preprints,
        "queries": queries,
        "synonyms": synonyms,
        "seed_papers": _as_str_list(raw.get("seed_papers"), "seed_papers"),
        "seed_authors": _as_str_list(raw.get("seed_authors"), "seed_authors"),
        "seed_venues": _as_str_list(raw.get("seed_venues"), "seed_venues"),
        "date": {"from": date_from, "to": date_to, "basis": basis},
        "count": int(count),
        "filters": _validate_filters(raw.get("filters")),
        "venue_metrics_files": [resolve_path(x) for x in venue_files],
        "automation": _validate_automation(raw.get("automation")),
        "easyscholar": es,
        "openalex": {"api_key_env": key_env, "credentials_file": resolve_path(openalex.get("credentials_file")),
                     "api_key": openalex.get("api_key")},
        "sources": list(dict.fromkeys(sources)),
        "journal_issns": list(dict.fromkeys(normalize_issn(x) for x in scope)),
        "relevance": _validate_relevance(raw.get("relevance")),
        "_source_path": str(profile_path),
    }


def expand_queries(profile: dict[str, Any]) -> list[str]:
    """Only complete queries are searched; synonyms are evidence-screening terms.

    A legacy synonyms-only profile remains usable, with a coverage warning.
    """
    seen: list[str] = []
    for item in (profile["queries"] or profile["synonyms"]):
        key = item.casefold()
        if key not in {v.casefold() for v in seen}:
            seen.append(item)
    return seen


if __name__ == "__main__":
    import sys

    try:
        loaded = load_profile(sys.argv[1] if len(sys.argv) > 1 else "radar-profile.json")
    except ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    loaded.pop("_source_path", None)
    print(json.dumps(redact(loaded), ensure_ascii=False, indent=2))
