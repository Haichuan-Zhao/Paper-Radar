"""Conservative claim/evidence checks, not an automated scientific referee.

The host checks source meaning. These guards reject missing, circular or
unqualified declarations and retain the limits of that structural validation.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

CONTENT = {"full_text", "figure", "table"}
ROLES = {"main_conclusion", "novelty", "headline_result", "reproducibility", "other"}
VERDICTS = {"supported", "qualified", "unsupported", "contradicted", "unresolved"}
METHODS = {"cross_check", "recalculation", "proof_check", "reproduction"}
SCOPE = "Host-declared claim checks and source anchors; not proof of completeness, entailment, replication or scientific correctness"


def template():
    return {"coverage": {"status": "pending", "rationale": "", "evidence_ids": [], "checked_at": ""},
            "claims": []}


def text(value):
    return isinstance(value, str) and bool(value.strip())


def one_of(value, allowed):
    return isinstance(value, str) and value in allowed


def references(ids, indexed, kinds=None):
    return (isinstance(ids, list) and bool(ids) and all(isinstance(i, str) and i in indexed for i in ids)
            and len(set(ids)) == len(ids)
            and (kinds is None or any(indexed[i]["kind"] in kinds for i in ids)))


def location(row):
    # Renaming one anchor does not turn it into corroborating evidence.
    return row["source"].strip(), row["locator"].strip()


def separate_evidence(ids, original_ids, indexed):
    original = {location(indexed[i]) for i in original_ids if i in indexed}
    excerpts = {" ".join(indexed[i]["excerpt"].split()) for i in original_ids if i in indexed}
    return any(location(indexed[i]) not in original and " ".join(indexed[i]["excerpt"].split()) not in excerpts for i in ids)


def content_witness(ids, original_ids, indexed, identity_id):
    return (references(ids, indexed, CONTENT) and any(i != identity_id and indexed[i]["kind"] in CONTENT
            and separate_evidence([i], original_ids, indexed) for i in ids))


def focused_verification(item, indexed, original_ids):
    check = item.get("verification")
    return (isinstance(check, dict) and one_of(check.get("method"), METHODS) and text(check.get("rationale"))
            and references(check.get("evidence_ids"), indexed, CONTENT | {"repository", "prior_work"})
            and separate_evidence(check["evidence_ids"], original_ids, indexed))


def validate(audit, indexed, readable, reviewed, identity_id=None):
    issues, claims, caps = [], [], {}
    unresolved, core, qualified = False, None, False
    audit = audit if isinstance(audit, dict) else {}
    coverage = audit.get("coverage")
    covered = False
    if isinstance(coverage, dict):
        try:
            checked = datetime.fromisoformat(coverage.get("checked_at", "").replace("Z", "+00:00"))
            covered = (coverage.get("status") == "complete" and text(coverage.get("rationale"))
                       and references(coverage.get("evidence_ids"), indexed, {"full_text"})
                       and any(i != identity_id and indexed[i]["kind"] == "full_text" for i in coverage["evidence_ids"])
                       and checked.tzinfo is not None and checked <= datetime.now(timezone.utc))
        except (ValueError, TypeError, AttributeError):
            pass
    if not covered or not readable or not reviewed:
        issues.append("claim_audit_coverage_incomplete")
    rows = audit.get("claims")
    if not isinstance(rows, list) or not rows:
        issues.append("claim_audit_claims_missing")
        rows = []
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or not text(row.get("id")) or row["id"] in seen
                or not one_of(row.get("role"), ROLES) or type(row.get("central")) is not bool
                or not one_of(row.get("verdict"), VERDICTS)
                or any(not text(row.get(k)) for k in ("claim", "rationale", "scope", "safe_conclusion"))
                or not references(row.get("claim_evidence_ids"), indexed, CONTENT | {"abstract"})
                or any(indexed[i]["kind"] not in CONTENT | {"abstract"} for i in row["claim_evidence_ids"])):
            issues.append("invalid_claim_audit_entry")
            continue
        seen.add(row["id"])
        item = copy.deepcopy(row)
        key = item["id"]
        quoted = " ".join(item["claim"].split())
        if not any(quoted in " ".join(indexed[i]["excerpt"].split()) for i in item["claim_evidence_ids"]):
            issues.append("claim_quote_mismatch:" + key)
            item["claim"] = ""
            item["verdict"] = "unresolved"
        support, counter = item.get("supporting_evidence_ids"), item.get("counterevidence_ids")
        valid_lists = all(isinstance(ids, list) and (not ids or references(ids, indexed)) for ids in (support, counter))
        verdict = item["verdict"]
        usable = valid_lists
        if verdict in {"supported", "qualified"}:
            usable = usable and content_witness(support, item["claim_evidence_ids"], indexed, identity_id)
            if item["role"] == "novelty":
                usable = usable and references(support, indexed, {"prior_work"})
            if item["role"] == "reproducibility":
                usable = (usable and focused_verification(item, indexed, item["claim_evidence_ids"] + support)
                          and item["verification"]["method"] == "reproduction")
        if verdict in {"qualified", "unsupported", "contradicted"}:
            usable = usable and content_witness(counter, item["claim_evidence_ids"], indexed, identity_id)
        if verdict in {"unsupported", "contradicted"}:
            usable = usable and focused_verification(item, indexed, item["claim_evidence_ids"] + (counter or []))
        if not usable or not readable or not reviewed:
            issues.append("claim_evidence_or_verification_incomplete:" + key)
            item["verdict"] = "unresolved"
        for field in ("supporting_evidence_ids", "counterevidence_ids"):
            if item.get(field) and not references(item[field], indexed):
                item[field] = []
        if "verification" in item:
            check = item["verification"]
            if (not isinstance(check, dict) or not one_of(check.get("method"), METHODS)
                    or not text(check.get("rationale")) or not references(check.get("evidence_ids"), indexed)):
                issues.append("invalid_claim_verification:" + key)
                item.pop("verification")
        if item["verdict"] in {"qualified", "unsupported", "contradicted"}:
            qualified = True
            caps["evidence"] = min(caps.get("evidence", 5), 3)
        if item["central"]:
            if item["verdict"] == "unresolved":
                unresolved = unresolved or bool(readable and reviewed)
            elif item["verdict"] == "qualified":
                qualified = True
            elif item["verdict"] in {"unsupported", "contradicted"}:
                if item["verdict"] == "contradicted" or core is None:
                    core = item["verdict"]
                caps["evidence"] = min(caps.get("evidence", 5), 2)
        claims.append(item)
    if not any(c["central"] and c["role"] == "main_conclusion" for c in claims):
        issues.append("central_conclusion_not_audited")
    status = ("needs_expert_review" if unresolved else "pending" if issues else
              "contradicted_core_claim" if core == "contradicted" else
              "unsupported_core_claim" if core else "qualified" if qualified else "completed")
    return {"status": status, "coverage": copy.deepcopy(coverage) if isinstance(coverage, dict) else {},
            "claims": claims, "issues": sorted(set(issues)), "quality_caps": caps,
            "quality_pending": bool(issues or unresolved), "scope": SCOPE}


def statements(review, indexed, claims):
    """Do not publish unattached free-form praise, criticism or reading reasons."""
    result, issues = {}, []
    claim_ids = {c["id"] for c in claims}
    supported_ids = {c["id"] for c in claims if c["verdict"] in {"supported", "qualified"}}
    for name in ("strengths", "limitations", "reading_reason"):
        rows = review.get(name) if name != "reading_reason" else [review.get(name)]
        parsed = []
        if not isinstance(rows, list) or not rows:
            issues.append("missing_report_statement:" + name)
            rows = []
        for row in rows:
            links = row.get("claim_ids") if isinstance(row, dict) else None
            valid = (isinstance(row, dict) and text(row.get("text"))
                     and one_of(row.get("basis"), {"author_report", "reviewer_assessment"})
                     and references(row.get("evidence_ids"), indexed, CONTENT | {"abstract"})
                     and isinstance(links, list) and bool(links)
                     and all(isinstance(i, str) and i in claim_ids for i in links)
                     and len(set(links)) == len(links))
            if name == "reading_reason":
                valid = valid and references(row.get("evidence_ids"), indexed, {"user_prompt"})
            if name in {"strengths", "reading_reason"}:
                valid = valid and all(i in supported_ids for i in links)
            if not valid:
                issues.append("unanchored_report_statement:" + name)
                continue
            parsed.append(copy.deepcopy(row))
        result[name] = (parsed[0] if parsed else {}) if name == "reading_reason" else parsed
    return result, issues
