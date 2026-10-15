"""Deep-search planning and evidence-led coverage audit, separate from Q/M/S."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import assessment

DEFAULTS = {"mode": "deep", "citation_hops": 2, "saturation_rounds": 2}
STEPS = {
    "query_expansion": "覆盖对象/任务、不同方法族、同义词/缩写及相邻应用；按每个来源的语法执行。",
    "cross_source": "交叉检索适合领域的独立来源；补查出版社和缺摘要/缺日期的候选。",
    "backward_citations": "从不同方法族的高匹配种子追溯参考文献；区分时间窗外的背景文献。",
    "forward_citations": "追踪种子的后续引用与版本关系，必要时再扩展到第二跳。",
    "identity_probes": "用已核验论文的精确标题/DOI检查漏检，记录补回原因和真实来源。",
    "gap_repair": "补查缺摘要、身份冲突、重要方法分支、授权/分页缺口，并逐项说明未解决部分。",
}


def settings(value=None):
    if value is not None and (not isinstance(value, dict) or set(value) - set(DEFAULTS)):
        raise ValueError("search accepts mode/citation_hops/saturation_rounds only")
    result = {**DEFAULTS, **(value or {})}
    if result["mode"] not in {"deep", "quick"}:
        raise ValueError("search.mode must be deep or explicitly requested quick")
    for name, low, high in (("citation_hops", 1, 3), ("saturation_rounds", 1, 5)):
        if type(result[name]) is not int or not low <= result[name] <= high:
            raise ValueError("Invalid search." + name)
    return result


def write_plan(profile, output, max_pages):
    cfg = settings(profile.get("search"))
    body = {"schema_version": 1, "request_fingerprint": assessment.digest(assessment.request(profile)),
            "settings": cfg, "queries": profile["queries"] or profile.get("synonyms", []), "sources": profile["sources"],
            "report_count": profile["count"], "retrieval_count_limit": None,
            "max_pages_per_query": max_pages, "steps": STEPS,
            "stop_rule": "After planned branches and citation traces, stop on configured consecutive zero-new-eligible rounds; budget/access stops remain partial"}
    plan = {**body, "plan_id": assessment.digest(body)}
    ledger = {"schema_version": 1, "plan_id": plan["plan_id"],
              "steps": {key: {"status": "pending", "summary": "", "evidence": []} for key in STEPS},
              "rounds": [], "unresolved_gaps": [], "stop_reason": None,
              "scope_note": "Host declarations need actual source checks; this template proves no search has happened"}
    output = Path(output)
    for name, value in (("search-plan.json", plan), ("search-ledger.template.json", ledger)):
        path = output / name
        if path.exists():
            raise ValueError("Search evidence already exists; use a new directory")
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"mode": cfg["mode"], "status": "host_deepening_pending", "plan": "search-plan.json",
            "ledger_template": "search-ledger.template.json", "plan_id": plan["plan_id"],
            "report_count": profile["count"], "retrieval_count_limit": None, "max_pages_per_query": max_pages}


def source_coverage(root, discovery):
    rows = []
    for entry in discovery:
        source = entry["source"]
        row = {"source": source, "execution_status": entry["status"], "pages": None, "query_variants": None}
        if str(entry.get("detail") or "").startswith("skipped:"):
            rows.append({**row, "coverage_status": "skipped_by_scope"})
            continue
        path = Path(root) / source / ("search-coverage.json" if source in {"crossref", "openalex"} else "coverage.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            searches = data["queries"]
            row.update(pages=sum(q.get("pages_fetched", q.get("pages", 0)) for q in searches),
                       query_variants=len(searches), coverage_status=data["status"], evidence_file=str(path.relative_to(root)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            row["coverage_status"] = "coverage_file_unavailable"
        rows.append(row)
    return rows


def valid_evidence(row):
    if not isinstance(row, dict) or any(not isinstance(row.get(k), str) or not row[k].strip() for k in ("source", "url", "retrieved_at")):
        return False
    try:
        parsed = urlparse(row["url"])
        timestamp = datetime.fromisoformat(row["retrieved_at"].replace("Z", "+00:00"))
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
                    and timestamp.tzinfo and timestamp <= datetime.now(timezone.utc))
    except (ValueError, TypeError):
        return False


def audit(run_dir, ledger_path, output):
    root, output = Path(run_dir), Path(output)
    if output.exists():
        raise ValueError("Search audit already exists; use a new output file")
    try:
        plan = json.loads((root / "search-plan.json").read_text(encoding="utf-8"))
        summary = json.loads((root / "summary.json").read_text(encoding="utf-8"))
        candidates = assessment.load_jsonl(root / "candidates.jsonl")
        ledger = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
        if ledger.get("schema_version") != 1 or ledger.get("plan_id") != plan["plan_id"]:
            raise ValueError()
        if assessment.digest({k: v for k, v in plan.items() if k != "plan_id"}) != plan["plan_id"]:
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError("Missing, invalid or mismatched search plan/ledger") from None
    issues = []
    steps = ledger.get("steps")
    if not isinstance(steps, dict):
        raise ValueError("Search ledger steps must be an object")
    for key in STEPS:
        row = steps.get(key) or {}
        refs = row.get("evidence") if isinstance(row, dict) else None
        if (not isinstance(row, dict) or row.get("status") != "completed" or not str(row.get("summary") or "").strip()
                or not isinstance(refs, list) or not refs or not all(valid_evidence(r) for r in refs)):
            issues.append("unfinished_or_unanchored:" + key)
        elif key in {"backward_citations", "forward_citations"} and not all(r.get("seed_id") for r in refs):
            issues.append("citation_seed_missing:" + key)
    families = {r["id"]: r.get("work_family") or
                (((r.get("preprint") or {}).get("server", "") + ":" + (r.get("preprint") or {}).get("native_id", ""))
                 if (r.get("preprint") or {}).get("native_id") else r["id"]) for r in candidates}
    rounds, seen, seen_families, counts = ledger.get("rounds"), set(), set(), []
    if not isinstance(rounds, list):
        raise ValueError("Search ledger rounds must be an array")
    for number, row in enumerate(rounds, 1):
        if not isinstance(row, dict):
            raise ValueError("Each search round must be an object")
        queries, ids, refs = row.get("queries"), row.get("new_eligible_ids"), row.get("evidence")
        if (type(row.get("round")) is not int or row["round"] != number or not isinstance(queries, list) or not queries
                or any(not isinstance(q, str) or not q.strip() for q in queries)
                or not isinstance(ids, list) or any(not isinstance(i, str) or not i.strip() for i in ids)
                or len(set(ids)) != len(ids) or seen.intersection(ids)
                or not isinstance(refs, list) or not refs or not all(valid_evidence(r) for r in refs)):
            raise ValueError("Search rounds need sequential numbers, queries, new unique IDs and source evidence")
        seen.update(ids)
        if any(key not in families for key in ids):
            issues.append("new_candidates_not_in_final_run")
        round_families = [families[key] for key in ids if key in families]
        if len(set(round_families)) != len(round_families) or seen_families.intersection(round_families):
            issues.append("related_versions_counted_as_new_papers")
        seen_families.update(round_families)
        counts.append(len(ids))
    required = plan["settings"]["saturation_rounds"]
    if ledger.get("stop_reason") != "saturated" or len(counts) < required or any(counts[-required:]):
        issues.append("search_not_saturated")
    if ledger.get("unresolved_gaps"):
        issues.append("unresolved_host_gaps")
    if summary.get("status") != "ok":
        issues.append("partial_builtin_sources")
    coverage = (summary.get("search_strategy") or {}).get("source_coverage") or []
    if not coverage or any(r.get("coverage_status") not in {"complete_query_coverage", "skipped_by_scope"} for r in coverage):
        issues.append("builtin_query_coverage_unverified")
    if plan["max_pages_per_query"] is not None:
        issues.append("explicit_page_limit")
    if plan["settings"]["mode"] != "deep":
        issues.append("quick_mode")
    result = {"schema_version": 1, "plan_id": plan["plan_id"],
              "status": "declared_plan_completed" if not issues else "partial",
              "issues": issues, "round_new_eligible_counts": counts,
              "built_in_unique_candidates": summary.get("unique_candidates"),
              "source_candidate_records": summary.get("source_candidate_records"),
              "source_coverage": coverage,
              "scope": "Structural audit of host search declarations and run status; not proof of scientific correctness or global recall"}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result
