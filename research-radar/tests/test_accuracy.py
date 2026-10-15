"""Regression tests for false matches, secret handling, and auditable screening."""
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config
import credentials
import discover_openalex
import discover_papers
import easyscholar
import filters
import identifiers
import relevance
import resolve_journal
import venue_table

spec = importlib.util.spec_from_file_location("radar_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def record(name="Nature", issn="0028-0836", **extra):
    return {"id": "doi:10.1234/test", "doi": "10.1234/test", "title": "A test paper",
            "venue": {"name": name, "issn": [issn]}, "metrics": {}, **extra}


def metric(value=10, edition="2026", year="2025"):
    return {"value": value, "edition": edition, "year": year, "verified": True,
            "source": "user-reviewed institution table", "source_url": "https://example.org/metrics"}


def ranks(code=200):
    return {"code": code, "data": {"officialRank": {"all": {"sciif": "10", "sci": "Q1", "ssci": "Q2"}, "select": {}},
                                    "customRank": {"rankInfo": [{"abbName": "Local rating"}], "rank": ["id&&&1"]}}}


class IdentityTests(unittest.TestCase):
    def test_invalid_check_digits_cannot_match(self):
        self.assertIsNone(identifiers.normalize_issn("0028-0837"))
        self.assertIsNone(identifiers.normalize_issn("not-an-issn"))
        self.assertEqual(identifiers.normalize_issn("2352152x"), "2352-152X")

    def test_print_and_electronic_identifiers_both_indexed(self):
        table = venue_table.VenueTable()
        table.add_row({"jif": metric()}, {"journal": "Nature", "issn": "0028-0836", "eissn": "1476-4687"})
        r = record(issn="1476-4687")
        table.apply([r])
        self.assertTrue(r["metrics"]["jif"]["verified"])

    def test_same_title_never_overrides_conflicting_issns(self):
        table = venue_table.VenueTable()
        table.add_row({"jif": metric()}, {"journal": "Nature", "issn": "0028-0836"})
        r = record(issn="2041-1723")
        report = table.apply([r])
        self.assertEqual(report["unresolved"], 1)
        self.assertEqual(r["metrics"], {})
        self.assertEqual(filters.filter_record(r, {})["decision"], "needs_verification")

    def test_name_without_identifier_is_observed_not_verified(self):
        table = venue_table.VenueTable()
        table.add_row({"jif": metric()}, {"journal": "Nature", "issn": "0028-0836"})
        r = record(issn="")
        table.apply([r])
        self.assertEqual(r["metrics"]["jif"]["value"], 10)
        self.assertFalse(r["metrics"]["jif"]["verified"])

    def test_ambiguous_names_are_not_arbitrarily_chosen(self):
        table = venue_table.VenueTable()
        for identifier in ("0028-0836", "2041-1723"):
            table.add_row({"jif": metric()}, {"journal": "Same Name", "issn": identifier})
        r = record(name="Same Name", issn="")
        table.apply([r])
        self.assertEqual(r["venue_matches"][0]["status"], "ambiguous")
        self.assertFalse(r["metrics"])

    def test_conflicting_editions_keep_both_observations(self):
        table = venue_table.VenueTable()
        for year, value in (("2025", 10), ("2026", 12)):
            table.add_row({"jif": metric(value, year)}, {"journal": "Nature", "issn": "0028-0836"})
        r = record()
        table.apply([r])
        self.assertFalse(r["metrics"]["jif"]["verified"])
        self.assertEqual(len(r["metrics"]["jif"]["observations"]), 2)

    def test_wos_only_rows_are_kept(self):
        result = venue_table._row_to_metrics({"wos_indexes": ["SCIE"], "verified": True, "checked_at": "2026-10-14"}, {})
        self.assertEqual(result["wos_indexes"]["value"], ["SCIE"])
        self.assertTrue(result["wos_indexes"]["verified"])

    def test_release_year_never_becomes_data_year(self):
        result = venue_table._row_to_metrics({"jif": "10", "edition_year": "2026", "verified": True}, {})
        self.assertIsNone(result["jif"]["year"])

    def test_fuzzy_journal_search_does_not_auto_select(self):
        payload = {"message": {"items": [{"title": "Nature Communications", "ISSN": ["2041-1723"]}]}}
        result = resolve_journal.resolve("Nature", fetcher=lambda _: payload)
        self.assertEqual(result["status"], "needs_verification")
        self.assertIsNone(result["resolved"])

    def test_journal_resolution_can_reject_name_identifier_conflict(self):
        payload = {"message": {"title": "Nature", "ISSN": ["0028-0836"]}}
        result = resolve_journal.resolve("Nature Communications", "0028-0836", lambda _: payload)
        self.assertEqual(result["status"], "name_identifier_conflict")


class TopicTests(unittest.TestCase):
    def settings(self, mode="review"):
        return {"mode": mode, "required_concepts": [
            {"name": "object", "terms": ["battery", "batteries"]},
            {"name": "task", "terms": ["state of health", "SOH"]},
            {"name": "method", "terms": ["diffusion model", "synthetic data"]}]}

    def test_all_groups_are_required_with_within_group_synonyms(self):
        r = record(title="Synthetic data for batteries", abstract="We estimate SOH.")
        result = relevance.screen(r, self.settings())
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["groups"][1]["hits"], [{"term": "SOH", "field": "abstract"}])

    def test_missing_group_is_pending_by_default(self):
        r = record(title="Diffusion model for image generation", abstract="Synthetic images.")
        self.assertEqual(relevance.screen(r, self.settings())["status"], "needs_verification")
        self.assertEqual(relevance.screen(r, self.settings("strict_keyword"))["status"], "outside_scope")

    def test_missing_abstract_is_not_a_hard_false_negative(self):
        self.assertEqual(relevance.screen(record(title="Batteries", abstract=None), self.settings("strict_keyword"))["status"], "needs_verification")

    def test_abbreviation_does_not_match_substring(self):
        self.assertFalse(relevance.contains("soho images battery sohealth", "SOH"))
        self.assertTrue(relevance.contains("soh estimation", "SOH"))

    def test_unverified_wos_list_and_jif_do_not_prove_scie(self):
        r = record()
        r["venue"]["wos_indexes"] = ["SCIE"]
        r["metrics"]["jif"] = metric()
        self.assertEqual(filters.filter_record(r, {"include_only": {"wos_indexes": ["SCIE"]}})["decision"], "needs_verification")


class CredentialsAndProviderTests(unittest.TestCase):
    def test_custom_only_ratings_are_preserved(self):
        r = record()
        raw = ranks()
        raw["data"]["officialRank"] = {"all": {}, "select": {}}
        with patch.object(easyscholar, "query_publication", return_value=raw):
            report = easyscholar.enrich([r], "sample-secret", pause=0)
        self.assertEqual(report["papers_observed"], 1)
        self.assertEqual(r["venue_ratings"]["easyscholar"]["custom"]["rank"], ["id&&&1"])
        self.assertFalse(r["metrics"])

    def test_malformed_ranking_objects_do_not_abort_the_batch(self):
        raw = {"code": 200, "data": {"officialRank": ["invalid"], "customRank": ["invalid"]}}
        with patch.object(easyscholar, "query_publication", return_value=raw):
            report = easyscholar.enrich([record()], "sample-secret", pause=0)
        self.assertEqual(report["papers_enriched"], 0)

    def test_profile_relative_credentials_work_from_another_working_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            (base / "private").mkdir()
            (base / "private" / "credentials.json").write_text('{"easyscholar":{"secret_key":"uploaded-secret"}}')
            profile_file = base / "profile.json"
            profile_file.write_text(json.dumps({"topic": "Example", "queries": ["battery health"],
                "date": {"from": "2026-01-01", "to": "2026-01-02"},
                "easyscholar": {"credentials_file": "private/credentials.json"}}))
            with patch.dict(os.environ, {}, clear=True):
                loaded = config.load_profile(profile_file)
                self.assertEqual(easyscholar.resolve_secret_key(loaded["easyscholar"]), "uploaded-secret")
            self.assertNotIn("uploaded-secret", json.dumps(credentials.redact(loaded)))

    def test_validation_cli_never_prints_inline_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.json"
            profile.write_text(json.dumps({"topic": "Example", "queries": ["battery health"],
                "date": {"from": "2026-01-01", "to": "2026-01-02"},
                "easyscholar": {"secret_key": "private-key-sentinel"}, "openalex": {"api_key": "other-key-sentinel"}}))
            output = io.StringIO()
            with patch("sys.stdout", new=output):
                self.assertEqual(driver.main(["validate", "--profile", str(profile)]), 0)
        self.assertNotIn("private-key-sentinel", output.getvalue())
        self.assertNotIn("other-key-sentinel", output.getvalue())

    @patch.dict(os.environ, {}, clear=True)
    def test_uploaded_json_is_read_without_copying_key_to_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private.json"
            path.write_text(json.dumps({"easyscholar": {"secret_key": "user-owned-secret"}}))
            cfg = {"credentials_file": str(path)}
            self.assertEqual(easyscholar.resolve_secret_key(cfg), "user-owned-secret")
            self.assertNotIn("user-owned-secret", json.dumps(cfg))

    def test_redacts_recursive_inline_credentials_and_query_urls(self):
        public = credentials.redact({"easyscholar": {"secret_key": "private-key"},
                                     "openalex": {"api_key": "other-key"},
                                     "url": "https://example.org/?secretKey=private-key"})
        self.assertNotIn("private-key", json.dumps(public))
        self.assertNotIn("other-key", json.dumps(public))

    def test_successful_name_lookup_never_implies_verified_identity_or_year(self):
        r = record()
        with patch.object(easyscholar, "query_publication", return_value=ranks()):
            report = easyscholar.enrich([r], "sample-secret", pause=0)
        self.assertEqual(report["papers_observed"], 1)
        self.assertEqual(report["papers_enriched"], 0)
        self.assertFalse(r["metrics"]["jif"]["verified"])
        self.assertIsNone(r["metrics"]["jif"]["year"])
        self.assertEqual(r["venue_ratings"]["easyscholar"]["custom"]["rankInfo"][0]["abbName"], "Local rating")

    def test_provider_error_is_not_cached_and_is_retried_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.jsonl"
            with patch.object(easyscholar, "query_publication", side_effect=[ranks(40002), ranks()]) as query:
                easyscholar.enrich([record()], "sample-secret", cache, pause=0)
                easyscholar.enrich([record()], "sample-secret", cache, pause=0)
            self.assertEqual(query.call_count, 2)
            self.assertEqual(len(cache.read_text().splitlines()), 1)

    def test_cache_is_scoped_to_each_users_key(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.jsonl"
            with patch.object(easyscholar, "query_publication", return_value=ranks()) as query:
                easyscholar.enrich([record()], "first-user-secret", cache, pause=0)
                easyscholar.enrich([record()], "second-user-secret", cache, pause=0)
                easyscholar.enrich([record()], "second-user-secret", cache, pause=0)
            self.assertEqual(query.call_count, 2)
            self.assertNotIn("second-user-secret", cache.read_text())

    def test_expired_cache_is_refreshed_without_relabeling_old_timestamp(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache.jsonl"
            with patch.object(easyscholar, "query_publication", return_value=ranks()):
                easyscholar.enrich([record()], "sample-secret", cache, pause=0)
            entry = json.loads(cache.read_text())
            entry["retrieved_at"] = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
            cache.write_text(json.dumps(entry) + "\n")
            with patch.object(easyscholar, "query_publication", return_value=ranks()) as query:
                easyscholar.enrich([record()], "sample-secret", cache, pause=0)
            query.assert_called_once()


class PipelineTests(unittest.TestCase):
    def test_cross_source_doi_merge_retains_identity_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            files = []
            for i, (name, identifier) in enumerate((("Nature", "0028-0836"), ("Nature Communications", "2041-1723"))):
                path = Path(directory) / f"{i}.jsonl"
                r = record(name, identifier)
                if i:
                    r["doi"] = "https://doi.org/10.1234/TEST"
                    r["id"] = "different-source-id"
                path.write_text(json.dumps(r) + "\n")
                files.append(path)
            records, count = driver._merge_records(files)
        self.assertEqual(count, 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(len(records[0]["source_records"]), 2)
        self.assertEqual(records[0]["metadata_conflicts"][0]["field"], "venue")
        self.assertEqual(filters.filter_record(records[0], {})["decision"], "needs_verification")

    def test_crossref_issn_scope_is_in_request_not_fuzzy_name(self):
        with tempfile.TemporaryDirectory() as directory:
            args = discover_papers.parser().parse_args(["--query", "battery SOH", "--date-from", "2026-01-01",
                "--date-to", "2026-01-02", "--date-field", "publication", "--type", "journal-article",
                "--issn", "0028-0836", "--output-dir", directory])
            calls = []
            def fetch(params, *_):
                calls.append(params)
                return {"message": {"items": [], "total-results": 0}}
            discover_papers.collect(args, fetch, lambda _: None)
        self.assertIn("issn:0028-0836", calls[0]["filter"])

    def test_partial_discovery_returns_partial_with_reviewable_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps({"topic": "Example", "queries": ["battery SOH"],
                "date": {"from": "2026-01-01", "to": "2026-01-02"}, "sources": ["crossref"]}))
            profile = config.load_profile(path)
            def discover(_script, _profile, _types, out, _cap):
                out.mkdir(parents=True)
                (out / "candidates.jsonl").write_text(json.dumps(record()) + "\n")
                return {"source": "crossref", "status": "partial", "exit": 2, "detail": "page cap"}
            output = Path(directory) / "run"
            with patch.object(driver, "_run_discovery", side_effect=discover), patch("sys.stdout", new=io.StringIO()):
                self.assertEqual(driver.run(profile, output, 1, False), 2)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "partial")
            self.assertTrue((output / "matching-audit.jsonl").exists())
            self.assertTrue((output / "report.md").exists())


if __name__ == "__main__":
    unittest.main()
