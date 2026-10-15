"""Offline tests for coverage accounting, date uncertainty and safe failures."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "discover_papers.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("discover_papers", SCRIPT)
discovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discovery
spec.loader.exec_module(discovery)


def item(identifier="10.1234/test", title="Test paper", online=None):
    record = {"DOI": identifier, "title": [title], "type": "journal-article",
              "author": [{"given": "Ada", "family": "Lovelace"}],
              "published": {"date-parts": [[2026, 8, 10]]}}
    if online is not None:
        record["published-online"] = {"date-parts": [online]}
    return record


def page(records, cursor="same-cursor", total=3):
    return {"message": {"items": records, "next-cursor": cursor, "total-results": total}}


class DiscoveryTests(unittest.TestCase):
    def args(self, directory, *extra):
        args = discovery.parser().parse_args(["--query", "test", "--date-from", "2026-08-01",
                                             "--date-to", "2026-08-31", "--date-field", "publication",
                                             "--type", "journal-article", "--rows", "2",
                                             "--output-dir", directory, "--pause", "0", *extra])
        return args

    def collect(self, directory, responses, *extra):
        calls = []
        def fetch(params, *_):
            calls.append(params)
            result = responses.pop(0)
            if isinstance(result, BaseException):
                raise result
            return result
        ledger = discovery.collect(self.args(directory, *extra), fetch, lambda _: None)
        candidates = [json.loads(line) for line in (Path(directory) / "candidates.jsonl").read_text().splitlines()]
        return ledger, candidates, calls

    def test_pagination_reused_cursor_and_doi_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, candidates, calls = self.collect(tmp, [page([item(), item("10.1234/B")]),
                                                          page([item("https://doi.org/10.1234/TEST")])])
            self.assertEqual("complete_query_coverage", ledger["status"])
            self.assertEqual(2, len(candidates))
            self.assertEqual(1, ledger["queries"][0]["duplicates"])
            self.assertEqual("same-cursor", calls[1]["cursor"])
            self.assertEqual(2, len(candidates[0]["provenance"]))
            self.assertEqual({}, candidates[0]["evaluation"])
            self.assertEqual(3, len((Path(tmp) / "raw-crossref.jsonl").read_text().splitlines()))

    def test_explicit_page_cap_never_claims_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, candidates, _ = self.collect(tmp, [page([item(), item("10.1234/b")])], "--max-pages", "1")
            self.assertEqual("partial", ledger["status"])
            self.assertEqual("explicit_max_pages", ledger["queries"][0]["reason"])
            self.assertFalse(ledger["queries"][0]["cursor_exhausted"])
            self.assertEqual(2, len(candidates))

    def test_relevance_order_is_explicit_on_every_cursor_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, _, calls = self.collect(tmp, [page([item(), item("10.1234/b")]), page([])])
            self.assertEqual(["*", "same-cursor"], [call["cursor"] for call in calls])
            for call in calls:
                self.assertEqual("score", call["sort"])
                self.assertEqual("desc", call["order"])
                self.assertEqual("test", call["query"])
            self.assertEqual("score", ledger["queries"][0]["sort"])
            self.assertEqual("desc", ledger["queries"][0]["order"])

    def test_failure_keeps_pages_and_unstarted_queries(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, candidates, _ = self.collect(tmp, [page([item(), item("10.1234/b")]), KeyboardInterrupt()], "--query", "second")
            self.assertEqual("partial", ledger["status"])
            self.assertTrue(ledger["interrupted"])
            self.assertEqual("not_started", ledger["queries"][1]["status"])
            self.assertEqual(2, len(candidates))
            saved = json.loads((Path(tmp) / "search-coverage.json").read_text())
            self.assertEqual(ledger, saved)

    def test_repeated_page_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = [item(), item("10.1234/b")]
            ledger, candidates, _ = self.collect(tmp, [page(records), page(records)])
            self.assertEqual("partial", ledger["status"])
            self.assertEqual("repeated_page_without_progress", ledger["queries"][0]["reason"])
            self.assertEqual(2, len(candidates))

    def test_full_page_without_cursor_is_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, _, _ = self.collect(tmp, [page([item(), item("10.1234/b")], cursor=None, total=100)])
            self.assertEqual("partial", ledger["status"])
            self.assertEqual("missing_cursor_on_full_page", ledger["queries"][0]["reason"])
            self.assertFalse(ledger["queries"][0]["cursor_exhausted"])

    def test_empty_exhausted_and_malformed_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger, candidates, _ = self.collect(tmp, [page([])])
            self.assertEqual("complete_query_coverage", ledger["status"])
            self.assertEqual([], candidates)
        with tempfile.TemporaryDirectory() as tmp:
            ledger, _, _ = self.collect(tmp, [page([{"unexpected": "shape"}])])
            self.assertEqual("partial", ledger["status"])
            self.assertEqual(1, ledger["queries"][0]["malformed_records"])

    def test_online_policy_preserves_precision_and_excludes_wrong_interval(self):
        interval = (date(2026, 8, 1), date(2026, 8, 31))
        record = discovery.normalize(item(online=[2025, 12, 1]), "q", "now", 1)
        self.assertEqual("outside", discovery.date_membership(record, *interval, "online-first")["status"])
        record["published_online"] = "2026"
        result = discovery.date_membership(record, *interval, "online-first")
        self.assertEqual("needs_date_verification", result["status"])
        self.assertEqual("year", result["precision"])
        record["published_online"] = "2026-08"
        self.assertEqual("within", discovery.date_membership(record, *interval, "online-first")["status"])
        record["published_online"] = None
        self.assertTrue(discovery.date_membership(record, *interval, "online-first")["fallback_used"])
        self.assertEqual("needs_date_verification", discovery.date_membership(record, *interval, "online")["status"])

    def test_online_first_queries_both_date_filters(self):
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp, "--date-field", "online-first")
            calls = []
            def fetch(params, *_):
                calls.append(params)
                return page([])
            ledger = discovery.collect(args, fetch, lambda _: None)
            self.assertEqual(2, len(calls))
            self.assertIn("from-online-pub-date:2026-08-01", calls[0]["filter"])
            self.assertIn("from-pub-date:2026-08-01", calls[1]["filter"])
            self.assertEqual("complete_query_coverage", ledger["status"])

    def test_normalization_does_not_invent_quality_or_review_subtype(self):
        record = discovery.normalize(item(title="Systematic review of examples"), "q", "now", 1)
        self.assertEqual("journal-article", record["publication_type"])
        self.assertIsNone(record["peer_review_status"])
        self.assertIsNone(record["venue"]["wos_indexes"])
        self.assertEqual({}, record["metrics"])
        self.assertEqual({}, record["artifacts"])
        self.assertIsNone(discovery.date_value({"date-parts": [[2026, 2, 30]]}))
        self.assertEqual("2026-08", discovery.date_value({"date-parts": [[2026, 8]]}))

    def test_fallback_identity_and_differing_dois(self):
        one = discovery.normalize(item(identifier=None), "q", "now", 1)
        two = discovery.normalize(item(identifier=None, title="TEST PAPER!"), "q", "now", 2)
        self.assertEqual(one["id"], two["id"])
        a = discovery.normalize(item(identifier="10.1234/a"), "q", "now", 3)
        b = discovery.normalize(item(identifier="10.1234/b"), "q", "now", 4)
        self.assertNotEqual(a["id"], b["id"])

    def test_missing_authors_do_not_collapse_distinct_generic_titles(self):
        a = item(identifier=None, title="Editorial")
        a["author"] = None
        a["container-title"] = ["Journal A"]
        b = dict(a, **{"container-title": ["Journal B"]})
        self.assertNotEqual(discovery.normalize(a, "q", "now", 1)["id"],
                            discovery.normalize(b, "q", "now", 2)["id"])

    def test_http_failure_is_redacted_and_respects_long_retry_after(self):
        error = urllib.error.HTTPError("https://example.org/?apikey=SECRET", 429, "SECRET", {"Retry-After": "3600"}, io.BytesIO(b"SECRET"))
        events = []
        with patch.object(discovery.urllib.request, "urlopen", side_effect=error), patch.object(discovery.time, "sleep") as sleep:
            with self.assertRaises(discovery.FetchError) as raised:
                discovery.fetch_json({}, 1, 2, events)
        self.assertNotIn("SECRET", str(raised.exception) + json.dumps(events))
        self.assertIn("retry_after_exceeds_60s", str(raised.exception))
        sleep.assert_not_called()

    def test_existing_evidence_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.jsonl"
            path.write_text("previous evidence")
            with self.assertRaises(ValueError):
                discovery.collect(self.args(tmp))
            self.assertEqual("previous evidence", path.read_text())


if __name__ == "__main__":
    unittest.main()
