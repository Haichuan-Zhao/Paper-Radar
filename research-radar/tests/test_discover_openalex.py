"""Offline tests for OpenAlex normalization, dedup, dates and safe failures."""
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

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "discover_openalex.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("discover_openalex", SCRIPT)
discovery = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = discovery
spec.loader.exec_module(discovery)


def work(doi="10.1234/test", title="Test paper", native_type="article",
         pubdate="2026-08-10", abstract=None):
    record = {
        "id": "https://openalex.org/W123",
        "doi": doi,
        "title": title,
        "type": native_type,
        "publication_date": pubdate,
        "authorships": [{"author": {"display_name": "Ada Lovelace",
                                    "orcid": "https://orcid.org/0000-0002-0000-0000"}}],
        "primary_location": {"source": {"display_name": "Example Journal",
                                        "issn": ["1234-5678"], "issn_l": "1234-5678",
                                        "host_organization_name": "Example Society"}},
    }
    if abstract is not None:
        record["abstract_inverted_index"] = abstract
    return record


def page(results, next_cursor=None, count=3):
    return {"meta": {"count": count, "next_cursor": next_cursor}, "results": results}


class OpenAlexDiscoveryTests(unittest.TestCase):
    def args(self, directory, *extra):
        return discovery.parser().parse_args(["--query", "test", "--date-from", "2026-08-01",
                                              "--date-to", "2026-08-31", "--date-field", "publication",
                                              "--type", "journal-article", "--rows", "2",
                                              "--output-dir", directory, "--pause", "0", *extra])

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

    def test_abstract_reconstruction(self):
        self.assertEqual("Hello world example",
                         discovery.reconstruct_abstract({"Hello": [0], "world": [1], "example": [2]}))
        self.assertEqual("Hello world",
                         discovery.reconstruct_abstract({"world": [1], "Hello": [0]}))
        self.assertIsNone(discovery.reconstruct_abstract(None))
        self.assertIsNone(discovery.reconstruct_abstract({}))
        record = discovery.normalize(work(abstract={"Hello": [0], "world": [1]}), "q", "now", 1)
        self.assertEqual("Hello world", record["abstract"])

    def test_doi_normalization(self):
        self.assertEqual("10.1234/test", discovery.doi("https://doi.org/10.1234/TEST"))
        self.assertEqual("10.1234/abc", discovery.doi("doi:10.1234/ABC"))
        self.assertEqual("10.1234/x", discovery.doi("HTTP://DX.DOI.ORG/10.1234/x"))
        self.assertIsNone(discovery.doi("not-a-doi"))
        self.assertEqual("10.1234/test", discovery.normalize(work(), "q", "now", 1)["doi"])

    def test_type_mapping(self):
        self.assertEqual("journal-article", discovery.normalize(work(native_type="article"), "q", "now", 1)["publication_type"])
        self.assertEqual("conference-paper", discovery.normalize(work(native_type="conference-paper"), "q", "now", 2)["publication_type"])
        self.assertEqual("preprint", discovery.normalize(work(native_type="preprint"), "q", "now", 3)["publication_type"])
        self.assertEqual("article", discovery.normalize(work(native_type="article"), "q", "now", 4)["source_publication_type"])

    def test_identity_dedup(self):
        one = discovery.normalize(work(doi="10.1234/a"), "q", "now", 1)
        two = discovery.normalize(work(doi="https://doi.org/10.1234/A"), "q", "now", 2)
        self.assertEqual(one["id"], two["id"])
        a = discovery.normalize(work(doi=None, title="One title"), "q", "now", 3)
        b = discovery.normalize(work(doi=None, title="A different title"), "q", "now", 4)
        self.assertNotEqual(a["id"], b["id"])

    def test_date_membership(self):
        interval = (date(2026, 8, 1), date(2026, 8, 31))
        record = discovery.normalize(work(pubdate="2026-08-10"), "q", "now", 1)
        self.assertEqual("within", discovery.date_membership(record, *interval, "online-first")["status"])
        self.assertEqual("outside", discovery.date_membership(record, date(2026, 9, 1), date(2026, 9, 30), "online-first")["status"])
        self.assertIsNone(record["published_online"])
        self.assertTrue(discovery.date_membership(record, *interval, "online-first")["fallback_used"])
        record["published"] = None
        self.assertEqual("needs_date_verification", discovery.date_membership(record, *interval, "online-first")["status"])

    def test_http_failure_is_redacted_and_respects_long_retry_after(self):
        error = urllib.error.HTTPError("https://example.org/?api_key=SECRET", 429, "SECRET", {"Retry-After": "3600"}, io.BytesIO(b"SECRET"))
        events = []
        with patch.object(discovery.urllib.request, "urlopen", side_effect=error), patch.object(discovery.time, "sleep") as sleep:
            with self.assertRaises(discovery.FetchError) as raised:
                discovery.fetch_json({}, 1, 2, events)
        self.assertNotIn("SECRET", str(raised.exception) + json.dumps(events))
        self.assertIn("retry_after_exceeds_60s", str(raised.exception))
        sleep.assert_not_called()

    def test_normalization_does_not_invent_quality_or_review_subtype(self):
        record = discovery.normalize(work(title="Systematic review of examples"), "q", "now", 1)
        self.assertEqual("journal-article", record["publication_type"])
        self.assertIsNone(record["peer_review_status"])
        self.assertIsNone(record["venue"]["wos_indexes"])
        self.assertIsNone(record["venue"]["volume"])
        self.assertEqual({}, record["metrics"])
        self.assertEqual({}, record["artifacts"])
        self.assertIsNone(record["pdf_path"])

    def test_existing_evidence_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.jsonl"
            path.write_text("previous evidence")
            with self.assertRaises(ValueError):
                discovery.collect(self.args(tmp))
            self.assertEqual("previous evidence", path.read_text())


if __name__ == "__main__":
    unittest.main()
