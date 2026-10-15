"""Access-state tests use mocked metadata, never paid sessions or downloads."""
import copy
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assessment as assessment
import config
import fulltext_access as access
import discover_openalex
from test_content_assessment import profile, paper, review

spec = importlib.util.spec_from_file_location("access_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def article():
    r = paper("doi:10.1038/example")
    r.update(doi="10.1038/example", publication_type="journal-article", version=None, preprint=None,
             url="https://doi.org/10.1038/example")
    return r


def enabled():
    p = profile()
    p["fulltext_access"] = {"unpaywall": {"enabled": True, "email": "researcher@example.org"}, "pause": 0}
    return p


def oa_data(version="publishedVersion"):
    return {"doi": "10.1038/example", "is_oa": True,
            "oa_locations": [{"url_for_pdf": "https://repository.example.org/paper.pdf", "version": version,
                              "host_type": "repository", "license": None}]}


def obs(record, outcome="readable_full_text", version="publishedVersion"):
    v = access.observation_template(record, assessment.fingerprint(record))
    v.update(outcome=outcome, source=record["url"], checked_at=datetime.now(timezone.utc).isoformat(),
             retrieval_method="open_access", material_version=version, identity_verified=True,
             evidence={"locator": "Observed article page and body", "excerpt": record["title"] + " / " + record["id"]})
    return v


class AccessRoutesTests(unittest.TestCase):
    def resolve(self, r=None, p=None, observations=None):
        return access.resolve([r or article()], p or profile(), assessment.fingerprint, observations)

    @patch.object(access, "fetch_json", return_value=oa_data("acceptedVersion"))
    def test_open_link_is_not_verified_full_text_or_a_quality_score(self, fetch):
        rows, summary = self.resolve(p=enabled())
        self.assertEqual(rows[0]["status"], "oa_link_found")
        self.assertFalse(rows[0]["assessed_content"])
        self.assertEqual(rows[0]["routes"][0]["version"], "acceptedVersion")
        self.assertIsNone(rows[0]["routes"][0]["license"])
        self.assertEqual(rows[0]["routes"][0]["status"], "link_unverified")
        self.assertEqual(summary["metadata_requests"], 1)
        self.assertNotIn("researcher@example.org", json.dumps(rows))

    @patch.object(access, "fetch_json", return_value={"doi": "10.1038/different", "oa_locations": oa_data()["oa_locations"]})
    def test_wrong_doi_never_attaches_the_copy(self, fetch):
        rows, _ = self.resolve(p=enabled())
        self.assertEqual(rows[0]["status"], "lookup_inconclusive")
        self.assertFalse(any(r.get("reported_open_access") for r in rows[0]["routes"]))

    @patch.object(access, "fetch_json", side_effect=access.AccessError("metadata_http_403"))
    def test_metadata_403_does_not_infer_subscription_or_purchase(self, fetch):
        rows, _ = self.resolve(p=enabled())
        self.assertEqual(rows[0]["status"], "lookup_inconclusive")
        self.assertNotEqual(rows[0]["status"], "subscription_required")

    @patch.object(access, "fetch_json", return_value={"doi": "10.1038/example", "oa_locations": []})
    def test_no_oa_is_distinct_from_access_denied(self, fetch):
        rows, _ = self.resolve(p=enabled())
        self.assertEqual(rows[0]["status"], "no_open_copy_found")
        self.assertIsNone(rows[0]["observation"])

    def test_embargoed_future_copy_is_not_usable(self):
        data = {"doi": "10.1038/example", "oa_locations": [], "oa_locations_embargoed": oa_data()["oa_locations"]}
        self.assertEqual(access.unpaywall_routes(data, "10.1038/example"), [])

    @patch.dict(os.environ, {}, clear=True)
    @patch.object(access, "fetch_json")
    def test_unpaywall_missing_user_email_is_inconclusive_without_request(self, fetch):
        p = enabled()
        p["fulltext_access"]["unpaywall"]["email"] = None
        rows, _ = self.resolve(p=p)
        self.assertEqual(rows[0]["status"], "lookup_inconclusive")
        self.assertEqual(rows[0]["metadata_attempts"][0]["reason"], "user_contact_email_missing")
        fetch.assert_not_called()

    @patch.object(access, "fetch_json")
    def test_default_uses_existing_routes_without_extra_network(self, fetch):
        r = article()
        r["full_text_urls"] = [{"url": "https://publisher.example.org/paper.pdf", "source": "OpenAlex",
                                "reported_open_access": True, "version": "publishedVersion", "format": "pdf"}]
        rows, _ = self.resolve(r)
        self.assertEqual(rows[0]["status"], "oa_link_found")
        fetch.assert_not_called()

    @patch.object(access, "fetch_json")
    def test_native_preprint_link_keeps_version_and_does_not_query_journal_doi(self, fetch):
        r = paper()
        r["doi"] = "10.1101/example"
        r["full_text_urls"] = [{"url": "https://arxiv.org/pdf/2601.00001v1", "format": "pdf"}]
        rows, _ = self.resolve(r, enabled())
        self.assertEqual(rows[0]["routes"][0]["native_version"], 1)
        self.assertEqual(rows[0]["routes"][0]["version"], "submittedVersion")
        fetch.assert_not_called()

    @patch.object(access, "fetch_json", return_value=oa_data())
    def test_budget_preserves_nonchecked_candidates(self, fetch):
        p = enabled()
        p["fulltext_access"]["max_lookups"] = 0
        rows, summary = self.resolve(p=p)
        self.assertEqual(rows[0]["status"], "not_checked")
        self.assertEqual(summary["metadata_requests"], 0)
        fetch.assert_not_called()

    def test_europe_pmc_xml_only_for_oa_subset_and_doi_matched(self):
        data = {"resultList": {"result": [{"doi": "10.1038/example", "pmcid": "PMC123", "isOpenAccess": "N"}]}}
        self.assertEqual(access.europepmc_routes(data, "10.1038/example"), [])
        data["resultList"]["result"][0]["isOpenAccess"] = "Y"
        routes = access.europepmc_routes(data, "10.1038/example")
        self.assertEqual(routes[0]["format"], "xml")
        self.assertEqual(routes[0]["version"], "unknown")
        with self.assertRaises(access.AccessError):
            access.europepmc_routes(data, "10.1038/different")

    def test_secret_or_transient_link_is_not_persisted(self):
        r = article()
        r["full_text_urls"] = [{"url": "https://publisher.example.org/paper?access_token=secret", "reported_open_access": True}]
        rows, _ = self.resolve(r)
        self.assertNotIn("secret", json.dumps(rows))
        self.assertEqual(rows[0]["status"], "not_checked")

    def test_signed_session_pdf_url_is_replaced_by_stable_landing_route(self):
        r = article()
        r["full_text_urls"] = [{"url": "https://files.example.org/paper.pdf?X-Amz-Signature=private", "reported_open_access": True}]
        rows, _ = self.resolve(r)
        self.assertEqual([r["url"] for r in rows[0]["routes"]], [r["url"]])
        self.assertNotIn("Signature", json.dumps(rows))

    def test_institution_profile_routes_do_not_claim_entitlement(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auth.json"
            path.write_text(json.dumps({"schema_version": 1, "default_profile": "university", "profiles": {
                "university": {"institution": "Example university", "library_url": "https://library.example.org/databases",
                               "allowed_domains": ["library.example.org"], "browser_profile_label": "Existing library browser",
                               "secret_storage": "browser_password_manager_only"}}}))
            p = profile()
            p["fulltext_access"] = {"institution": {"enabled": True, "config_file": str(path)}}
            rows, _ = self.resolve(p=p)
            self.assertEqual(rows[0]["status"], "institution_route_available")
            self.assertEqual(rows[0]["routes"][-1]["entitlement"], "unknown")

    def test_config_rejects_secret_bearing_or_unknown_entitlement_fields(self):
        for block in ({"institution": {"password": "test"}}, {"unpaywall": {"enabled": "false"}}, {"max_lookups": True}):
            with self.assertRaises(access.AccessError):
                access.settings(block)


class ActualObservationTests(unittest.TestCase):
    def test_readable_requires_actual_identity_version_time_and_evidence(self):
        r = article()
        for field, value in (("identity_verified", False), ("material_version", "unknown"), ("checked_at", ""), ("evidence", {})):
            v = obs(r)
            v[field] = value
            with self.assertRaises(access.AccessError):
                access.resolve([r], profile(), assessment.fingerprint, [v])

    def test_actual_denial_is_recorded_only_with_observation(self):
        r = article()
        rows, _ = access.resolve([r], profile(), assessment.fingerprint, [obs(r, "subscription_required")])
        self.assertEqual(rows[0]["status"], "subscription_required")
        self.assertFalse(rows[0]["assessed_content"])

    @patch.object(access, "fetch_json", return_value=oa_data())
    def test_denial_of_one_route_does_not_hide_another_open_copy(self, fetch):
        r = article()
        rows, _ = access.resolve([r], enabled(), assessment.fingerprint, [obs(r, "subscription_required")])
        self.assertEqual(rows[0]["status"], "oa_link_found")
        self.assertEqual(rows[0]["observation"]["outcome"], "subscription_required")

    def test_journal_reading_a_preprint_is_an_alternative_not_vor(self):
        r = article()
        rows, _ = access.resolve([r], profile(), assessment.fingerprint, [obs(r, version="submittedVersion")])
        self.assertEqual(rows[0]["status"], "alternative_version_available")

    def test_stale_or_different_native_version_is_rejected(self):
        r = paper()
        v = obs(r, version="submittedVersion")
        v["native_version"] = 2
        with self.assertRaises(access.AccessError):
            access.resolve([r], profile(), assessment.fingerprint, [v])
        v = obs(r, version="submittedVersion")
        r["title"] = "A different title"
        with self.assertRaises(access.AccessError):
            access.resolve([r], profile(), assessment.fingerprint, [v])

    def test_native_source_url_cannot_contradict_the_declared_version(self):
        r = paper()
        v = obs(r, version="submittedVersion")
        v["source"] = "https://arxiv.org/pdf/2601.00001v2"
        with self.assertRaises(access.AccessError):
            access.resolve([r], profile(), assessment.fingerprint, [v])
        self.assertTrue(access.preprint_url_matches(r, "https://arxiv.org/pdf/2601.00001v1.pdf"))
        self.assertFalse(access.preprint_url_matches(r, "https://arxiv.org/pdf/2601.00002v1"))

    def test_output_never_downloads_or_overwrites_prior_evidence(self):
        r = article()
        rows, summary = access.resolve([r], profile(), assessment.fingerprint)
        with tempfile.TemporaryDirectory() as tmp:
            access.write(tmp, rows, summary, [r], assessment.fingerprint)
            self.assertEqual(len(list(Path(tmp).iterdir())), 4)
            with self.assertRaises(access.AccessError):
                access.write(tmp, rows, summary, [r], assessment.fingerprint)


class AccessQualityBoundaryTests(unittest.TestCase):
    def test_oa_link_does_not_fill_blank_review(self):
        r, p = paper(), profile()
        r["fulltext_access"] = {"status": "oa_link_found"}
        a = assessment.score_record(r, None, p)["assessment"]
        self.assertIsNone(a["quality"]["score"])
        self.assertEqual(a["status"], "needs_content_review")

    def test_body_version_check_catches_a_contradictory_native_url(self):
        r, p = paper(), profile()
        v = review(r, p)
        v["access"]["full_text_source"] = "https://arxiv.org/pdf/2601.00001v2"
        v["evidence"][2]["source"] = v["access"]["full_text_source"]
        a = assessment.score_record(r, v, p)["assessment"]
        self.assertIn("full_text_source_version_mismatch", a["issues"])
        self.assertIsNone(a["quality"]["score"])

    def test_paywall_metadata_does_not_reduce_actually_read_content_quality(self):
        r, p = article(), profile()
        v = review(r, p)
        first = assessment.score_record(r, v, p)["assessment"]
        r["fulltext_access"] = {"status": "subscription_required"}
        second = assessment.score_record(r, v, p)["assessment"]
        self.assertEqual(first["composite"], second["composite"])
        self.assertEqual(second["status"], "shortlist")

    def test_preprint_evidence_does_not_supply_published_article_scores(self):
        r, p = article(), profile()
        v = review(r, p)
        v["access"]["material_version"] = "submittedVersion"
        a = assessment.score_record(r, v, p)["assessment"]
        self.assertIsNone(a["quality"]["score"])
        self.assertIsNone(a["match"]["score"])
        self.assertIn("full_text_version_mismatch", a["issues"])

    def test_different_material_candidate_cannot_supply_any_body_check(self):
        r, p = paper(), profile()
        v = review(r, p)
        v["access"]["material_candidate_id"] = "arxiv:2601.00001v2"
        a = assessment.score_record(r, v, p)["assessment"]
        self.assertIsNone(a["quality"]["score"])
        self.assertEqual(a["concept_checks"]["battery"], "unknown")

    def test_accepted_manuscript_is_transparently_labelled(self):
        r, p = article(), profile()
        v = review(r, p)
        v["access"]["material_version"] = "acceptedVersion"
        a = assessment.score_record(r, v, p)["assessment"]
        self.assertEqual(a["status"], "shortlist")
        self.assertEqual(a["access"]["material_version"], "acceptedVersion")
        r["version"] = "publishedVersion"
        v["candidate_fingerprint"] = assessment.fingerprint(r)
        self.assertIsNone(assessment.score_record(r, v, p)["assessment"]["quality"]["score"])

    def test_final_fit_must_be_confirmed_in_read_copy_not_only_publisher_abstract(self):
        r, p = article(), profile()
        v = review(r, p)
        v["access"]["material_version"] = "acceptedVersion"
        for dimension in v["match"].values():
            dimension["evidence_ids"] = ["abstract", "request"]
        a = assessment.score_record(r, v, p)["assessment"]
        self.assertEqual(a["quality"]["score"], 80)
        self.assertIsNone(a["match"]["score"])
        self.assertEqual(a["status"], "needs_content_review")

    def test_missing_fulltext_stays_in_acquisition_queue_without_fake_quality(self):
        r, p = article(), profile()
        r["fulltext_access"] = {"status": "subscription_required", "next_action": "user_pdf_or_library_document_delivery"}
        with tempfile.TemporaryDirectory() as tmp:
            summary = assessment.score([r], [], p, tmp)
            self.assertEqual(summary["selected_ids"], [])
            self.assertEqual(summary["acquisition_queue"][0]["candidate_id"], r["id"])
            self.assertIn("待获取全文", (Path(tmp) / "reading-list.md").read_text())

    def test_access_manifest_rejects_stale_identity_without_invalidating_content_on_status_change(self):
        r = article()
        old = assessment.fingerprint(r)
        rows, _ = access.resolve([r], profile(), assessment.fingerprint)
        assessment.attach_access([r], rows)
        self.assertEqual(old, assessment.fingerprint(r))
        r["title"] = "Different"
        with self.assertRaises(assessment.AssessmentError):
            assessment.attach_access([r], rows)

    def test_normalized_profile_has_portable_access_defaults_and_relative_auth_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps({"topic": "test", "queries": ["test"], "date": {"from": "2026-01-01"},
                                       "fulltext_access": {"institution": {"config_file": "private/auth.json"}}}))
            p = config.load_profile(path)
            self.assertFalse(p["fulltext_access"]["unpaywall"]["enabled"])
            self.assertEqual(p["fulltext_access"]["institution"]["config_file"], str((Path(tmp) / "private/auth.json").resolve()))


if __name__ == "__main__":
    unittest.main()
