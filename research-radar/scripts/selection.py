"""Bind a user's explicit paper selection to a frozen assessment; no downloads."""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import assessment


class SelectionError(ValueError):
    pass


def plan(assessment_dir, *, numbers=None, ids=None, include_si=False):
    """Resolve the chosen report numbers or exact IDs without broadening the set."""
    if (numbers is None) == (ids is None):
        raise SelectionError("Provide report numbers or exact candidate IDs, not both")
    root = Path(assessment_dir)
    try:
        catalog = json.loads((root / "selection-catalog.json").read_text(encoding="utf-8"))
        records = assessment.load_jsonl(root / "ranked.jsonl")
        expected = assessment.selection_catalog(records, catalog["request_fingerprint"])
        if catalog != expected:
            raise ValueError()
        if any(r["assessment"]["request_fingerprint"] != catalog["request_fingerprint"] for r in records):
            raise ValueError()
        candidate_ids = [r["id"] for r in records]
        if len(set(candidate_ids)) != len(candidate_ids):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise SelectionError("Missing, invalid or stale selection catalog; use the matching assessment directory") from None
    text = numbers if numbers is not None else ids
    if not isinstance(text, str):
        raise SelectionError("Selection must be a comma-separated string")
    tokens = [part.strip() for part in text.replace("，", ",").replace("、", ",").split(",")]
    if not tokens or any(not part for part in tokens):
        raise SelectionError("Select at least one explicit paper")
    if numbers is not None:
        if any(not re.fullmatch(r"[1-9][0-9]*", token) for token in tokens):
            raise SelectionError("Report numbers must be positive integers separated by commas")
        chosen = list(map(int, tokens))
        lookup = {item["number"]: i for i, item in enumerate(catalog["items"])}
    else:
        chosen = tokens
        lookup = {item["candidate_id"]: i for i, item in enumerate(catalog["items"])}
    if len(set(chosen)) != len(chosen) or any(key not in lookup for key in chosen):
        raise SelectionError("Selection contains duplicate or unknown papers; no plan was created")
    positions = [lookup[key] for key in chosen]
    rows = [copy.deepcopy(records[i]) for i in positions]
    result = {"schema_version": 1, "stage": 2, "status": "planned",
              "catalog_id": catalog["catalog_id"], "request_fingerprint": catalog["request_fingerprint"],
              "selected_ids": [r["id"] for r in rows], "include_si": include_si is True,
              "items": [copy.deepcopy(catalog["items"][i]) for i in positions],
              "execution": "Host downloads only this set using lawful routes and verifies files/versions",
              "authorization_note": "The host must have the human's explicit selection; a plan file alone grants no access or library-write permission"}
    return result, rows


def write(assessment_dir, output, *, numbers=None, ids=None, include_si=False):
    result, rows = plan(assessment_dir, numbers=numbers, ids=ids, include_si=include_si)
    output = Path(output).expanduser().absolute()
    if output.exists():
        raise SelectionError("Selection output already exists; use a new directory")
    result["destination"] = str(output / "pdfs")
    output.mkdir(parents=True)
    assessment.write_jsonl(output / "selected-papers.jsonl", rows)
    (output / "download-plan.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
