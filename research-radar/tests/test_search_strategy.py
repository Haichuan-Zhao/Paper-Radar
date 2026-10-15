"""Deep discovery is auditable; small display counts never truncate retrieval."""
import copy
import contextlib
import importlib.util
import io
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assessment
import config
import search_strategy as search

spec = importlib.util.spec_from_file_location("search_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class DeepSearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / "run"
        self.run.mkdir()
        self.profile_path = self.root / "config.json"
        self.profile_path.write_text(json.dumps({"topic": "Synthetic battery test", "queries": ["battery SOH", "battery synthetic data", "battery physics model"],
                                                "date": {"from": "2026-01-01", "to": "2026-01-02"}, "count": 1, "sources": ["crossref"]}))
        self.p = config.load_profile(self.profile_path)
        self.plan_info = search.write_plan(self.p, self.run, None)
        self.plan = json.loads((self.run / "search-plan.json").read_text())
        self.ledger = json.loads((self.run / "search-ledger.template.json").read_text())
        self.ledger_path = self.root / "ledger.json"
        self.summary = {"status": "ok", "unique_candidates": 2, "source_candidate_records": 6,
                        "search_strategy": {"source_coverage": [{"source": "crossref", "pages": 6, "coverage_status": "complete_query_coverage"}]}}
        self.candidates = [{"id": "doi:10.1234/synthetic", "title": "Synthetic candidate"}]
        (self.run / "summary.json").write_text(json.dumps(self.summary))
        assessment.write_jsonl(self.run / "candidates.jsonl", self.candidates)

    def evidence(self, **extra):
        return {"source": "Synthetic primary source", "url": "https://example.org/synthetic-source",
                "retrieved_at": datetime.now(timezone.utc).isoformat(), **extra}

    def complete(self):
        for key in search.STEPS:
            self.ledger["steps"][key] = {"status": "completed", "summary": "Synthetic fixture only: observed this search step.",
                                        "evidence": [self.evidence(seed_id="doi:10.1234/synthetic")]}
        self.ledger["rounds"] = [{"round": n, "queries": ["synthetic query round " + str(n)],
                                  "new_eligible_ids": ["doi:10.1234/synthetic"] if n == 1 else [],
                                  "evidence": [self.evidence()]} for n in (1, 2, 3)]
        self.ledger["stop_reason"] = "saturated"
        return self.ledger

    def audit(self):
        self.ledger_path.write_text(json.dumps(self.ledger))
        target = self.root / ("audit-" + str(len(list(self.root.glob("audit-*")))) + ".json")
        return search.audit(self.run, self.ledger_path, target)

    def test_default_is_deep_and_presentation_count_is_not_retrieval_limit(self):
        self.assertEqual(self.p["search"], {"mode": "deep", "citation_hops": 2, "saturation_rounds": 2})
        self.assertEqual(self.plan["report_count"], 1)
        self.assertIsNone(self.plan["retrieval_count_limit"])
        self.assertIsNone(self.plan["max_pages_per_query"])
        self.assertEqual(len(self.plan["queries"]), 3)

    def test_all_queries_reach_discovery_without_implicit_page_cap(self):
        response = SimpleNamespace(returncode=0, stdout="fixture", stderr="")
        with patch.object(driver.subprocess, "run", return_value=response) as execute:
            driver._run_discovery("discover_papers.py", self.p, ["journal-article"], self.run / "crossref", None)
        command = execute.call_args.args[0]
        self.assertEqual(command.count("--query"), 3)
        self.assertNotIn("--max-pages", command)
        self.assertNotIn("--limit", command)

    def test_invalid_search_settings_are_rejected(self):
        for value in ({"mode": "random"}, {"citation_hops": True}, {"citation_hops": 0}, {"saturation_rounds": 0}, {"max_candidates": 10}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                search.settings(value)

    def test_empty_ledger_never_claims_completed_deep_search(self):
        result = self.audit()
        self.assertEqual(result["status"], "partial")
        self.assertIn("search_not_saturated", result["issues"])
        self.assertEqual(sum(issue.startswith("unfinished_or_unanchored:") for issue in result["issues"]), len(search.STEPS))

    def test_observed_steps_and_two_zero_new_rounds_complete_only_declared_plan(self):
        self.complete()
        result = self.audit()
        self.assertEqual(result["status"], "declared_plan_completed")
        self.assertEqual(result["round_new_eligible_counts"], [1, 0, 0])
        self.assertIn("not proof", result["scope"])

    def test_no_evidence_or_missing_citation_seed_remains_incomplete(self):
        self.complete()
        self.ledger["steps"]["query_expansion"]["evidence"] = []
        self.ledger["steps"]["forward_citations"]["evidence"] = [self.evidence()]
        result = self.audit()
        self.assertIn("unfinished_or_unanchored:query_expansion", result["issues"])
        self.assertIn("citation_seed_missing:forward_citations", result["issues"])

    def test_budget_stop_and_insufficient_zero_rounds_stay_partial(self):
        self.complete()
        self.ledger["stop_reason"] = "budget"
        self.assertEqual(self.audit()["status"], "partial")
        self.ledger["stop_reason"] = "saturated"
        self.ledger["rounds"].pop()
        self.assertIn("search_not_saturated", self.audit()["issues"])

    def test_duplicate_ids_cannot_be_counted_as_new_repeatedly(self):
        self.complete()
        self.ledger["rounds"][1]["new_eligible_ids"] = ["doi:10.1234/synthetic"]
        with self.assertRaises(ValueError):
            self.audit()

    def test_new_papers_missing_from_final_candidate_set_are_disclosed(self):
        self.complete()
        self.ledger["rounds"][0]["new_eligible_ids"] = ["doi:10.1234/not-integrated"]
        self.assertIn("new_candidates_not_in_final_run", self.audit()["issues"])

    def test_related_versions_do_not_establish_new_independent_papers(self):
        self.complete()
        assessment.write_jsonl(self.run / "candidates.jsonl", [
            {"id": "arxiv:2601.00001v1", "work_family": "arxiv:2601.00001"},
            {"id": "arxiv:2601.00001v2", "work_family": "arxiv:2601.00001"}])
        self.ledger["rounds"][0]["new_eligible_ids"] = ["arxiv:2601.00001v1", "arxiv:2601.00001v2"]
        self.assertIn("related_versions_counted_as_new_papers", self.audit()["issues"])

    def test_partial_or_unverified_builtin_coverage_cannot_pass(self):
        self.complete()
        self.summary["status"] = "partial"
        self.summary["search_strategy"]["source_coverage"][0]["coverage_status"] = "partial"
        (self.run / "summary.json").write_text(json.dumps(self.summary))
        result = self.audit()
        self.assertIn("partial_builtin_sources", result["issues"])
        self.assertIn("builtin_query_coverage_unverified", result["issues"])

    def test_wrong_plan_binding_stops_without_audit_file(self):
        self.complete()
        self.ledger["plan_id"] = "other-run"
        with self.assertRaises(ValueError):
            self.audit()
        self.assertFalse(list(self.root.glob("audit-*")))

    def test_source_coverage_counts_pages_and_explicit_scope_skips(self):
        source = self.run / "crossref"
        source.mkdir()
        (source / "search-coverage.json").write_text(json.dumps({"status": "complete_query_coverage", "queries": [{"pages_fetched": 3}, {"pages_fetched": 4}]}))
        rows = search.source_coverage(self.run, [{"source": "crossref", "status": "complete"},
                                               {"source": "arxiv", "status": "complete", "detail": "skipped: journal scope"}])
        self.assertEqual((rows[0]["pages"], rows[0]["query_variants"]), (7, 2))
        self.assertEqual(rows[1]["coverage_status"], "skipped_by_scope")

    def prepare_assessment(self):
        (self.run / "profile.json").write_text(json.dumps(self.p))
        assessment.prepare(self.candidates, self.p, self.root / "review")
        return ["assess", "--run", str(self.run), "--reviews", str(self.root / "review/reviews.template.jsonl")]

    def test_reading_list_discloses_pending_or_bound_search_coverage(self):
        args = self.prepare_assessment()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.main(args), 0)
        summary = json.loads((self.run / "assessment/assessment-summary.json").read_text())
        self.assertEqual(summary["search_coverage"]["status"], "host_deepening_pending")
        self.complete()
        self.ledger_path.write_text(json.dumps(self.ledger))
        search.audit(self.run, self.ledger_path, self.run / "search-audit.json")
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.main(args + ["--out", str(self.root / "bound-assessment")]), 0)
        summary = json.loads((self.root / "bound-assessment/assessment-summary.json").read_text())
        self.assertEqual(summary["search_coverage"]["status"], "declared_plan_completed")
        self.assertIn("declared_plan_completed", (self.root / "bound-assessment/reading-list.md").read_text())

    def test_assessment_rejects_audit_from_another_run(self):
        args = self.prepare_assessment()
        (self.run / "search-audit.json").write_text(json.dumps({"schema_version": 1, "plan_id": "other", "status": "declared_plan_completed", "issues": []}))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(driver.main(args), 2)
        self.assertFalse((self.run / "assessment").exists())


if __name__ == "__main__":
    unittest.main()
