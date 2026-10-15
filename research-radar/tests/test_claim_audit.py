"""Adversarial declarations test safeguards, not scientific truth or accuracy."""
import copy
from pathlib import Path
import tempfile
import unittest

from test_content_assessment import a, paper, profile, review


class ClaimAuditTests(unittest.TestCase):
    def setUp(self):
        self.p, self.r = profile(), paper()
        self.v = review(self.r, self.p, quality=5, match=5)

    @property
    def claim(self):
        return self.v["claim_audit"]["claims"][0]

    def score(self):
        return a.score_record(self.r, self.v, self.p)["assessment"]

    def verified_negative(self, verdict):
        self.claim.update(verdict=verdict, counterevidence_ids=["result"], supporting_evidence_ids=[],
            verification={"method": "cross_check", "rationale": "The synthetic result and held-out protocol were compared in a focused check.", "evidence_ids": ["method"]})

    def test_missing_audit_blocks_perfect_scores(self):
        self.v.pop("claim_audit")
        result = self.score()
        self.assertIsNone(result["quality"]["score"])
        self.assertIsNone(result["composite"]["score"])
        self.assertEqual(result["status"], "needs_content_review")
        self.assertIn("evidence", result["quality"]["missing_dimensions"])

    def test_coverage_is_not_established_by_an_empty_or_future_declaration(self):
        for field, value in (("status", "pending"), ("evidence_ids", ["abstract"]), ("checked_at", "2999-01-01T00:00:00Z")):
            with self.subTest(field=field):
                original = copy.deepcopy(self.v)
                self.v["claim_audit"]["coverage"][field] = value
                self.assertIsNone(self.score()["composite"]["score"])
                self.v = original

    def test_novelty_alone_does_not_cover_the_main_conclusion(self):
        self.claim.update(role="novelty", supporting_evidence_ids=["method", "prior"])
        self.assertIn("central_conclusion_not_audited", self.score()["issues"])

    def test_invented_author_quote_is_not_published(self):
        self.claim["claim"] = "Fabricated unlimited generalization to every possible application."
        result = self.score()
        self.assertEqual(result["claim_audit"]["claims"][0]["claim"], "")
        self.assertNotEqual(result["status"], "must_read")

    def test_restating_a_claim_is_not_supporting_results(self):
        self.claim["supporting_evidence_ids"] = ["conclusion"]
        result = self.score()
        self.assertEqual(result["status"], "needs_expert_review")
        self.assertIsNone(result["quality"]["score"])

    def test_renaming_the_same_source_location_does_not_corroborate(self):
        original = next(e for e in self.v["evidence"] if e["id"] == "conclusion")
        self.v["evidence"].append({**original, "id": "duplicate_conclusion"})
        self.claim["supporting_evidence_ids"] = ["duplicate_conclusion"]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_repeating_the_author_claim_at_another_location_is_not_corroboration(self):
        original = next(e for e in self.v["evidence"] if e["id"] == "conclusion")
        self.v["evidence"].append({**original, "id": "claim_repeated", "locator": "Another paragraph repeating the conclusion"})
        self.claim["supporting_evidence_ids"] = ["claim_repeated"]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_metadata_or_abstract_only_cannot_verify_results(self):
        self.claim["supporting_evidence_ids"] = ["abstract"]
        self.assertIsNone(self.score()["composite"]["score"])

    def test_qualified_central_claim_caps_evidence_and_confidence(self):
        self.claim.update(verdict="qualified", counterevidence_ids=["result"],
                          safe_conclusion="The author reports results only in the evaluated synthetic setting.")
        result = self.score()
        self.assertEqual(result["quality"]["dimensions"]["evidence"]["score"], 3)
        self.assertEqual(result["quality"]["score"], 90)
        self.assertEqual(result["status"], "shortlist")
        self.assertEqual(result["confidence"], "medium")
        self.assertEqual(result["claim_audit"]["score_adjustments"][0]["submitted"], 5)
        self.assertEqual(self.v["quality"]["evidence"]["score"], 5)

    def test_qualification_cannot_increase_an_existing_low_score(self):
        self.claim.update(verdict="qualified", counterevidence_ids=["result"])
        self.v["quality"]["evidence"]["score"] = 1
        self.assertEqual(self.score()["quality"]["dimensions"]["evidence"]["score"], 1)

    def test_unresolved_central_claim_cannot_be_recommended(self):
        self.claim["verdict"] = "unresolved"
        result = self.score()
        self.assertEqual(result["status"], "needs_expert_review")
        self.assertIsNone(result["composite"]["score"])

    def test_unverified_negative_is_a_question_not_an_exclusion(self):
        for verdict in ("unsupported", "contradicted"):
            self.claim.update(verdict=verdict, counterevidence_ids=["result"])
            result = self.score()
            self.assertEqual(result["status"], "needs_expert_review")
            self.assertEqual(result["claim_audit"]["claims"][0]["verdict"], "unresolved")

    def test_checked_unsupported_claim_cannot_be_rescued_by_high_scores(self):
        self.verified_negative("unsupported")
        self.p["assessment"].update(quality_floor=0, critical_dimension_floor=0)
        result = self.score()
        self.assertEqual(result["status"], "below_quality_floor")
        self.assertEqual(result["quality"]["dimensions"]["evidence"]["score"], 2)
        self.assertNotEqual(result["status"], "excluded_core_flaw")
        self.assertIsNone(result["composite"]["score"])
        self.assertEqual(result["composite"]["blocked_by"], "unsupported_core_claim")

    def test_checked_contradiction_overrides_numeric_priority(self):
        self.verified_negative("contradicted")
        result = self.score()
        self.assertEqual(result["status"], "excluded_core_flaw")
        self.assertIsNone(result["composite"]["score"])

    def test_counterevidence_cannot_double_as_a_separate_verification(self):
        self.verified_negative("contradicted")
        self.claim["verification"]["evidence_ids"] = ["result"]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_secondary_unknown_is_disclosed_without_invalidating_supported_core(self):
        secondary = copy.deepcopy(self.claim)
        secondary.update(id="c2", role="other", central=False, verdict="unresolved")
        self.v["claim_audit"]["claims"].append(secondary)
        result = self.score()
        self.assertEqual(result["status"], "must_read")
        self.assertEqual(result["claim_audit"]["claims"][1]["verdict"], "unresolved")

    def test_claimed_independent_reproduction_requires_reproduction_evidence(self):
        extra = copy.deepcopy(self.claim)
        extra.update(id="replication", role="reproducibility", central=False)
        self.v["claim_audit"]["claims"].append(extra)
        result = self.score()
        self.assertIsNone(result["composite"]["score"])
        self.assertIn("claim_evidence_or_verification_incomplete:replication", result["issues"])

    def test_novelty_requires_opened_prior_work_as_well_as_primary_content(self):
        extra = copy.deepcopy(self.claim)
        extra.update(id="novelty", role="novelty", central=False)
        self.v["claim_audit"]["claims"].append(extra)
        self.assertIsNone(self.score()["composite"]["score"])
        extra["supporting_evidence_ids"].append("prior")
        self.assertEqual(self.score()["status"], "must_read")

    def test_unanchored_praise_and_criticism_do_not_enter_the_report(self):
        for name in ("strengths", "limitations"):
            original = copy.deepcopy(self.v)
            self.v[name] = ["Unverified prose promising universal state-of-the-art performance."]
            result = self.score()
            self.assertEqual(result[name], [])
            self.assertIsNone(result["composite"]["score"])
            self.v = original

    def test_report_statements_require_both_claim_and_source_links(self):
        self.v["strengths"][0]["claim_ids"] = ["unknown-claim"]
        self.v["reading_reason"]["evidence_ids"] = ["method"]
        result = self.score()
        self.assertEqual(result["strengths"], [])
        self.assertEqual(result["reading_reason"], {})
        self.assertIsNone(result["composite"]["score"])

    def test_body_from_another_paper_needs_explicit_material_binding(self):
        item = next(e for e in self.v["evidence"] if e["id"] == "result")
        item["source"] = "https://example.org/unrelated-paper"
        result = self.score()
        self.assertIn("body_evidence_material_unbound:result", result["issues"])
        self.assertIsNone(result["composite"]["score"])

    def test_bound_supplement_can_use_a_different_source(self):
        item = next(e for e in self.v["evidence"] if e["id"] == "result")
        item.update(source="https://example.org/synthetic-supplement", material_candidate_id=self.r["id"],
                    material_version=self.v["access"]["material_version"], native_version=self.r["version"])
        self.assertEqual(self.score()["status"], "must_read")

    def test_conflicting_version_binding_cannot_be_ignored_on_the_same_url(self):
        item = next(e for e in self.v["evidence"] if e["id"] == "result")
        item.update(material_candidate_id=self.r["id"], material_version=self.v["access"]["material_version"], native_version=2)
        self.assertIn("body_evidence_material_unbound:result", self.score()["issues"])

    def test_the_current_paper_cannot_serve_as_its_own_opened_prior_work(self):
        prior = next(e for e in self.v["evidence"] if e["id"] == "prior")
        prior["source"] = self.v["access"]["full_text_source"]
        self.assertIn("originality", self.score()["quality"]["missing_dimensions"])

    def test_unverified_critical_finding_is_downgraded(self):
        self.v["findings"] = [{"severity": "critical", "status": "confirmed", "rationale": "An apparent visual anomaly needs investigation before any accusation.",
                              "evidence_ids": ["fig1"], "claim_ids": ["c1"]}]
        result = self.score()
        self.assertEqual(result["status"], "needs_expert_review")
        self.assertEqual(result["findings"][0]["status"], "suspected")
        self.assertIsNone(result["composite"]["score"])

    def test_major_findings_are_not_silently_ignored(self):
        self.v["findings"] = [{"severity": "major", "status": "suspected", "rationale": "A material protocol ambiguity affecting the conclusion needs further review.",
                              "evidence_ids": ["method"], "claim_ids": ["c1"]}]
        result = self.score()
        self.assertEqual(result["status"], "needs_expert_review")
        self.assertIsNone(result["quality"]["score"])
        self.assertIsNone(result["composite"]["score"])

    def test_report_discloses_qualified_claims_and_adjustments(self):
        self.claim.update(verdict="qualified", counterevidence_ids=["result"])
        with tempfile.TemporaryDirectory() as tmp:
            summary = a.score([self.r], [self.v], self.p, tmp)
            output = (Path(tmp) / "reading-list.md").read_text()
            self.assertEqual(summary["selected_ids"], [self.r["id"]])
            self.assertIn("作者报告：", output)
            self.assertIn("评审判断：", output)
            self.assertIn(self.claim["scope"], output)
            self.assertIn(self.claim["safe_conclusion"], output)
            self.assertIn("evidence 5 → 3", output)

    def test_old_schema_is_rejected_instead_of_silently_grandfathered(self):
        self.v.update(schema_version=4, rubric_version="research-radar-content-v3")
        with self.assertRaisesRegex(a.AssessmentError, "schema v5"):
            self.score()

    def test_report_cannot_present_a_priority_score_for_a_failed_core_claim(self):
        self.verified_negative("unsupported")
        with tempfile.TemporaryDirectory() as tmp:
            summary = a.score([self.r], [self.v], self.p, tmp)
            self.assertEqual(summary["selected_ids"], [])
            output = (Path(tmp) / "reading-list.md").read_text()
            self.assertIn("不计算（核心证据未通过）", output)
            self.assertIn("复核方式：cross_check", output)

    def test_malformed_claim_lists_cannot_crash_or_promote(self):
        for field, value in (("claims", {}), ("claims", [None]), ("coverage", [])):
            original = copy.deepcopy(self.v)
            self.v["claim_audit"][field] = value
            self.assertIsNone(self.score()["composite"]["score"])
            self.v = original

    def test_malformed_enums_cannot_crash_or_promote(self):
        for field, value in (("role", []), ("verdict", {}), ("central", "true")):
            original = copy.deepcopy(self.v)
            self.claim[field] = value
            self.assertIsNone(self.score()["composite"]["score"])
            self.v = original
        self.v["strengths"][0]["basis"] = []
        self.assertIsNone(self.score()["composite"]["score"])

    def test_malformed_optional_evidence_can_still_be_reported_as_pending(self):
        for field, value in (("supporting_evidence_ids", [{}]), ("counterevidence_ids", "bad"), ("verification", ["bad"])):
            original = copy.deepcopy(self.v)
            self.claim[field] = value
            with tempfile.TemporaryDirectory() as tmp:
                result = a.score([self.r], [self.v], self.p, tmp)
                self.assertEqual(result["selected_ids"], [])
                self.assertTrue((Path(tmp) / "reading-list.md").exists())
            self.v = original

    def test_header_identity_and_a_self_claim_do_not_verify_results(self):
        self.claim["supporting_evidence_ids"] = ["identity", "conclusion"]
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_request_text_cannot_be_used_as_an_author_quote(self):
        self.claim.update(claim=self.p["user_prompt"], claim_evidence_ids=["abstract", "request"])
        self.assertIn("invalid_claim_audit_entry", self.score()["issues"])

    def test_bad_verification_method_is_not_a_confirmed_negative(self):
        self.verified_negative("contradicted")
        self.claim["verification"]["method"] = []
        self.assertEqual(self.score()["status"], "needs_expert_review")

    def test_unresolved_secondary_claim_cannot_support_a_positive_recommendation_reason(self):
        extra = copy.deepcopy(self.claim)
        extra.update(id="c2", role="other", central=False, verdict="unresolved")
        self.v["claim_audit"]["claims"].append(extra)
        self.v["strengths"][0]["claim_ids"] = ["c2"]
        result = self.score()
        self.assertEqual(result["strengths"], [])
        self.assertIsNone(result["composite"]["score"])

    def test_scoped_theoretical_work_does_not_require_an_empirical_study(self):
        self.v["paper_type"] = "theoretical"
        self.v["access"].update(figure_count=0, figures_inspected=[])
        self.v["quality"]["figures"]["evidence_ids"] = ["method"]
        for item in self.v["evidence"]:
            if item["id"] == "conclusion":
                item["excerpt"] = "The bound holds under the stated assumptions."
            elif item["id"] == "result":
                item["excerpt"] = "A formal derivation establishes the bound subject to the stated assumptions."
        self.claim.update(claim="The bound holds under the stated assumptions.", scope="Only the explicitly stated theorem assumptions.",
                          safe_conclusion="The provided derivation supports the stated conditional bound.")
        self.assertEqual(self.score()["status"], "must_read")


if __name__ == "__main__":
    unittest.main()
