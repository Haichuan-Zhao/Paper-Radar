import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import discover_preprints as d
import discover_papers
import easyscholar

spec = importlib.util.spec_from_file_location("preprint_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def atom(total=1):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/">
    <opensearch:totalResults>{total}</opensearch:totalResults><entry>
    <id>http://arxiv.org/abs/2601.01234v2</id><title>Battery SOH synthetic data</title>
    <published>2026-01-02T10:00:00Z</published><updated>2026-02-03T11:00:00Z</updated>
    <summary>A synthetic-data battery SOH method.</summary><author><name>Test Author</name><arxiv:affiliation>Test University</arxiv:affiliation></author>
    <arxiv:doi>10.1234/published</arxiv:doi><arxiv:journal_ref>Journal example</arxiv:journal_ref>
    <category term="cs.LG"/></entry></feed>'''.encode()


def rxiv(version=2, title="Battery synthetic data"):
    return {"doi": "10.1101/2026.01.02.000001", "version": str(version), "title": title,
            "authors": "Author One; Author Two", "abstract": "Synthetic data for battery SOH.",
            "date": "2026-01-02", "published": "10.1234/published", "category": "bioengineering"}


def args(tmp, server="arxiv", cap=None):
    return SimpleNamespace(output_dir=tmp, server=server, query=["battery synthetic"], category=[], rows=1,
                           date_from="2026-01-01", date_to="2026-01-03", timeout=1, retries=0, pause=3, max_pages=cap)


class PreprintTests(unittest.TestCase):
    def test_arxiv_version_and_publication_relation_are_separate(self):
        root, total = d.parse_atom(atom())
        r = d.normalize_arxiv(root.find("a:entry", d.NS), "https://export.arxiv.org/api/query", "2026-10-14T00:00:00Z")
        self.assertEqual(r["id"], "arxiv:2601.01234v2")
        self.assertIsNone(r["doi"])
        self.assertEqual(r["relations"][0]["doi"], "10.1234/published")
        self.assertEqual(r["published_online"], "2026-01-02")
        self.assertEqual(r["updated"], "2026-02-03")
        self.assertEqual(r["peer_review_status"], "not_peer_reviewed")

    def test_rxiv_posted_version_not_assumed_v1(self):
        r = d.normalize_rxiv(rxiv(), "biorxiv", "https://api.biorxiv.org/details", "2026-10-14T00:00:00Z")
        self.assertEqual(r["version"], 2)
        self.assertTrue(r["id"].endswith("v2"))
        self.assertEqual(r["relations"][0]["doi"], "10.1234/published")
        self.assertIn("version_posted", r["discovery"]["date_membership"]["basis"])

    def test_na_published_is_not_a_doi(self):
        item = rxiv()
        item["published"] = "NA"
        self.assertEqual(d.normalize_rxiv(item, "medrxiv", "https://api.biorxiv.org", "now")["relations"], [])

    def test_plain_arxiv_query_is_token_and_and_supports_fielded_query(self):
        q = d.arxiv_query("battery synthetic data", "2026-01-01", "2026-01-02")
        self.assertIn("(ti:battery OR abs:battery) AND", q)
        self.assertIn("202601010000 TO 202601022359", q)
        self.assertIn("abs:SOH OR abs:health", d.arxiv_query("abs:SOH OR abs:health", "2026-01-01", "2026-01-02"))

    def test_rxiv_local_matching_handles_case_punctuation_and_boundaries(self):
        self.assertTrue(d.locally_matches(rxiv(title="BATTERY synthetic-data"), "battery synthetic data"))
        self.assertFalse(d.locally_matches(rxiv(title="Perisoh unrelated"), "IS"))

    def test_arxiv_page_cap_reports_partial_and_retains_raw(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = d.collect(args(tmp, cap=1), fetcher=lambda *x: atom(4), sleeper=lambda x: None)
            self.assertEqual(ledger["status"], "partial")
            self.assertEqual(ledger["unique_candidates"], 1)
            self.assertTrue((Path(tmp) / "raw.jsonl").exists())

    def test_arxiv_exact_total_reports_query_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(d.collect(args(tmp), fetcher=lambda *x: atom(), sleeper=lambda x: None)["status"], "complete_query_coverage")

    def test_repeated_rxiv_page_stops_instead_of_looping(self):
        payload = json.dumps({"messages": [{"status": "ok", "total": 3}], "collection": [rxiv()]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = d.collect(args(tmp, "biorxiv"), fetcher=lambda *x: payload, sleeper=lambda x: None)
            self.assertEqual(ledger["status"], "partial")
            self.assertEqual(ledger["queries"][0]["reason"], "pagination_repeated_page")

    def test_missing_total_cannot_falsely_claim_feed_exhaustion(self):
        payload = json.dumps({"messages": [{"status": "ok"}], "collection": [rxiv()]}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            ledger = d.collect(args(tmp, "biorxiv"), fetcher=lambda *x: payload, sleeper=lambda x: None)
            self.assertEqual(ledger["status"], "partial")
            self.assertEqual(ledger["queries"][0]["reason"], "missing_rxiv_pagination_total")

    def test_rxiv_feed_fetched_once_for_multiple_queries(self):
        payload = json.dumps({"messages": [{"status": "ok", "total": 1}], "collection": [rxiv()]}).encode()
        calls = []
        def fetcher(*x):
            calls.append(x[0])
            return payload
        with tempfile.TemporaryDirectory() as tmp:
            cfg = args(tmp, "biorxiv")
            cfg.query = ["battery synthetic", "unrelated query"]
            d.collect(cfg, fetcher=fetcher, sleeper=lambda x: None)
            self.assertEqual(len(calls), 1)

    def test_versions_remain_separate_and_link_to_formal_doi(self):
        preprints = [d.normalize_rxiv(rxiv(v), "biorxiv", "https://api.biorxiv.org", "now") for v in (1, 2)]
        journal = {"id": "doi:10.1234/published", "doi": "10.1234/published", "title": "Different published title", "publication_type": "journal-article", "venue": {"name": "Formal journal"}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidates.jsonl"
            path.write_text("\n".join(json.dumps(r) for r in preprints + [journal]))
            merged, raw = driver._merge_records([path])
            self.assertEqual(len(merged), 3)
            self.assertEqual(len({r["work_family"] for r in merged}), 1)
            self.assertTrue(all(len(r["related_candidate_ids"]) == 2 for r in merged))

    def test_similar_titles_do_not_create_publication_relation(self):
        records = [{"id": "a", "doi": None, "title": "Identical title"}, {"id": "b", "doi": None, "title": "Identical title"}]
        driver._link_manifestations(records)
        self.assertNotEqual(records[0]["work_family"], records[1]["work_family"])

    def test_repository_never_queries_easyscholar(self):
        item = d.normalize_rxiv(rxiv(), "biorxiv", "https://api.biorxiv.org", "now")
        with patch.object(easyscholar, "query_publication", side_effect=AssertionError("Must not query a repository")):
            self.assertEqual(easyscholar.enrich([item], "dummy-test-key", pause=0)["journals_queried"], 0)

    def test_crossref_preprint_subtype_is_normalized(self):
        r = discover_papers.normalize({"DOI": "10.1101/test", "title": ["Preprint"], "type": "posted-content", "subtype": "preprint"}, "q1", "now", 1)
        self.assertEqual(r["publication_type"], "preprint")
        self.assertEqual(r["peer_review_status"], "not_peer_reviewed")


if __name__ == "__main__":
    unittest.main()
