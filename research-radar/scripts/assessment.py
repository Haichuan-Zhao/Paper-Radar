"""Evidence-bound content assessment; the host LLM reviews, Python aggregates.

No embedded model API, reputation points, venue points or inferred reviews.
Validation checks structure/access/anchors, not the truth of an LLM's claims.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import fulltext_access as access_mod
import claim_audit as claims_mod

VERSION = "research-radar-content-v4"
REVIEW_SCHEMA = 5  # v5 requires claim audits and evidence-bound report statements.
QUALITY = {"motivation": 15, "originality": 15, "rigor": 25, "evidence": 25,
           "reproducibility": 10, "figures": 10}
MATCH = {"problem": 45, "approach": 25, "context": 20, "intent": 10}
DEFAULTS = {"quality_weight": 0.6, "quality_floor": 70, "match_floor": 70,
            "shortlist_threshold": 75, "must_read_threshold": 85, "watchlist_threshold": 65,
            "critical_dimension_floor": 3, "review_limit": 60,
            "quality_weights": QUALITY, "match_weights": MATCH}
KINDS = {"abstract", "full_text", "figure", "table", "repository", "prior_work", "metadata", "user_prompt"}


class AssessmentError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def finite(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def config(value=None):
    if value is not None and not isinstance(value, dict):
        raise AssessmentError("assessment must be an object")
    value = value or {}
    if set(value) - set(DEFAULTS):
        raise AssessmentError("Unknown assessment settings: " + ", ".join(sorted(set(value) - set(DEFAULTS))))
    result = copy.deepcopy(DEFAULTS)
    result.update(copy.deepcopy(value))
    for key in ("quality_weight", "quality_floor", "match_floor", "shortlist_threshold", "must_read_threshold", "watchlist_threshold", "critical_dimension_floor"):
        upper = 1 if key == "quality_weight" else 5 if key == "critical_dimension_floor" else 100
        if not finite(result[key], 0, upper):
            raise AssessmentError(f"assessment.{key} must be finite in [0, {upper}]")
    if not 0 < result["quality_weight"] < 1:
        raise AssessmentError("Both quality and match must have a positive composite weight")
    if not result["watchlist_threshold"] <= result["shortlist_threshold"] <= result["must_read_threshold"]:
        raise AssessmentError("Assessment thresholds must satisfy watchlist <= shortlist <= must_read")
    if type(result["review_limit"]) is not int or not 1 <= result["review_limit"] <= 1000:
        raise AssessmentError("assessment.review_limit must be an integer in [1, 1000]")
    for key, dimensions in (("quality_weights", QUALITY), ("match_weights", MATCH)):
        weights = result[key]
        if not isinstance(weights, dict) or set(weights) != set(dimensions) or any(not finite(w, 0.01, 100) for w in weights.values()) or not math.isclose(sum(weights.values()), 100):
            raise AssessmentError(f"assessment.{key} needs all dimensions, positive weights summing to 100")
    return result


def request(profile):
    return {"user_prompt": profile.get("user_prompt") or profile["topic"],
            "topic": profile["topic"], "topic_en": profile.get("topic_en"),
            "requirements": profile.get("requirements") or {}, "relevance": profile.get("relevance") or {},
            "filters": profile.get("filters") or {}, "journal_issns": profile.get("journal_issns") or [],
            "date": profile.get("date") or {}}


def fingerprint(record):
    # Any content/identity/version change invalidates the review, even with the
    # same DOI. Venue metrics do not invalidate a blind content evaluation.
    return digest({key: record.get(key) for key in ("id", "doi", "title", "abstract", "publication_type",
                  "published_online", "published", "version", "preprint", "url", "metadata_conflicts")})


def blank_dimension():
    return {"score": None, "rationale": "", "evidence_ids": []}


def template(record, profile):
    prompt = request(profile)
    evidence = [{"id": "request", "kind": "user_prompt", "source": "profile", "locator": "user_prompt + requirements",
                 "excerpt": json.dumps(prompt, ensure_ascii=False, sort_keys=True)}]
    if record.get("abstract"):
        evidence.append({"id": "abstract", "kind": "abstract", "source": record.get("url") or record["id"],
                         "locator": "Abstract", "excerpt": record["abstract"]})
    return {"schema_version": REVIEW_SCHEMA, "rubric_version": VERSION, "candidate_id": record["id"],
            "candidate_fingerprint": fingerprint(record), "request_fingerprint": digest(prompt),
            "reviewer": {"model": "", "reviewed_at": ""}, "paper_type": "other",
            "access": {"full_text": False, "full_text_source": "", "material_candidate_id": "",
                       "material_version": "unknown", "native_version": None, "identity_evidence_id": "",
                       "retrieval_method": "", "verified_at": "", "figure_count": None, "figures_inspected": []},
            "quality": {key: blank_dimension() for key in QUALITY}, "match": {key: blank_dimension() for key in MATCH},
            "evidence": evidence,
            "concept_checks": [{"id": g["name"], "result": "unknown", "rationale": "", "evidence_ids": []}
                               for g in (profile.get("relevance") or {}).get("required_concepts", [])],
            "constraint_checks": [{"id": g["id"], "result": "unknown", "rationale": "", "evidence_ids": []}
                                  for g in (profile.get("requirements") or {}).get("hard_constraints", [])],
            "claim_audit": claims_mod.template(), "findings": [], "strengths": [], "limitations": [],
            "reading_reason": {"text": "", "basis": "reviewer_assessment", "evidence_ids": [], "claim_ids": []},
            "review_confidence": "low"}


def load_jsonl(path):
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise AssessmentError(f"Cannot read {path}: {exc}") from exc
    rows = []
    for i, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            raise AssessmentError(f"Invalid JSON at line {i} of {path}") from None
        if not isinstance(value, dict):
            raise AssessmentError(f"Expected an object at line {i} of {path}")
        rows.append(value)
    return rows


def write_jsonl(path, rows):
    Path(path).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n" for r in rows), encoding="utf-8")


def attach_access(records, rows):
    """Use a later read-only access manifest without changing paper fingerprints."""
    indexed = {r["id"]: r for r in records}
    seen = set()
    for row in rows:
        key = row.get("candidate_id")
        if key not in indexed or key in seen or row.get("candidate_fingerprint") != fingerprint(indexed[key]):
            raise AssessmentError("Unknown, duplicate or stale access manifest candidate")
        seen.add(key)
        indexed[key]["fulltext_access"] = copy.deepcopy(row)


def prepare(records, profile, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = ("review-packet.jsonl", "reviews.template.jsonl", "context.jsonl", "review-manifest.json")
    if any((output / name).exists() for name in names):
        raise AssessmentError("Review output already exists; use a new directory")
    settings = config(profile.get("assessment"))
    candidates = [r for r in records if (r.get("filter") or {}).get("decision") != "exclude"]
    # Budget priority follows topic evidence, not IF or famous authors. This is
    # still a queue; papers outside the budget remain unreviewed, not rejected.
    candidates.sort(key=lambda r: (r.get("preliminary") or {}).get("relevance", 0), reverse=True)
    selected = candidates[:settings["review_limit"]]
    packets = [{"candidate_id": r["id"], "candidate_fingerprint": fingerprint(r), "request": request(profile),
                "paper": {k: r.get(k) for k in ("title", "abstract", "url", "full_text_urls", "fulltext_access", "pdf_path", "version", "publication_type")},
                "rubric_version": VERSION, "quality_weights": settings["quality_weights"], "match_weights": settings["match_weights"]}
               for r in selected]
    contexts = [{"candidate_id": r["id"], "authors": r.get("authors"), "venue": r.get("venue"),
                 "metrics": r.get("metrics"), "peer_review_status": r.get("peer_review_status"), "relations": r.get("relations", []),
                 "author_context": r.get("author_context", []), "policy": "Context only; no author or venue quality points"} for r in selected]
    write_jsonl(output / names[0], packets)
    write_jsonl(output / names[1], [template(r, profile) for r in selected])
    write_jsonl(output / names[2], contexts)
    manifest = {"rubric_version": VERSION, "request_fingerprint": digest(request(profile)), "eligible": len(candidates),
                "prepared": len(selected), "unreviewed_ids": [r["id"] for r in candidates[len(selected):]],
                "quality_weights": settings["quality_weights"], "match_weights": settings["match_weights"],
                "review_order": "topic evidence; authors/venue withheld in primary packet", "settings": settings}
    (output / names[3]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def evidence_index(review):
    indexed, issues = {}, []
    rows = review.get("evidence")
    if not isinstance(rows, list):
        return {}, ["evidence_not_a_list"]
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in indexed:
            issues.append("invalid_or_duplicate_evidence_id")
            continue
        if not claims_mod.one_of(row.get("kind"), KINDS) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("source", "locator", "excerpt")):
            issues.append("incomplete_evidence:" + row["id"])
            continue
        indexed[row["id"]] = row
    return indexed, issues


def anchored(item, indexed):
    ids = item.get("evidence_ids")
    return (isinstance(item.get("rationale"), str) and len(item["rationale"].strip()) >= 12
            and isinstance(ids, list) and bool(ids) and all(isinstance(i, str) and i in indexed for i in ids))


def figures_available(access):
    count = access.get("figure_count")
    inspected = access.get("figures_inspected")
    return (type(count) is int and 0 <= count <= 1000 and isinstance(inspected, list)
            and all(type(x) is int and 1 <= x <= count for x in inspected)
            and set(inspected) == set(range(1, count + 1)))


def assess_axis(review, axis, weights, indexed, access):
    assessed, missing, issues = {}, [], []
    values = review.get(axis) if isinstance(review.get(axis), dict) else {}
    for name, weight in weights.items():
        item = values.get(name)
        prefix = axis + "." + name
        if not isinstance(item, dict) or item.get("score") is None:
            missing.append(name)
            continue
        kinds = {indexed[i]["kind"] for i in item.get("evidence_ids", []) if isinstance(i, str) and i in indexed} if isinstance(item.get("evidence_ids"), list) else set()
        valid = finite(item.get("score"), 0, 5) and anchored(item, indexed)
        if axis == "quality":
            # All final quality dimensions require primary text. Abstract-only
            # impressions remain missing bounds, even if numeric scores supplied.
            valid = valid and access.get("full_text") is True and bool(kinds & {"full_text", "figure", "table", "repository"})
            if name == "originality":
                valid = valid and "prior_work" in kinds
            if name == "figures":
                valid = valid and figures_available(access) and ("full_text" in kinds if access.get("figure_count") == 0 else bool(kinds & {"figure", "table"}))
        else:
            valid = valid and "user_prompt" in kinds and bool(kinds & {"abstract", "full_text", "figure", "table"})
            if access.get("full_text") is True:
                # After acquisition, confirm fit in the actual read material.
                # A publisher abstract may describe a different manuscript
                # revision, especially when only an accepted copy was obtained.
                valid = valid and bool(kinds & {"full_text", "figure", "table"})
        if not valid:
            missing.append(name)
            issues.append("unusable_score_evidence:" + prefix)
            continue
        assessed[name] = {"score": float(item["score"]), "weight": weight, "rationale": item["rationale"], "evidence_ids": item["evidence_ids"]}
    lower = sum(d["score"] / 5 * d["weight"] for d in assessed.values())
    coverage = sum(d["weight"] for d in assessed.values())
    return {"score": round(lower, 2) if not missing else None, "lower": round(lower, 2),
            "upper": round(lower + 100 - coverage, 2), "evidence_coverage": round(coverage, 2),
            "observed_score": round(lower * 100 / coverage, 2) if coverage else None,
            "missing_dimensions": missing, "dimensions": assessed}, issues


def composite(quality, match, alpha):
    return round((quality ** alpha) * (match ** (1 - alpha)), 2)


def validate_checks(rows, required, indexed):
    rows = rows if isinstance(rows, list) else []
    parsed, issues = {}, []
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in required or row.get("id") in parsed:
            issues.append("invalid_or_duplicate_check")
            continue
        result = row.get("result")
        if result not in {"pass", "fail", "unknown"}:
            issues.append("invalid_check_result:" + row["id"])
            result = "unknown"
        if result != "unknown" and not anchored(row, indexed):
            issues.append("unanchored_check:" + row["id"])
            result = "unknown"
        elif result != "unknown" and not any(indexed[i]["kind"] in {"abstract", "full_text", "figure", "table"} for i in row["evidence_ids"]):
            issues.append("non_content_check:" + row["id"])
            result = "unknown"
        parsed[row["id"]] = result
    for key in required:
        parsed.setdefault(key, "unknown")
    return parsed, issues


def validate_material(record, access, indexed):
    """Check the declared reading target. The host still must verify the source.

    DOI records may be read as an explicitly labelled accepted manuscript.
    Preprints of a published paper require a separate preprint candidate/review.
    Unknown or borrowed material never supplies content evidence to Q or M.
    """
    if access.get("full_text") is not True:
        return False, []
    issues = []
    source = access.get("full_text_source")
    identity = indexed.get(access.get("identity_evidence_id"))
    if (not isinstance(source, str) or not source.strip() or not identity
            or identity["kind"] != "full_text" or identity["source"] != source):
        issues.append("full_text_identity_unanchored")
    elif not any(str(record.get(k) or "").casefold() in identity["excerpt"].casefold()
                 for k in ("title", "doi") if record.get(k)):
        issues.append("full_text_identity_mismatch")
    if access.get("material_candidate_id") != record["id"]:
        issues.append("full_text_candidate_mismatch")
    if not access_mod.preprint_url_matches(record, source):
        issues.append("full_text_source_version_mismatch")
    version = access.get("material_version")
    if record.get("publication_type") == "preprint":
        if version != "submittedVersion" or access.get("native_version") != record.get("version"):
            issues.append("full_text_version_mismatch")
    elif not claims_mod.one_of(version, {"publishedVersion", "acceptedVersion"}):
        issues.append("full_text_version_mismatch")
    if record.get("version") in {"publishedVersion", "acceptedVersion"} and version != record["version"]:
        issues.append("full_text_version_mismatch")
    if not claims_mod.one_of(access.get("retrieval_method"), {"open_access", "institution", "publisher_api", "user_file"}):
        issues.append("full_text_retrieval_method_missing")
    elif access["retrieval_method"] == "user_file":
        if not isinstance(source, str) or not Path(source).is_absolute() or not Path(source).is_file():
            issues.append("full_text_local_file_missing")
    elif not access_mod.safe_url(source):
        issues.append("full_text_source_invalid_or_secret_bearing")
    try:
        checked = datetime.fromisoformat(access.get("verified_at", "").replace("Z", "+00:00"))
        if checked.tzinfo is None or checked > datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        issues.append("full_text_check_time_missing")
    return not issues, issues


def score_record(record, review, profile):
    settings = config(profile.get("assessment"))
    result = copy.deepcopy(record)
    if review is None:
        review = template(record, profile)
    if review.get("schema_version") != REVIEW_SCHEMA or review.get("rubric_version") != VERSION:
        raise AssessmentError("Review schema/rubric mismatch for " + record["id"] + "; regenerate templates (schema v5 requires claim audits and anchored report statements)")
    if review.get("candidate_id") != record["id"] or review.get("candidate_fingerprint") != fingerprint(record):
        raise AssessmentError("Stale or mismatched paper review for " + record["id"])
    if review.get("request_fingerprint") != digest(request(profile)):
        raise AssessmentError("Review belongs to a different user request for " + record["id"])
    indexed, issues = evidence_index(review)
    prompt = indexed.get("request")
    # Bind the actual prompt evidence, not just the hash supplied by the agent.
    if not prompt or prompt.get("kind") != "user_prompt" or prompt.get("excerpt") != json.dumps(request(profile), ensure_ascii=False, sort_keys=True):
        indexed = {k: v for k, v in indexed.items() if v["kind"] != "user_prompt"}
        issues.append("request_evidence_mismatch")
    for key, evidence in list(indexed.items()):
        if evidence["kind"] == "abstract" and evidence["excerpt"] not in str(record.get("abstract") or ""):
            issues.append("abstract_excerpt_mismatch:" + key)
            del indexed[key]
    access = review.get("access") if isinstance(review.get("access"), dict) else {}
    readable, access_issues = validate_material(record, access, indexed)
    issues.extend(access_issues)
    if access.get("full_text") is True and not readable:
        access = {**access, "full_text": False}
    if not readable:
        # A declaration tied to another version must not pass scope checks,
        # hard-constraint checks, novelty or prompt-fit using its body/figures.
        indexed = {k: v for k, v in indexed.items() if v["kind"] not in {"full_text", "figure", "table", "repository"}}
    else:
        for key, evidence in list(indexed.items()):
            if evidence["kind"] in {"full_text", "figure", "table"}:
                bound = (evidence.get("material_candidate_id") == record["id"]
                         and evidence.get("material_version") == access.get("material_version")
                         and evidence.get("native_version") == access.get("native_version"))
                declared = any(k in evidence for k in ("material_candidate_id", "material_version", "native_version"))
                if not bound and (declared or evidence["source"] != access["full_text_source"]):
                    issues.append("body_evidence_material_unbound:" + key)
                    del indexed[key]
            elif evidence["kind"] == "prior_work" and evidence["source"] == access["full_text_source"]:
                issues.append("prior_work_requires_external_source:" + key)
                del indexed[key]
    reviewer = review.get("reviewer") if isinstance(review.get("reviewer"), dict) else {}
    reviewed = False
    try:
        timestamp = datetime.fromisoformat(reviewer.get("reviewed_at", "").replace("Z", "+00:00"))
        reviewed = claims_mod.text(reviewer.get("model")) and timestamp.tzinfo is not None and timestamp <= datetime.now(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        pass
    if not reviewed:
        issues.append("missing_reviewer_provenance")
    claim_audit = claims_mod.validate(review.get("claim_audit"), indexed, readable, reviewed, access.get("identity_evidence_id"))
    issues.extend(claim_audit["issues"])
    guarded = copy.deepcopy(review)
    adjustments = []
    quality_rows = guarded.get("quality") if isinstance(guarded.get("quality"), dict) else {}
    for name, item in quality_rows.items():
        if not isinstance(item, dict) or not finite(item.get("score"), 0, 5):
            continue
        original = item["score"]
        if name == "evidence" and claim_audit["quality_pending"]:
            item["score"] = None
        elif name in claim_audit["quality_caps"]:
            item["score"] = min(original, claim_audit["quality_caps"][name])
        if item["score"] != original:
            adjustments.append({"dimension": name, "submitted": original, "applied": item["score"],
                                "reason": "claim_audit:" + claim_audit["status"]})
    claim_audit["score_adjustments"] = adjustments
    quality, qi = assess_axis(guarded, "quality", settings["quality_weights"], indexed, access)
    match, mi = assess_axis(review, "match", settings["match_weights"], indexed, access)
    issues.extend(qi + mi)
    concepts, ci = validate_checks(review.get("concept_checks"), [g["name"] for g in (profile.get("relevance") or {}).get("required_concepts", [])], indexed)
    constraints, hi = validate_checks(review.get("constraint_checks"), [g["id"] for g in (profile.get("requirements") or {}).get("hard_constraints", [])], indexed)
    issues.extend(ci + hi)
    for key, value in list(constraints.items()):
        row = next((r for r in (review.get("constraint_checks") or []) if isinstance(r, dict) and r.get("id") == key), {})
        if value == "fail" and (access.get("full_text") is not True or not any(indexed[i]["kind"] in {"full_text", "figure", "table"} for i in row.get("evidence_ids", []) if i in indexed)):
            constraints[key] = "unknown"
            issues.append("hard_constraint_failure_needs_full_text:" + key)
    if not claims_mod.one_of(review.get("paper_type"), {"empirical", "theoretical", "review", "resource", "other"}):
        issues.append("invalid_paper_type")
    statements, si = claims_mod.statements(review, indexed, claim_audit["claims"])
    issues.extend(si)
    findings = review.get("findings") or []
    confirmed_critical, suspicious, checked_findings = [], [], []
    if not isinstance(findings, list):
        issues.append("findings_not_a_list")
        findings = []
    for item in findings:
        if not isinstance(item, dict) or not claims_mod.one_of(item.get("severity"), {"critical", "major", "minor"}) or not claims_mod.one_of(item.get("status"), {"confirmed", "suspected"}) or not anchored(item, indexed):
            issues.append("invalid_finding")
            continue
        item = copy.deepcopy(item)
        links = item.get("claim_ids")
        bound = (isinstance(links, list) and bool(links) and all(isinstance(i, str) and
                 i in {c["id"] for c in claim_audit["claims"]} for i in links))
        if not bound:
            issues.append("finding_claim_unbound")
        if item["status"] == "confirmed":
            confirmed = (bound and readable and reviewed
                         and any(indexed[i]["kind"] in claims_mod.CONTENT for i in item["evidence_ids"])
                         and claims_mod.focused_verification(item, indexed, item["evidence_ids"]))
            if item["severity"] == "critical":
                confirmed = confirmed and any(c["central"] and c["id"] in (links or []) for c in claim_audit["claims"])
            if not confirmed:
                item["status"] = "suspected"
                item["confirmation_note"] = "Insufficient evidence for the requested confirmation; retain as an unresolved review question"
                issues.append("finding_confirmation_unverified")
        checked_findings.append(item)
        if item["severity"] == "critical":
            if item["status"] == "confirmed":
                confirmed_critical.append(item["rationale"])
            else:
                suspicious.append("Unconfirmed critical review question: " + item["rationale"])
        elif item["severity"] == "major":
            suspicious.append("Unresolved major review finding: " + item["rationale"])
    if suspicious:
        dimension = quality_rows.get("evidence")
        if isinstance(dimension, dict) and finite(dimension.get("score"), 0, 5):
            adjustments.append({"dimension": "evidence", "submitted": dimension["score"], "applied": None,
                                "reason": "unresolved_major_or_critical_finding"})
            dimension["score"] = None
            quality, qi = assess_axis(guarded, "quality", settings["quality_weights"], indexed, access)
            issues.extend(qi)
    low, high = composite(quality["lower"], match["lower"], settings["quality_weight"]), composite(quality["upper"], match["upper"], settings["quality_weight"])
    complete = quality["score"] is not None and match["score"] is not None and reviewed and not issues and not suspicious
    content_block = ("confirmed_core_flaw" if confirmed_critical else
                     claim_audit["status"] if claim_audit["status"] in {"unsupported_core_claim", "contradicted_core_claim"} else None)
    total = low if complete and not content_block else None
    pending_gates = [c["field"] for c in (record.get("filter") or {}).get("checks", []) if c.get("matched") is None and c["field"] != "topic_match"]
    if record.get("metadata_conflicts"):
        pending_gates.append("metadata_identity")
    if (record.get("filter") or {}).get("decision") == "needs_verification" and not (record.get("filter") or {}).get("checks"):
        pending_gates.append("unspecified_filter_gate")
    # A venue conflict matters when the user requested a venue gate, or when
    # paper identity itself is conflicting. Missing IF by itself is no gate.
    reasons = []
    if (record.get("filter") or {}).get("decision") == "exclude":
        status = "excluded_filter"
        reasons.extend((record.get("filter") or {}).get("reasons", []))
    elif "fail" in concepts.values() or "fail" in constraints.values():
        status = "excluded_scope"
        reasons.extend("Unsatisfied requirement: " + key for key, value in {**concepts, **constraints}.items() if value == "fail")
    elif confirmed_critical:
        status = "excluded_core_flaw"
        reasons.extend(confirmed_critical)
    elif claim_audit["status"] == "contradicted_core_claim":
        status = "excluded_core_flaw"
        reasons.append("A central claim contradicts the checked evidence; see the claim audit and focused verification")
    elif claim_audit["status"] == "unsupported_core_claim":
        status = "below_quality_floor"
        reasons.append("A central claim lacks support after focused verification; this does not establish fabrication or an incorrect method")
    elif pending_gates:
        status = "needs_verification"
        reasons.append("Unresolved explicit gates: " + ", ".join(sorted(set(pending_gates))))
    elif suspicious:
        status = "needs_expert_review"
        reasons.extend(suspicious)
    elif claim_audit["status"] == "needs_expert_review":
        status = "needs_expert_review"
        reasons.append("A central claim remains unresolved; a quality recommendation requires further evidence")
    elif complete and not claims_mod.one_of(review.get("review_confidence"), {"medium", "high"}):
        status = "needs_expert_review"
        reasons.append("Reviewer confidence is low or missing despite complete scores")
    elif not complete or "unknown" in concepts.values() or "unknown" in constraints.values():
        status = "needs_content_review"
        reasons.append("Missing or unusable content/prompt evidence; bounds are uncertainty, not confidence intervals")
        reasons.extend("Unknown requirement: " + key for key, value in {**concepts, **constraints}.items() if value == "unknown")
    elif any(quality["dimensions"][key]["score"] < settings["critical_dimension_floor"] for key in ("rigor", "evidence")):
        status = "below_quality_floor"
        reasons.append("Core rigor/evidence dimension fails the minimum")
    elif quality["score"] < settings["quality_floor"]:
        status = "below_quality_floor"
        reasons.append("Content quality below minimum")
    elif match["score"] < settings["match_floor"]:
        status = "below_match_floor"
        reasons.append("Prompt fit below minimum")
    elif total >= settings["must_read_threshold"]:
        status = "shortlist" if claim_audit["status"] == "qualified" else "must_read"
    elif total >= settings["shortlist_threshold"]:
        status = "shortlist"
    elif total >= settings["watchlist_threshold"]:
        status = "watchlist"
    else:
        status = "below_priority_threshold"
    if claim_audit["status"] == "qualified":
        reasons.append("Claim wording exceeds the checked support; use the bounded conclusions, with evidence capped at 3/5 and recommendation at most shortlist")
    confidence = review.get("review_confidence") if claims_mod.one_of(review.get("review_confidence"), {"low", "medium", "high"}) else "low"
    if not complete or pending_gates or suspicious:
        confidence = "low"
    elif claim_audit["status"] == "qualified" and confidence == "high":
        confidence = "medium"
    result["assessment"] = {"model_version": VERSION, "settings_hash": digest(settings), "request_fingerprint": digest(request(profile)),
        "quality": quality, "match": match, "composite": {"score": total, "lower": low, "upper": high,
            "quality_weight": settings["quality_weight"], "formula": "Q^alpha * M^(1-alpha)", "blocked_by": content_block},
        "status": status, "confidence": confidence, "reviewer": reviewer, "access": access, "issues": sorted(set(issues)),
        "concept_checks": concepts, "constraint_checks": constraints, "reasons": reasons,
        "reading_reason": statements["reading_reason"], "strengths": statements["strengths"],
        "limitations": statements["limitations"], "findings": checked_findings, "claim_audit": claim_audit,
        "evidence": list(indexed.values()), "author_venue_policy": "context_only_zero_points",
        "scored_at": datetime.now(timezone.utc).isoformat()}
    return result


def display_score(axis):
    if axis.get("blocked_by"):
        return "不计算（核心证据未通过）"
    return str(axis["score"]) if axis["score"] is not None else f"{axis['lower']}–{axis['upper']} 待评"


def esc(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def statement_text(item):
    if not item:
        return "待补充有证据的判断。"
    label = "作者报告" if item["basis"] == "author_report" else "评审判断"
    return (label + "：" + item["text"] + "（主张 " + ", ".join(item["claim_ids"]) +
            "；锚点 " + ", ".join(item["evidence_ids"]) + "）")


def selection_catalog(records, request_fingerprint):
    """Freeze report numbers to exact candidates/versions; never select downloads."""
    items = []
    for number, r in enumerate(records, 1):
        a = r["assessment"]
        items.append({"number": number, "candidate_id": r["id"], "candidate_fingerprint": fingerprint(r),
                      "title": r.get("title"), "doi": r.get("doi"), "url": r.get("url"),
                      "publication_type": r.get("publication_type"), "version": r.get("version"),
                      "preprint": r.get("preprint"), "status": a["status"],
                      "scores": {key: a[axis]["score"] for key, axis in (("Q", "quality"), ("M", "match"), ("S", "composite"))},
                      "reviewed_material": a["access"],
                      "access_status": (r.get("fulltext_access") or {}).get("status", "not_checked")})
    body = {"schema_version": 1, "stage": "awaiting_user_selection",
            "request_fingerprint": request_fingerprint, "items": items}
    return {**body, "catalog_id": digest(body)}


def report(records, summary, profile):
    lines = ["# 关键文献阅读清单", "", "研究问题：" + profile["topic"], "",
             f"内容模型：{VERSION}；Q=质量，M=需求匹配，S=Q^α×M^(1−α)，α={config(profile.get('assessment'))['quality_weight']}。",
             "IF/WoS/期刊分区与作者背景单列，不加到论文内容质量分。上下界是未评维度取 0/5 的敏感性范围，并非统计置信区间。",
             "可读性单列；接受稿的评分只适用于实际读到的稿件，正式版和预印本需要各自的证据。",
             "主张审查区分作者报告、证据支持范围和评审判断；阅读原文不等于独立复现，未发现支持不等于已证伪。",
             "第一步：检索与评估结果。下表编号对应本目录 selection-catalog.json；评分推荐不代表用户已选择下载。",
             "检索覆盖：" + str((summary.get("search_coverage") or {}).get("status", "not_recorded")) +
             "。论文质量评分与检索完整性分开；缺少深度检索日志时不能宣称全面检索已完成。",
             "", "|编号|状态|原始标题|版本/来源|实际阅读材料|获取状态|Q|M|S|置信|主张审查|", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for number, r in enumerate(records, 1):
        a = r["assessment"]
        title = esc(r.get("title"))
        if r.get("url"):
            title = f"[{title}]({r['url']})"
        lines.append("|" + "|".join([str(number), a["status"], title, esc((r.get("preprint") or {}).get("server") or (r.get("venue") or {}).get("name")) + (" v" + str(r["version"]) if r.get("version") else ""),
            esc(a["access"].get("material_version") if a["access"].get("full_text") else "未取得完整阅读证据"),
            "readable_copy_reviewed" if a["access"].get("full_text") else esc((r.get("fulltext_access") or {}).get("status") or "not_checked"),
            display_score(a["quality"]), display_score(a["match"]), display_score(a["composite"]), a["confidence"], a["claim_audit"]["status"]]) + "|")
    lines.extend(["", "## 可推荐阅读", ""])
    for r in records:
        a = r["assessment"]
        if r["id"] not in summary["selected_ids"]:
            continue
        lines.extend(["### " + str(r.get("title")), "", statement_text(a["reading_reason"]), "",
                      "优势：" + "；".join(statement_text(s) for s in a["strengths"]),
                      "局限：" + "；".join(statement_text(s) for s in a["limitations"]),
                      "发表/评审状态：" + str(r.get("peer_review_status") or "unknown"),
                      "实际阅读版本/获取方式：" + str(a["access"].get("material_version")) + " / " + str(a["access"].get("retrieval_method")),
                      "全文来源：" + str(a["access"].get("full_text_source") or "unknown"),
                      "期刊指标：" + esc(json.dumps(r.get("metrics") or {}, ensure_ascii=False)), ""])
        for axis in ("quality", "match"):
            for key, dimension in a[axis]["dimensions"].items():
                lines.append(f"- {axis}.{key} = {dimension['score']}/5：{dimension['rationale']}（锚点 {', '.join(dimension['evidence_ids'])}）")
        lines.append("")
    lines.extend(["## 主张与证据审查", "",
                  "以下是宿主基于所列原文锚点的审查记录，不是独立复现证明或自动科学真伪认证。", ""])
    for number, r in enumerate(records, 1):
        a = r["assessment"]
        audit = a["claim_audit"]
        if not audit["claims"] and not a["findings"]:
            continue
        lines.extend(["### " + str(number) + ". " + str(r.get("title")), "",
                      "主张审查状态：" + audit["status"] + "。"])
        for claim in audit["claims"]:
            lines.extend(["", "- 主张 `" + esc(claim["id"]) + "`（" + claim["role"] + "；" + claim["verdict"] + "）",
                          "  - 作者表述：" + esc(claim["claim"] or "原文引文待核对，不予转述。"),
                          "  - 已核查范围：" + esc(claim["scope"]),
                          "  - 审查后的保守表述：" + (esc(claim["safe_conclusion"]) if claim["verdict"] != "unresolved" else "证据尚不充分，暂不形成确定结论。"),
                          "  - 主张锚点：" + esc(", ".join(claim["claim_evidence_ids"])) +
                          "；支持：" + esc(", ".join(claim.get("supporting_evidence_ids") or [])) +
                          "；限制/反证：" + esc(", ".join(claim.get("counterevidence_ids") or []))])
            verification = claim.get("verification")
            if isinstance(verification, dict):
                lines.append("  - 复核方式：" + esc(verification["method"]) + "；" + esc(verification["rationale"]) +
                             "（锚点 " + esc(", ".join(verification["evidence_ids"])) + "）")
        for finding in a["findings"]:
            label = "待核验评审疑点" if finding["status"] != "confirmed" else "经针对性核对的评审判断"
            lines.append("- " + label + "（" + finding["severity"] + "）：" + esc(finding["rationale"]))
            if finding["status"] == "confirmed":
                check = finding["verification"]
                lines.append("  - 复核：" + esc(check["method"]) + "；" + esc(check["rationale"]) +
                             "（锚点 " + esc(", ".join(check["evidence_ids"])) + "）")
        for adjustment in audit["score_adjustments"]:
            lines.append("- 评分约束：" + adjustment["dimension"] + " " + str(adjustment["submitted"]) +
                         " → " + str(adjustment["applied"]) + "；" + adjustment["reason"])
        used = set()
        for claim in audit["claims"]:
            for field in ("claim_evidence_ids", "supporting_evidence_ids", "counterevidence_ids"):
                used.update(claim.get(field) or [])
            used.update((claim.get("verification") or {}).get("evidence_ids") or [])
        for finding in a["findings"]:
            used.update(finding["evidence_ids"])
            if finding["status"] == "confirmed":
                used.update(finding["verification"]["evidence_ids"])
        for evidence in a["evidence"]:
            if evidence["id"] in used:
                lines.append("- 锚点 `" + esc(evidence["id"]) + "`：" + esc(evidence["source"]) + "；" + esc(evidence["locator"]))
        lines.append("")
    lines.extend(["## 待获取全文（质量未评定）", ""])
    for item in summary["acquisition_queue"]:
        lines.append("- `" + esc(item["candidate_id"]) + "`：M=" + str(item["match_score"] if item["match_score"] is not None else "待评") +
                     "；获取状态=" + item["access_status"] + "；下一步=" + item["next_action"])
    if not summary["acquisition_queue"]:
        lines.append("- 无。")
    lines.extend(["", "## 待评与筛选记录", ""])
    for r in records:
        a = r["assessment"]
        if r["id"] not in summary["selected_ids"]:
            lines.append(f"- {esc(r.get('title'))}：{a['status']}；{esc('；'.join(a['reasons']))}；缺失 Q={','.join(a['quality']['missing_dimensions'])}, M={','.join(a['match']['missing_dimensions'])}")
    lines.extend(["", "## 第二步：选择下载", "",
                  "回复“下载第 1、3 篇”等明确选择，宿主将按本表编号下载对应正文；需要补充材料时另行注明。",
                  "尚未选择时不批量保存 PDF、不导入文献库。已打开全文供评价不等于已下载归档；获取失败按论文逐条报告。",
                  "编号仅属于这份结果；更新检索或评分后请使用对应目录的 selection-catalog.json。", "",
                  "评分是可审计的阅读优先级判断，未经本领域人工标注集校准；脚本检查结构和证据声明，原文锚点及科学结论仍需宿主实际核对。", ""])
    return "\n".join(lines)


def score(records, reviews, profile, output, search_coverage=None):
    output = Path(output)
    names = ("ranked.jsonl", "reviews.used.jsonl", "reading-list.md", "assessment-summary.json", "selection-catalog.json")
    if any((output / name).exists() for name in names):
        raise AssessmentError("Assessment output already exists; use a new directory")
    ids = [r.get("id") for r in records]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise AssessmentError("Candidates need unique nonempty IDs")
    indexed = {}
    for review in reviews:
        key = review.get("candidate_id")
        if key not in ids or key in indexed:
            raise AssessmentError("Unknown or duplicate review candidate_id")
        indexed[key] = review
    ranked = [score_record(r, indexed.get(r["id"]), profile) for r in records]
    order = {"must_read": 0, "shortlist": 1, "watchlist": 2}
    ranked.sort(key=lambda r: (order.get(r["assessment"]["status"], 3),
        -(r["assessment"]["composite"]["score"] or 0), -(r["assessment"]["composite"]["upper"])))
    selected, families = [], set()
    for r in ranked:
        if r["assessment"]["status"] not in {"must_read", "shortlist"}:
            continue
        family = r.get("work_family") or r["id"]
        if family in families:
            r["assessment"]["reasons"].append("Related manifestation already selected; retained separately for version audit")
            continue
        if len(selected) < profile.get("count", 20):
            selected.append(r["id"])
            families.add(family)
    acquisition = [{"candidate_id": r["id"], "match_score": r["assessment"]["match"]["score"],
                    "topic_queue_score": (r.get("preliminary") or {}).get("relevance", 0),
                    "access_status": (r.get("fulltext_access") or {}).get("status", "not_checked"),
                    "next_action": (r.get("fulltext_access") or {}).get("next_action", "resolve_lawful_full_text")}
                   for r in ranked if r["assessment"]["access"].get("full_text") is not True
                   and r["assessment"]["status"] in {"needs_content_review", "needs_verification"}]
    acquisition.sort(key=lambda r: (r["match_score"] is None, -(r["match_score"] or 0), -r["topic_queue_score"]))
    summary = {"model_version": VERSION, "review_schema": REVIEW_SCHEMA, "request_fingerprint": digest(request(profile)), "settings": config(profile.get("assessment")),
        "candidates": len(records), "supplied_reviews": len(reviews), "statuses": dict(Counter(r["assessment"]["status"] for r in ranked)),
        "selected_ids": selected, "unreviewed_ids": [i for i in ids if i not in indexed],
        "acquisition_queue": acquisition,
        "search_coverage": copy.deepcopy(search_coverage) if search_coverage else {"status": "not_recorded"},
        "selection_note": "Up to requested count of passing reviews; never fill with unreviewed or below-floor papers",
        "validation_scope": "Structure, access declarations, material/prompt binding, claim audit declarations, report anchors and deterministic guards; not source entailment or scientific correctness"}
    catalog = selection_catalog(ranked, summary["request_fingerprint"])
    summary["workflow"] = {"stage": 1, "download_status": "awaiting_user_selection",
                           "selection_catalog": names[4], "catalog_id": catalog["catalog_id"],
                           "note": "selected_ids above are reading recommendations, not a download selection"}
    output.mkdir(parents=True, exist_ok=True)
    write_jsonl(output / names[0], ranked)
    write_jsonl(output / names[1], reviews)
    (output / names[2]).write_text(report(ranked, summary, profile), encoding="utf-8")
    (output / names[3]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / names[4]).write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary
