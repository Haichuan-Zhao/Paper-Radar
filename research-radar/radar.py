#!/usr/bin/env python3
"""Unified Research Radar driver.

One command turns a single profile file (topic + filters/switches + automation)
into an auditable, reproducible literature run:

    python3 radar.py run --profile radar-profile.json [--out runs/...] [--notify]

Pipeline: public journal/preprint discovery -> identity/versions -> journal
context and explicit filters -> content review packets -> host LLM assessment
-> deterministic quality/fit priority. Retrieval alone produces a review queue.
"""
from __future__ import annotations

import argparse
import json
import copy
import os
import re
import subprocess
import sys
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import config as config_mod          # noqa: E402
import easyscholar as easyscholar_mod  # noqa: E402
import filters as filters_mod        # noqa: E402
import venue_table as venue_mod      # noqa: E402
import relevance as relevance_mod    # noqa: E402
import assessment as assessment_mod  # noqa: E402
import calibrate_assessments as calibration_mod  # noqa: E402
import fulltext_access as access_mod  # noqa: E402
import selection as selection_mod    # noqa: E402
import preflight as preflight_mod    # noqa: E402
import search_strategy as search_mod  # noqa: E402
from credentials import CredentialError, redact, resolve_key  # noqa: E402
from identifiers import compare_venues, normalize_title, issns  # noqa: E402
from discover_papers import doi as normalize_doi, identity as paper_identity  # noqa: E402

DISCOVER_SCRIPTS = {
    "crossref": "discover_papers.py",
    "openalex": "discover_openalex.py",
    "arxiv": "discover_preprints.py",
    "biorxiv": "discover_preprints.py",
    "medrxiv": "discover_preprints.py",
}
DEFAULT_TYPES = ["journal-article", "proceedings-article", "preprint"]


# --------------------------------------------------------------------------- #
# Small deterministic helpers
# --------------------------------------------------------------------------- #

def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = re.sub(r"[^a-z0-9]+", "-", ascii_text.casefold()).strip("-")
    return ascii_text[:40] or "topic"


def _first_date(record: dict[str, Any]) -> str | None:
    membership = (record.get("discovery") or {}).get("date_membership") or {}
    value = str(membership.get("value") or "")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    for key in ("published_online", "published", "issued", "published_print"):
        value = record.get(key)
        if value and re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(value)[:10]):
            return str(value)[:10]
    return None


def _verified_metric_value(record: dict[str, Any], key: str) -> Any:
    metrics = record.get("metrics")
    if not isinstance(metrics, dict):
        return None
    obj = metrics.get(key)
    if (isinstance(obj, dict) and obj.get("verified") is True
            and not obj.get("conflict") and obj.get("identity_verified") is not False):
        return obj.get("value")
    return None


def _relevance_points(record: dict[str, Any], profile: dict[str, Any]) -> float:
    groups = (record.get("topic_match") or {}).get("groups") or []
    if groups:
        matched = sum(bool(g.get("matched")) for g in groups)
        title_hits = sum(any(h.get("field") == "title" for h in g.get("hits", [])) for g in groups)
        return round(40 * matched / len(groups) + 10 * title_hits / len(groups), 2)
    tokens: set[str] = set()
    for phrase in list(profile["queries"]) + list(profile["synonyms"]) + ([profile["topic_en"]] if profile.get("topic_en") else []):
        for token in re.findall(r"[a-z0-9\u4e00-\u9fff]{3,}", (phrase or "").casefold()):
            tokens.add(token)
    if not tokens:
        return 0.0
    title = (record.get("title") or "").casefold()
    abstract = (record.get("abstract") or "").casefold()
    hits = 0
    for token in tokens:
        if token in title:
            hits += 3
        if token in abstract:
            hits += 1
    return round(min(50.0, hits * 4.0), 2)


def _recency_points(record: dict[str, Any], end: date) -> float:
    published = _first_date(record)
    if not published:
        return 0.0
    try:
        days = (end - date.fromisoformat(published)).days
    except ValueError:
        return 0.0
    if days < 0:
        return 0.0
    return round(max(0.0, 10.0 - days / 9.0), 2)


def _preliminary_score(record: dict[str, Any], profile: dict[str, Any], end: date) -> dict[str, Any]:
    relevance = _relevance_points(record, profile)
    recency = _recency_points(record, end)
    return {
        "relevance": relevance,
        "recency": recency,
        "total": round(relevance + recency, 2),
        "purpose": "content_review_queue_not_paper_quality",
    }


# --------------------------------------------------------------------------- #
# Discovery and merge
# --------------------------------------------------------------------------- #

def _run_discovery(script: str, profile: dict[str, Any], types: list[str], out_dir: Path, max_pages: int | None) -> dict[str, Any]:
    date_cfg = profile["date"]
    cmd = [sys.executable, str(SCRIPT_DIR / script)]
    source = out_dir.name
    if script == "discover_preprints.py":
        cmd += ["--server", source]
        for category in (profile.get("preprints") or {}).get(source + "_categories", []):
            cmd += ["--category", category]
    queries = ((profile.get("preprints") or {}).get("arxiv_queries") if source == "arxiv" else None) or config_mod.expand_queries(profile)
    for query in queries:
        cmd += ["--query", query]
    cmd += ["--date-from", date_cfg["from"], "--date-to", date_cfg["to"], "--date-field", date_cfg["basis"]]
    kinds = types
    if script == "discover_papers.py":
        kind_map = {"conference-paper": "proceedings-article", "preprint": "posted-content", "review": "journal-article"}
        kinds = list(dict.fromkeys(kind_map.get(kind, kind) for kind in types))
    for kind in kinds:
        cmd += ["--type", kind]
    for identifier in profile.get("journal_issns", []):
        cmd += ["--issn", identifier]
    cmd += ["--output-dir", str(out_dir)]
    if max_pages:
        cmd += ["--max-pages", str(max_pages)]
    child_env = os.environ.copy()
    if script == "discover_openalex.py":
        key = resolve_key(profile.get("openalex") or {}, "openalex")
        # Set only the child environment; keys never enter command-line args.
        if key:
            child_env["OPENALEX_API_KEY"] = key
        else:
            child_env.pop("OPENALEX_API_KEY", None)
    result = subprocess.run(cmd, capture_output=True, text=True, env=child_env)
    status = "complete" if result.returncode == 0 else "partial" if result.returncode == 2 else "failed"
    detail = (result.stdout or "").strip().splitlines()
    return {"source": out_dir.name, "script": script, "exit": result.returncode, "status": status, "detail": detail[-1] if detail else "", "stderr": (result.stderr or "").strip()[-500:]}


def _merge_records(candidate_files: list[Path]) -> tuple[list[dict[str, Any]], int]:
    merged: dict[str, dict[str, Any]] = {}
    raw = 0
    for path in candidate_files:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw += 1
            normalized_doi = normalize_doi(record.get("doi"))
            record["doi"] = normalized_doi
            if record.get("publication_type") == "preprint":
                key = record.get("id") if record.get("preprint") else "preprint:" + (normalized_doi or record.get("id") or paper_identity(record))
            else:
                key = "doi:" + normalized_doi if normalized_doi else record.get("id") or paper_identity(record)
            snapshot = {field: copy.deepcopy(record.get(field)) for field in
                        ("id", "title", "doi", "authors", "venue", "published", "published_online", "published_print", "issued", "provenance", "version", "preprint", "relations")}
            if key in merged:
                previous = merged[key]
                previous.setdefault("source_records", []).append(snapshot)
                comparison = compare_venues(previous.get("venue") or {}, record.get("venue") or {})
                if comparison["status"] == "conflict":
                    previous.setdefault("metadata_conflicts", []).append({"field": "venue", **comparison})
                elif comparison["status"] == "matched":
                    previous["venue"]["issn"] = sorted(issns(previous["venue"]) | issns(record.get("venue") or {}))
                elif not previous.get("venue", {}).get("name") and record.get("venue"):
                    previous["venue"] = copy.deepcopy(record["venue"])
                if normalize_title(previous.get("title")) != normalize_title(record.get("title")):
                    previous.setdefault("metadata_conflicts", []).append({"field": "title", "values": [previous.get("title"), record.get("title")]})
                if record.get("provenance"):
                    previous.setdefault("provenance", [])
                    previous["provenance"].extend(record["provenance"])
                if not previous.get("abstract") and record.get("abstract"):
                    previous["abstract"] = record["abstract"]
                    previous.setdefault("field_provenance", {})["abstract"] = copy.deepcopy(record.get("provenance", []))
                for link in record.get("full_text_urls", []):
                    if link not in previous.setdefault("full_text_urls", []):
                        previous["full_text_urls"].append(link)
            else:
                record["id"] = key
                record["source_records"] = [snapshot]
                record["field_provenance"] = {field: copy.deepcopy(record.get("provenance", []))
                                              for field in ("title", "venue", "abstract") if record.get(field)}
                merged[key] = record
    records = list(merged.values())
    _link_manifestations(records)
    return records, raw


def _link_manifestations(records):
    """Group versions using native IDs/DOIs/explicit publisher relations only.

    Never infer a preprint/journal relationship from title similarity. Versions
    remain independent review targets, even when they belong to one work.
    """
    parent = {}
    def root(key):
        parent.setdefault(key, key)
        path = []
        while parent[key] != key:
            path.append(key)
            key = parent[key]
        for previous in path:
            parent[previous] = key
        return key
    def union(a, b):
        left, right = root(a), root(b)
        parent[max(left, right)] = min(left, right)
    for record in records:
        key = record["id"]
        root(key)
        if record.get("doi"):
            union(key, "work-doi:" + record["doi"])
            arxiv = re.fullmatch(r"10\.48550/arxiv\.(.+)", record["doi"], re.I)
            if arxiv:
                union(key, "work-arxiv:" + re.sub(r"v\d+$", "", arxiv.group(1)))
        preprint = record.get("preprint") or {}
        if preprint.get("server") and preprint.get("native_id"):
            union(key, "work-" + preprint["server"] + ":" + preprint["native_id"])
        for relation in record.get("relations", []):
            target = normalize_doi(relation.get("doi"))
            if relation.get("type") == "published_version" and target:
                union(key, "work-doi:" + target)
    groups = {}
    for record in records:
        record["work_family"] = root(record["id"])
        groups.setdefault(record["work_family"], []).append(record["id"])
    for record in records:
        record["related_candidate_ids"] = [key for key in groups[record["work_family"]] if key != record["id"]]


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #

def _md_escape(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", " ")


def _display_metric(record: dict[str, Any], key: str) -> str:
    obj = (record.get("metrics") or {}).get(key) or {}
    value = obj.get("value")
    if value is None:
        return "-"
    metrics = record.get("metrics") or {}
    year = (metrics.get(key) or {}).get("year") or (metrics.get(key) or {}).get("edition")
    return f"{value}" + (f" ({year})" if year else " (年份未知)") + (" · 待核验" if _verified_metric_value(record, key) is None else "")


def _display_date(record: dict[str, Any]) -> str:
    membership = (record.get("discovery") or {}).get("date_membership") or {}
    value = membership.get("value") or _first_date(record) or "未知"
    field = membership.get("field")
    return f"{value}" + (f" ({membership.get('basis') or field}{'; fallback' if membership.get('fallback_used') else ''})" if field else "")


def _build_report(profile: dict[str, Any], kept: list[dict[str, Any]], pending: list[dict[str, Any]],
                  excluded: list[dict[str, Any]], counts: dict[str, int], discovery: list[dict[str, Any]],
                  end: date) -> str:
    include = profile["filters"]["include_only"]
    switches = []
    for field, label in (("wos_indexes", "WOS 索引"), ("cas_partitions", "中科院分区"), ("jcr_quartiles", "JCR 分区"), ("ccf_ranks", "CCF 等级"), ("types", "文献类型")):
        if include.get(field):
            switches.append(f"{label}={include[field]}")
    if include.get("min_jif") is not None:
        switches.append(f"JIF≥{include['min_jif']}")
    if include.get("open_access_only"):
        switches.append("仅开放获取")
    if include.get("peer_reviewed_only"):
        switches.append("仅同行评审")

    lines = [
        "# Research Radar 报告",
        "",
        f"- 主题：{profile['topic']}" + (f"（{profile['topic_en']}）" if profile.get("topic_en") else ""),
        f"- 时间窗：{profile['date']['from']} — {profile['date']['to']}（依据 {profile['date']['basis']}）",
        f"- 检索词：{', '.join(config_mod.expand_queries(profile)) or '-'}",
        f"- 开启的过滤开关：{', '.join(switches) or '无（默认仅排除非研究类文献）'}",
        f"- 候选总数：{counts['keep'] + counts['needs_verification'] + counts['exclude']}（保留 {counts['keep']}，需核验 {counts['needs_verification']}，排除 {counts['exclude']}）",
        "",
        "> 本表为**内容复核队列**（关键词相关性 + 时效），不等同于论文质量结论。期刊级别单列；全文/图表评估完成后用质量 Q 与匹配 M 计算综合分 S。",
        "",
        "## 保留候选（按初排分数）",
        "",
        "| 排名 | 标题 | 期刊/会议/预印本 | 日期依据 | IF | JCR | CAS | CCF | WoS 索引 | 主题命中 | 队列分(相关/时效) |",
        "|---|---|---|---|---|---|---|---|---|---|---:|",
    ]
    top = int(profile["count"])
    for index, record in enumerate(kept[:top], 1):
        venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
        score = record.get("preliminary", {})
        doi = record.get("doi")
        title = record.get("title") or "(无标题)"
        if doi:
            title = f"[{_md_escape(title)}](https://doi.org/{doi})"
        else:
            title = f"[{_md_escape(title)}]({record['url']})" if record.get("url") else _md_escape(title)
        lines.append(
            f"| {index} | {title} | {_md_escape(venue.get('name') or '-')} | {_md_escape(_display_date(record))} "
            f"| {_md_escape(_display_metric(record, 'jif'))} | {_md_escape(_display_metric(record, 'jcr_quartile'))} "
            f"| {_md_escape(_display_metric(record, 'cas_partition'))} | {_md_escape(_display_metric(record, 'ccf_rank'))} "
            f"| {_md_escape(_display_metric(record, 'wos_indexes'))} "
            f"| {'概念命中' if (record.get('topic_match') or {}).get('status') == 'matched' else '未设概念组'} | {score.get('total', 0):.2f} "
            f"({score.get('relevance', 0):g}/{score.get('recency', 0):g}) |"
        )

    lines.extend(["", "## 需核验（主题、期刊身份、日期或指标）", ""])
    if pending:
        for record in pending[:50]:
            observed = "; ".join(f"{key}={_display_metric(record, key)}" for key in ("jif", "jcr_quartile", "cas_partition", "wos_indexes") if (record.get("metrics") or {}).get(key))
            lines.append(f"- `{_md_escape(record.get('id') or record.get('title'))}` — {_md_escape(record.get('title'))} — {_md_escape('；'.join((record.get('filter') or {}).get('reasons', [])))}" + (f" — {_md_escape(observed)}" if observed else ""))
    else:
        lines.append("- 无。")

    lines.extend(["", "## 被开关排除", ""])
    if excluded:
        for record in excluded[:50]:
            lines.append(f"- `{_md_escape(record.get('id') or record.get('title'))}` — {_md_escape(record.get('title'))} — {_md_escape('；'.join((record.get('filter') or {}).get('reasons', [])))}")
    else:
        lines.append("- 无。")

    lines.extend(["", "## 来源覆盖", ""])
    for item in discovery:
        lines.append(f"- `{item['source']}`: {item['status']} (exit {item['exit']}) {item['detail']}")
    if not profile.get("queries"):
        lines.append("- 当前仅配置同义词，查询可能过宽；请补充完整领域检索式。")
    lines.append("- 来源分页耗尽仅表示声明的检索式已执行；不代表覆盖了所有相关文献。")
    lines.append("- 当前为第一步的检索队列；宿主完成证据评审并执行 assess 后交付编号、Q/M/S 及下载选择入口。用户选择后才进行第二步下载。")
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Run command
# --------------------------------------------------------------------------- #

def run(profile: dict[str, Any], out_dir: Path, max_pages: int | None, do_notify: bool,
        continue_with_gaps: bool = False) -> int:
    started_at = datetime.now(timezone.utc).isoformat()
    if max_pages is not None and (type(max_pages) is not int or max_pages < 1):
        raise ValueError("max-pages must be a positive integer")
    readiness = preflight_mod.check(profile, max_pages)
    if readiness["gaps"] and continue_with_gaps is not True:
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 3
    if readiness["gaps"]:
        readiness["decision"] = "continue_with_disclosed_gaps"
        profile = preflight_mod.effective_profile(profile, readiness)
    if any((out_dir / name).exists() for name in ("summary.json", "candidates.jsonl", "preflight.json", "search-plan.json", *DISCOVER_SCRIPTS)):
        raise ValueError("Run directory already contains evidence; choose a new --out directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "preflight.json").write_text(json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    search_plan = search_mod.write_plan(profile, out_dir, max_pages)
    types = profile["filters"]["include_only"].get("types") or DEFAULT_TYPES

    discovery: list[dict[str, Any]] = []
    candidate_files: list[Path] = []
    for source, script in DISCOVER_SCRIPTS.items():
        if source not in profile.get("sources", DISCOVER_SCRIPTS):
            continue
        sub = out_dir / source
        if script == "discover_preprints.py" and ("preprint" not in types or profile.get("journal_issns")):
            discovery.append({"source": source, "script": script, "exit": 0, "status": "complete", "detail": "skipped: publication types or explicit journal scope do not include repository preprints", "stderr": ""})
            continue
        try:
            result = _run_discovery(script, profile, types, sub, max_pages)
        except FileNotFoundError as exc:
            result = {"source": source, "script": script, "exit": -1, "status": "failed", "detail": f"script missing: {exc}", "stderr": ""}
        discovery.append(result)
        candidate_files.append(sub / "candidates.jsonl")

    search_plan["source_coverage"] = search_mod.source_coverage(out_dir, discovery)
    records, raw = _merge_records(candidate_files)
    topic_report = relevance_mod.apply(records, profile.get("relevance") or {})
    scope = set(profile.get("journal_issns", []))
    if scope:
        for record in records:
            actual = issns(record.get("venue") or {})
            record["journal_scope_match"] = {"status": "matched" if scope & actual else
                "needs_verification" if not actual or record.get("metadata_conflicts") else "outside_scope",
                "requested_issns": sorted(scope), "actual_issns": sorted(actual)}

    if profile["venue_metrics_files"]:
        table = venue_mod.load_venue_tables(profile["venue_metrics_files"])
        match_report = table.apply(records)
    else:
        match_report = {"matched": 0, "unmatched": len(records), "total_rows": 0}

    # Optional live venue-metric enrichment from EasyScholar (key from env/config).
    es_config = profile.get("easyscholar") or {}
    es_report: dict[str, Any] = {"enabled": False}
    if es_config.get("enabled"):
        secret_key = easyscholar_mod.resolve_secret_key(es_config)
        if not secret_key:
            es_report = {"enabled": True, "skipped": "no_secret_key", "hint": f"set {es_config.get('secret_key_env')}"}
        else:
            cache_path = Path(es_config["cache_file"]) if es_config.get("cache_file") else (out_dir / "easyscholar-cache.jsonl")
            es_report = easyscholar_mod.enrich(
                records, secret_key, cache_path,
                pause=float(es_config.get("pause", 1.0)), timeout=float(es_config.get("timeout", 15.0)),
                cache_ttl_hours=es_config.get("cache_ttl_hours", 168), dataset_versions=es_config.get("dataset_versions"),
            )
            es_report["enabled"] = True

    counts = filters_mod.apply_filters(records, profile["filters"])
    kept, pending, excluded = filters_mod.partition(records)

    end = date.fromisoformat(profile["date"]["to"])
    for record in kept + pending:
        record["preliminary"] = _preliminary_score(record, profile, end)
    kept.sort(key=lambda r: r["preliminary"]["total"], reverse=True)

    access_rows, access_summary = access_mod.resolve(records, profile, assessment_mod.fingerprint)
    access_mod.write(out_dir / "access", access_rows, access_summary, records, assessment_mod.fingerprint)
    access_by_id = {row["candidate_id"]: row for row in access_rows}
    for record in records:
        record["fulltext_access"] = access_by_id[record["id"]]

    # Persist machine-readable artifacts.
    (out_dir / "candidates.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records) + "\n", encoding="utf-8")
    (out_dir / "excluded.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in excluded) + "\n", encoding="utf-8")

    report = _build_report(profile, kept, pending, excluded, counts, discovery, end)
    report += "\n## 运行前检查与检索深度\n\n"
    report += "- 配置检查：" + readiness["decision"] + "；缺口：" + (", ".join(readiness["gaps"]) or "无本地配置缺口") + "。\n"
    report += "- 当前完成内置来源检索；深度检索还需执行 search-plan.json 中的扩词、引用追踪和缺口补查，并填写检索日志。\n"
    report += "- 推荐篇数为展示/阅读目标，不限制检索候选数量；未经检索日志核验不宣称检索已全面完成。\n"
    for row in search_plan["source_coverage"]:
        variants = row["query_variants"] if row["query_variants"] is not None else "未核验"
        pages = row["pages"] if row["pages"] is not None else "未核验"
        report += f"- {row['source']}：{variants} 个查询变体，{pages} 页；{row['coverage_status']}。\n"
    (out_dir / "report.md").write_text(report, encoding="utf-8")

    top_n = int(profile["count"])
    summary = {
        "run_dir": str(out_dir),
        "profile": profile["_source_path"],
        "topic": profile["topic"],
        "date_window": [profile["date"]["from"], profile["date"]["to"]],
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "ok" if all(d["status"] == "complete" for d in discovery) else "partial",
        "raw_records": raw,
        "source_candidate_records": raw,
        "duplicates_merged": raw - len(records),
        "unique_candidates": len(records),
        "counts": {"kept": counts["keep"], "needs_verification": counts["needs_verification"], "excluded": counts["exclude"]},
        "venue_matched": match_report["matched"],
        "venue_matching": match_report,
        "topic_matching": topic_report,
        "easyscholar": es_report,
        "preflight": {"decision": readiness["decision"], "gaps": readiness["gaps"], "report": "preflight.json"},
        "search_strategy": search_plan,
        "fulltext_access": access_summary,
        "shortlist": [],
        "review_queue": [
            {"id": r.get("id"), "title": r.get("title"), "doi": r.get("doi"), "url": r.get("url"),
             "total": r.get("preliminary", {}).get("total"), "status": "kept"}
            for r in kept[:top_n]
        ],
        "needs_verification": [
            {"id": r.get("id"), "title": r.get("title"), "reasons": (r.get("filter") or {}).get("reasons", [])}
            for r in pending[:top_n]
        ],
        "errors": [d for d in discovery if d["status"] != "complete"],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "profile.json").write_text(json.dumps(redact(profile), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_manifest = assessment_mod.prepare(records, profile, out_dir / "review")
    summary["content_assessment"] = {"status": "awaiting_host_review", "packet": str(out_dir / "review" / "review-packet.jsonl"),
        "prepared": review_manifest["prepared"], "unreviewed": len(review_manifest["unreviewed_ids"])}
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / "matching-audit.jsonl").write_text("".join(json.dumps({"id": r.get("id"), "topic_match": r.get("topic_match"),
        "venue_matches": r.get("venue_matches", []), "metadata_conflicts": r.get("metadata_conflicts", [])}, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")

    print(json.dumps({
        "run_dir": str(out_dir),
        "unique_candidates": len(records),
        "counts": counts,
        "venue_matched": match_report["matched"],
        "report": str(out_dir / "report.md"),
    }, ensure_ascii=False))

    if do_notify or profile["automation"]["enabled"]:
        _notify(summary, profile, out_dir)
    return 0 if summary["status"] == "ok" else 2


def _notify(summary: dict[str, Any], profile: dict[str, Any], out_dir: Path) -> None:
    notify_script = SCRIPT_DIR / "notify.py"
    if not notify_script.exists():
        return
    summary_path = out_dir / "summary.json"
    cmd = [sys.executable, str(notify_script), "--summary", str(summary_path), "--config", profile["_source_path"], "--run-dir", str(out_dir)]
    subprocess.run(cmd, capture_output=True, text=True)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    sub = result.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Stage 1: discover/filter and prepare host review; no batch downloads")
    run_p.add_argument("--profile", required=True, help="Path to the user's Markdown configuration document or JSON profile")
    run_p.add_argument("--out", help="Run output directory (default: runs/<ts>-<topic>)")
    run_p.add_argument("--max-pages", type=int, help="Per-source page cap for a quick smoke test")
    run_p.add_argument("--notify", action="store_true", help="Send notifications even if automation.enabled is false")
    run_p.add_argument("--continue-with-gaps", action="store_true", help="Use only after the user explicitly chooses to continue with disclosed configuration gaps")

    sub.add_parser("validate", help="Validate a profile and print the normalized config").add_argument("--profile", required=True)
    sub.add_parser("doctor", help="Check runtime and credential configuration without network or key output").add_argument("--profile", required=True)
    sub.add_parser("preflight", help="Check readiness before discovery; exit 3 requires a user choice, no network requests").add_argument("--profile", required=True)
    audit_p = sub.add_parser("audit-search", help="Audit the host's deep-search ledger against this run's plan")
    audit_p.add_argument("--run", required=True)
    audit_p.add_argument("--ledger", required=True)
    audit_p.add_argument("--out", required=True, help="New search-audit.json file")
    prepare_p = sub.add_parser("prepare-review", help="Prepare blind content packets and structured review templates")
    prepare_p.add_argument("--run", required=True)
    prepare_p.add_argument("--profile", help="Defaults to saved run/profile.json")
    prepare_p.add_argument("--out", required=True, help="New review output directory")
    assess_p = sub.add_parser("assess", help="Validate host LLM reviews and compute quality/fit reading priorities")
    assess_p.add_argument("--run", required=True)
    assess_p.add_argument("--profile", help="Defaults to saved run/profile.json")
    assess_p.add_argument("--reviews", required=True, help="Completed reviews JSONL; empty reviews leave candidates pending")
    assess_p.add_argument("--out", help="Defaults to run/assessment; existing results are never overwritten")
    assess_p.add_argument("--search-audit", help="Bound deep-search audit; defaults to run/search-audit.json if present")
    select_p = sub.add_parser("select", help="Stage 2: plan only the user's chosen papers; the host performs downloads")
    select_p.add_argument("--assessment", required=True, help="Directory containing reading-list.md, ranked.jsonl and selection-catalog.json")
    choices = select_p.add_mutually_exclusive_group(required=True)
    choices.add_argument("--numbers", help="Exact report numbers, e.g. 1,3,5")
    choices.add_argument("--ids", help="Exact comma-separated candidate IDs, including versions")
    select_p.add_argument("--include-si", action="store_true", help="Include supporting information only if the user requested it")
    select_p.add_argument("--out", required=True, help="New directory for the selection plan; PDFs go in its pdfs/ subdirectory")
    for command in (prepare_p, assess_p):
        command.add_argument("--access", help="Optional access-manifest.jsonl from a later access check")
    access_p = sub.add_parser("access", help="Resolve lawful full-text routes and optional actual access observations; no downloads")
    access_p.add_argument("--run", required=True)
    access_p.add_argument("--profile", help="Defaults to saved run/profile.json; may change access configuration")
    access_p.add_argument("--observations", help="Host-filled access observations JSONL")
    access_p.add_argument("--out", required=True, help="New access output directory")
    calibrate_p = sub.add_parser("calibrate", help="Compare rankings with researcher-provided human gold labels")
    calibrate_p.add_argument("--ranked", required=True)
    calibrate_p.add_argument("--gold", required=True)
    calibrate_p.add_argument("--out", required=True)
    calibrate_p.add_argument("--top-k", type=int, default=10)
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv or sys.argv[1:])
    if args.command == "preflight":
        try:
            profile = config_mod.load_profile(args.profile)
            result = preflight_mod.check(profile)
        except (ValueError, OSError):
            print(json.dumps({"status": "blocked", "network_used": False, "credential_values_returned": False,
                              "next_action": "complete_or_fix_the_user_document_then_validate"}))
            return 2
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 3 if result["gaps"] else 0
    if args.command == "audit-search":
        try:
            result = search_mod.audit(args.run, args.ledger, args.out)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == "declared_plan_completed" else 2
        except (OSError, ValueError) as exc:
            print(f"search audit error: {exc}", file=sys.stderr)
            return 2
    if args.command == "select":
        try:
            result = selection_mod.write(args.assessment, args.out, numbers=args.numbers, ids=args.ids, include_si=args.include_si)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError) as exc:
            print(f"selection error: {exc}", file=sys.stderr)
            return 2
    if args.command == "calibrate":
        try:
            print(json.dumps(calibration_mod.run(args.ranked, args.gold, args.out, args.top_k), ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(f"calibration error: {exc}", file=sys.stderr)
            return 2
    if args.command in {"prepare-review", "assess", "access"}:
        try:
            run_dir = Path(args.run)
            profile = config_mod.load_profile(args.profile or run_dir / "profile.json")
            if args.profile and (run_dir / "profile.json").exists():
                original = config_mod.load_profile(run_dir / "profile.json")
                if assessment_mod.digest(assessment_mod.request(original)) != assessment_mod.digest(assessment_mod.request(profile)):
                    raise assessment_mod.AssessmentError("Research request, dates or filters differ from the saved run; create a new run so gates and candidates match. Assessment weights/budget may be changed without a new search")
            records = assessment_mod.load_jsonl(run_dir / "candidates.jsonl")
            if args.command == "access":
                observations = assessment_mod.load_jsonl(args.observations) if args.observations else []
                rows, summary = access_mod.resolve(records, profile, assessment_mod.fingerprint, observations)
                result = access_mod.write(args.out, rows, summary, records, assessment_mod.fingerprint)
            elif args.command == "prepare-review":
                if args.access:
                    assessment_mod.attach_access(records, assessment_mod.load_jsonl(args.access))
                result = assessment_mod.prepare(records, profile, args.out)
            else:
                if args.access:
                    assessment_mod.attach_access(records, assessment_mod.load_jsonl(args.access))
                coverage = {"status": "host_deepening_pending" if (run_dir / "search-plan.json").exists() else "not_recorded"}
                audit_path = Path(args.search_audit) if args.search_audit else run_dir / "search-audit.json"
                if args.search_audit or audit_path.exists():
                    try:
                        coverage = json.loads(audit_path.read_text(encoding="utf-8"))
                        plan = json.loads((run_dir / "search-plan.json").read_text(encoding="utf-8"))
                        if (coverage.get("schema_version") != 1 or coverage.get("plan_id") != plan["plan_id"]
                                or coverage.get("status") not in {"partial", "declared_plan_completed"}
                                or not isinstance(coverage.get("issues"), list)
                                or (coverage["status"] == "declared_plan_completed" and coverage["issues"])):
                            raise ValueError()
                    except (OSError, ValueError, KeyError, TypeError, AttributeError):
                        raise assessment_mod.AssessmentError("Search audit is missing, invalid or belongs to another run") from None
                result = assessment_mod.score(records, assessment_mod.load_jsonl(args.reviews), profile, args.out or run_dir / "assessment", coverage)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        except (OSError, ValueError) as exc:
            print(f"{args.command} error: {exc}", file=sys.stderr)
            return 2
    if args.command in {"validate", "doctor"}:
        try:
            profile = config_mod.load_profile(args.profile)
        except config_mod.ProfileError as exc:
            print(f"profile error: {exc}", file=sys.stderr)
            return 2
        if args.command == "doctor":
            try:
                institutional = access_mod.institution_route(profile["fulltext_access"])
                checks = {service: {"configured": bool(resolve_key(profile.get(service) or {}, service)),
                                   "required_for_pagination": service == "openalex",
                                   "used_for": "venue_ratings" if service == "easyscholar" else "paper_discovery"}
                          for service in ("easyscholar", "openalex")}
            except (CredentialError, access_mod.AccessError, OSError) as exc:
                print(f"credential error: {exc}", file=sys.stderr)
                return 2
            print(json.dumps({"python": sys.version.split()[0], "credentials": checks, "sources": profile["sources"],
                              "easyScholar_enabled": profile["easyscholar"]["enabled"], "queries": config_mod.expand_queries(profile),
                              "concepts": [g["name"] for g in profile["relevance"]["required_concepts"]],
                              "fulltext_access": {"unpaywall_enabled": profile["fulltext_access"]["unpaywall"]["enabled"],
                                  "unpaywall_contact_configured": bool(access_mod.contact(profile["fulltext_access"])),
                                  "europepmc_enabled": profile["fulltext_access"]["europepmc"]["enabled"],
                                  "institution_enabled": profile["fulltext_access"]["institution"]["enabled"],
                                  "institution_profile_configured": institutional is not None,
                                  "entitlement": "requires_actual_session_or_publisher_check"}}, ensure_ascii=False, indent=2))
        else:
            profile.pop("_source_path", None)
            print(json.dumps(redact(profile), ensure_ascii=False, indent=2))
        return 0

    try:
        profile = config_mod.load_profile(args.profile)
    except config_mod.ProfileError as exc:
        print(f"profile error: {exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out) if args.out else Path("runs") / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slugify(profile['topic'])}"
    try:
        return run(profile, out_dir, args.max_pages, args.notify, args.continue_with_gaps)
    except (OSError, ValueError, CredentialError) as exc:
        print(f"run error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
