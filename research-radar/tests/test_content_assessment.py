"""Synthetic evidence fixtures test selection logic, not scientific accuracy."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assessment as a
import calibrate_assessments as calibration
import config
import filters

spec = importlib.util.spec_from_file_location("content_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def profile():
    return {"topic": "battery SOH synthetic data", "user_prompt": "Find useful synthetic-data methods for battery SOH in small datasets.",
            "requirements": {"purpose": "method reuse", "hard_constraints": []}, "count": 10,
            "relevance": {"mode": "review", "required_concepts": [{"name": "battery", "terms": ["battery"]}]},
            "filters": {}, "journal_issns": [], "assessment": a.config()}


def paper(key="arxiv:2601.00001v1"):
    return {"id": key, "title": "Synthetic battery data for SOH", "abstract": "A synthetic-data method estimates battery SOH with independent test sets.",
            "doi": None, "publication_type": "preprint", "url": "https://arxiv.org/abs/2601.00001v1",
            "version": 1, "preprint": {"server": "arxiv", "native_id": "2601.00001", "version": 1},
            "venue": {"name": "arXiv"}, "peer_review_status": "not_peer_reviewed", "metrics": {},
            "filter": {"decision": "keep", "checks": []}}


def review(record, p, quality=4, match=4):
    r = a.template(record, p)
    r["reviewer"] = {"model": "synthetic-test-fixture", "reviewed_at": datetime.now(timezone.utc).isoformat()}
    r["paper_type"] = "empirical"
    r["access"] = {"full_text": True, "full_text_source": "https://example.org/synthetic-test-only",
                   "material_candidate_id": record["id"], "material_version": "submittedVersion" if record.get("publication_type") == "preprint" else "publishedVersion",
                   "native_version": record.get("version"), "identity_evidence_id": "identity",
                   "retrieval_method": "open_access", "verified_at": datetime.now(timezone.utc).isoformat(),
                   "figure_count": 1, "figures_inspected": [1]}
    r["evidence"].extend([
        {"id": "identity", "kind": "full_text", "source": "https://example.org/synthetic-test-only", "locator": "Header; synthetic fixture only", "excerpt": record["title"] + " / " + record["id"]},
        {"id": "method", "kind": "full_text", "source": "https://example.org/synthetic-test-only", "locator": "Section 3, paragraph 2", "excerpt": "Independent held-out cells test SOH estimation under small-data conditions."},
        {"id": "prior", "kind": "prior_work", "source": "https://example.org/synthetic-baseline", "locator": "Method section", "excerpt": "The baseline lacks conditional synthetic-data generation."},
        {"id": "fig1", "kind": "figure", "source": "https://example.org/synthetic-test-only", "locator": "Figure 1, panels a–c", "excerpt": "Axes identify held-out-cell error and sample sizes."},
        {"id": "conclusion", "kind": "full_text", "source": "https://example.org/synthetic-test-only", "locator": "Conclusion", "excerpt": "The method supports small-data SOH estimation in the evaluated setting."},
        {"id": "result", "kind": "full_text", "source": "https://example.org/synthetic-test-only", "locator": "Section 4, held-out results", "excerpt": "SOH error decreased on the held-out cells; validation covers one synthetic test domain."},
    ])
    for key in a.QUALITY:
        r["quality"][key] = {"score": quality, "rationale": "Synthetic fixture: the anchored evidence supports this dimension with a limited sample.", "evidence_ids": ["method"] + (["prior"] if key == "originality" else ["fig1"] if key == "figures" else [])}
    for key in a.MATCH:
        r["match"][key] = {"score": match, "rationale": "Synthetic fixture: the method tests the battery SOH problem in the requested small-data setting.", "evidence_ids": ["method", "request"]}
    r["concept_checks"] = [{"id": "battery", "result": "pass", "rationale": "Battery SOH is explicitly the evaluated task.", "evidence_ids": ["method"]}]
    r["claim_audit"] = {"coverage": {"status": "complete", "checked_at": datetime.now(timezone.utc).isoformat(),
        "rationale": "The synthetic conclusion and reported results were checked in this offline fixture.", "evidence_ids": ["conclusion", "result"]},
        "claims": [{"id": "c1", "role": "main_conclusion", "central": True,
            "claim": "The method supports small-data SOH estimation in the evaluated setting.",
            "claim_evidence_ids": ["conclusion"], "supporting_evidence_ids": ["method", "result"],
            "counterevidence_ids": [], "verdict": "supported", "scope": "The single evaluated synthetic test domain only.",
            "rationale": "The synthetic held-out results support the explicitly bounded conclusion.",
            "safe_conclusion": "The author reports a benefit within the single synthetic evaluation setting."}]}
    r["strengths"] = [{"text": "Held-out evaluation in this synthetic fixture.", "basis": "author_report", "claim_ids": ["c1"], "evidence_ids": ["method", "result"]}]
    r["limitations"] = [{"text": "Single synthetic test domain; not a real scientific review.", "basis": "reviewer_assessment", "claim_ids": ["c1"], "evidence_ids": ["result"]}]
    r["reading_reason"] = {"text": "The test fixture directly addresses the requested small-data SOH method reuse.",
                           "basis": "reviewer_assessment", "claim_ids": ["c1"], "evidence_ids": ["method", "request"]}
    r["review_confidence"] = "high"
    return r


class ContentScoringTests(unittest.TestCase):
    def setUp(self):
        self.p, self.r = profile(), paper()
        self.v = review(self.r, self.p)

    def score(self):
        return a.score_record(self.r, self.v, self.p)["assessment"]

    def test_complete_preprint_can_be_shortlisted_without_if(self):
        s = self.score()
        self.assertEqual(s["quality"]["score"], 80)
        self.assertEqual(s["match"]["score"], 80)
        self.assertEqual(s["composite"]["score"], 80)
        self.assertEqual(s["status"], "shortlist")

    def test_famous_authors_and_high_if_do_not_change_content_scores(self):
        first = self.score()
        self.r["authors"] = [{"name": "Famous Person", "affiliation": "Prestigious University"}]
        self.r["metrics"] = {"jif": {"value": 100, "verified": True}}
        second = self.score()
        self.assertEqual(first["quality"], second["quality"])
        self.assertEqual(first["composite"], second["composite"])

    def test_high_quality_cannot_compensate_for_bad_fit(self):
        self.v = review(self.r, self.p, quality=4.5, match=2)
        self.assertEqual(self.score()["status"], "below_match_floor")

    def test_perfect_fit_cannot_compensate_for_bad_quality(self):
        self.v = review(self.r, self.p, quality=2, match=5)
        self.assertEqual(self.score()["status"], "below_quality_floor")

    def test_low_rigor_cannot_be_hidden_by_other_dimensions(self):
        self.v = review(self.r, self.p, quality=5, match=5)
        self.v["quality"]["rigor"]["score"] = 1
        self.assertEqual(self.score()["status"], "below_quality_floor")

    def test_fair_rigor_below_reliable_level_cannot_be_recommended(self):
        self.v = review(self.r, self.p, quality=5, match=5)
        self.v["quality"]["rigor"]["score"] = 2
        self.assertEqual(self.score()["status"], "below_quality_floor")

    def test_missing_figure_is_uncertainty_not_zero(self):
        self.v["access"]["figures_inspected"] = []
        s = self.score()
        self.assertIsNone(s["quality"]["score"])
        self.assertEqual(s["quality"]["observed_score"], 80)
        self.assertEqual((s["quality"]["lower"], s["quality"]["upper"]), (72, 82))
        self.assertEqual(s["status"], "needs_content_review")

    def test_abstract_only_cannot_produce_final_quality(self):
        self.v["access"]["full_text"] = False
        s = self.score()
        self.assertEqual(s["quality"]["evidence_coverage"], 0)
        self.assertIsNone(s["composite"]["score"])

    def test_originality_needs_comparison_with_prior_work(self):
        self.v["quality"]["originality"]["evidence_ids"] = ["method"]
        self.assertIn("originality", self.score()["quality"]["missing_dimensions"])

    def test_author_metadata_is_not_valid_quality_evidence(self):
        self.v["evidence"].append({"id": "author", "kind": "metadata", "source": "https://example.org/author", "locator": "Biography", "excerpt": "A famous researcher."})
        self.v["quality"]["motivation"]["evidence_ids"] = ["author"]
        self.assertIn("motivation", self.score()["quality"]["missing_dimensions"])

    def test_unknown_anchor_and_nonfinite_scores_fail_closed(self):
        self.v["quality"]["rigor"]["score"] = float("nan")
        self.v["match"]["problem"]["evidence_ids"] = ["nonexistent"]
        s = self.score()
        self.assertIn("rigor", s["quality"]["missing_dimensions"])
        self.assertIn("problem", s["match"]["missing_dimensions"])

    def test_match_requires_prompt_and_article_evidence(self):
        self.v["match"]["problem"]["evidence_ids"] = ["method"]
        self.assertIn("problem", self.score()["match"]["missing_dimensions"])

    def test_prompt_and_version_changes_reject_stale_reviews(self):
        self.p["user_prompt"] = "A different research goal"
        with self.assertRaises(a.AssessmentError):
            self.score()
        self.p = profile()
        self.r["version"] = 2
        with self.assertRaises(a.AssessmentError):
            self.score()

    def test_fabricated_abstract_quote_is_rejected(self):
        self.v["evidence"][1]["excerpt"] = "An invented result absent from the real abstract"
        self.v["match"]["problem"]["evidence_ids"] = ["request", "abstract"]
        self.assertIn("problem", self.score()["match"]["missing_dimensions"])

    def test_lexical_pending_can_be_resolved_semantically(self):
        self.r["filter"] = {"decision": "needs_verification", "checks": [{"field": "topic_match", "matched": None}]}
        self.assertEqual(self.score()["status"], "shortlist")

    def test_explicit_wos_gate_cannot_be_cleared_by_semantic_review(self):
        self.r["filter"] = {"decision": "needs_verification", "checks": [{"field": "wos_indexes", "matched": None}]}
        self.assertEqual(self.score()["status"], "needs_verification")

    def test_unspecified_pending_filter_cannot_be_silently_cleared(self):
        self.r["filter"] = {"decision": "needs_verification", "reasons": ["Unresolved filter"]}
        self.assertEqual(self.score()["status"], "needs_verification")

    def test_explicit_strict_keyword_exclusion_is_preserved(self):
        self.r["filter"] = {"decision": "exclude", "checks": [], "reasons": ["strict keyword restriction"]}
        self.assertEqual(self.score()["status"], "excluded_filter")

    def test_unknown_constraint_is_pending_and_failed_constraint_excluded(self):
        self.p["requirements"]["hard_constraints"] = [{"id": "experiment", "description": "Experimental validation required"}]
        self.v = review(self.r, self.p)
        self.assertEqual(self.score()["status"], "needs_content_review")
        self.v["constraint_checks"] = [{"id": "experiment", "result": "fail", "rationale": "Full text confirms only simulated data without experimental validation.", "evidence_ids": ["method"]}]
        self.assertEqual(self.score()["status"], "excluded_scope")

    def test_abstract_absence_does_not_establish_hard_constraint_failure(self):
        self.p["requirements"]["hard_constraints"] = [{"id": "experiment", "description": "Experimental validation required"}]
        self.v = review(self.r, self.p)
        self.v["constraint_checks"] = [{"id": "experiment", "result": "fail", "rationale": "The abstract does not mention experimental validation so it may be absent.", "evidence_ids": ["abstract"]}]
        self.assertEqual(self.score()["status"], "needs_content_review")

    def test_unattributed_claim_of_critical_error_stays_suspected(self):
        self.v["reviewer"] = {}
        self.v["findings"] = [{"severity": "critical", "status": "confirmed", "rationale": "Claim of a critical problem from a reviewer without provenance.", "evidence_ids": ["method"], "claim_ids": ["c1"]}]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_confirmed_core_flaw_overrides_high_scores(self):
        self.v["findings"] = [{"severity": "critical", "status": "confirmed", "rationale": "Synthetic fixture confirms test-label leakage in the claimed independent evaluation.", "evidence_ids": ["method"], "claim_ids": ["c1"],
            "verification": {"method": "cross_check", "rationale": "A second synthetic result location was checked for the claimed inconsistency.", "evidence_ids": ["result"]}}]
        self.assertEqual(self.score()["status"], "excluded_core_flaw")

    def test_suspected_flaw_needs_review_not_accusation(self):
        self.v["findings"] = [{"severity": "critical", "status": "suspected", "rationale": "The plotted panel raises a question that has not been verified.", "evidence_ids": ["fig1"], "claim_ids": ["c1"]}]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_theory_without_figures_can_be_evaluated(self):
        self.v["paper_type"] = "theoretical"
        self.v["access"].update(figure_count=0, figures_inspected=[])
        self.v["quality"]["figures"]["evidence_ids"] = ["method"]
        self.assertEqual(self.score()["status"], "shortlist")

    def test_missing_reviewer_or_low_confidence_cannot_promote(self):
        self.v["reviewer"] = {}
        self.assertEqual(self.score()["status"], "needs_content_review")
        self.v = review(self.r, self.p)
        self.v["review_confidence"] = "low"
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_no_review_is_pending(self):
        self.assertEqual(a.score_record(self.r, None, self.p)["assessment"]["status"], "needs_content_review")

    def test_review_budget_withholds_author_and_venue_and_keeps_unreviewed(self):
        other = paper("arxiv:2601.00002v1")
        self.p["assessment"]["review_limit"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            manifest = a.prepare([self.r, other], self.p, tmp)
            packet = a.load_jsonl(Path(tmp) / "review-packet.jsonl")[0]
            self.assertNotIn("authors", packet["paper"])
            self.assertNotIn("venue", packet["paper"])
            self.assertEqual(manifest["unreviewed_ids"], [other["id"]])

    def test_manifestations_do_not_fill_two_recommendation_slots(self):
        other = paper("arxiv:2601.00001v2")
        self.r["work_family"] = other["work_family"] = "same-work"
        other["version"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            summary = a.score([self.r, other], [self.v, review(other, self.p)], self.p, tmp)
            self.assertEqual(len(summary["selected_ids"]), 1)
            self.assertTrue((Path(tmp) / "reading-list.md").exists())
            with self.assertRaises(a.AssessmentError):
                a.score([self.r], [self.v], self.p, tmp)

    def test_duplicate_or_unknown_reviews_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(a.AssessmentError):
                a.score([self.r], [self.v, self.v], self.p, tmp)

    def test_settings_reject_nan_weight_sum_and_one_axis_only(self):
        for cfg in ({"quality_weight": float("inf")}, {"quality_weight": 1}, {"quality_weights": {"rigor": 100}}, {"quality_floo": 70}):
            with self.assertRaises(a.AssessmentError):
                a.config(cfg)


class PreprintGateAndCalibrationTests(unittest.TestCase):
    def test_venue_gates_separate_from_preprints_unless_requested(self):
        settings = {"include_only": {"min_jif": 20, "wos_indexes": ["SCIE"]}}
        self.assertEqual(filters.filter_record(paper(), settings)["decision"], "keep")
        settings["preprint_venue_policy"] = "apply"
        self.assertEqual(filters.filter_record(paper(), settings)["decision"], "needs_verification")

    def test_peer_reviewed_switch_still_excludes_preprint(self):
        self.assertEqual(filters.filter_record(paper(), {"include_only": {"peer_reviewed_only": True}})["decision"], "exclude")

    def test_unknown_peer_review_status_is_not_truthy_success(self):
        r = paper()
        r["peer_review_status"] = "unknown"
        self.assertEqual(filters.filter_record(r, {"include_only": {"peer_reviewed_only": True}})["decision"], "needs_verification")

    def test_calibration_ties_and_missing_labels(self):
        self.assertEqual(calibration.spearman([1, 2, 2, 4], [1, 2, 2, 4]), 1)
        self.assertIsNone(calibration.spearman([1, 1, 1], [2, 3, 4]))
        p, r = profile(), paper()
        ranked = [a.score_record(r, review(r, p), p)]
        result = calibration.evaluate(ranked, [{"candidate_id": r["id"], "quality": 60, "match": 80}])
        self.assertEqual(result["quality"]["mae"], 20)
        self.assertIsNone(result["precision_at_k"])
        self.assertEqual(len(result["large_disagreements"]), 1)

    def test_false_recommendation_is_reported(self):
        p, r = profile(), paper()
        ranked = [a.score_record(r, review(r, p), p)]
        result = calibration.evaluate(ranked, [{"candidate_id": r["id"], "selected": False}])
        self.assertEqual(result["precision_at_k"], 0)
        self.assertEqual(result["false_positive_ids"], [r["id"]])

    def test_profile_round_trip_keeps_request_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({"topic": "battery", "queries": ["battery SOH"], "date": {"from": "2026-01-01", "to": "2026-01-02"}}))
            p = config.load_profile(path)
            path.write_text(json.dumps(p))
            self.assertEqual(a.digest(a.request(p)), a.digest(a.request(config.load_profile(path))))


if __name__ == "__main__":
    unittest.main()
