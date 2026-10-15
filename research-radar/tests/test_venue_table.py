"""Offline tests for venue-metric table loading and identifier matching."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "venue_table.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("venue_table", SCRIPT)
venue_table = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = venue_table
spec.loader.exec_module(venue_table)


CSV_EN = (
    "journal,issn_l,issn,eissn,source,source_url,edition_year,data_year,category,"
    "jcr_quartile,jcr_percentile,jif,jif_percentile,cas_large_zone,cas_small_zone,cas_top,ccf_rank,wos_indexes,verified\n"
    "Journal of Energy Storage,2352-152X,2352-152X,2352-1538,Clarivate JCR,https://jcr.example.com,2026,2025,"
    "ENERGY & FUELS,Q1,88.0,10.7,90.0,1,1,1,,SCIE,true\n"
)

CSV_ZH = (
    "期刊名,ISSN,影响因子,JCR分区,中科院大类分区,中科院小类分区,收录索引,来源,来源链接,数据年\n"
    "Energy,0360-5442,9.0,Q1,1,1,SCIE,Clarivate,https://example.com,2025\n"
)


class TestNormalize(unittest.TestCase):
    def test_issn(self):
        self.assertEqual(venue_table.normalize_issn("2352-152x"), "2352-152X")
        self.assertIsNone(venue_table.normalize_issn(""))

    def test_quartile_and_partition(self):
        self.assertEqual(venue_table._quartile("q1"), "Q1")
        self.assertEqual(venue_table._partition("1区"), 1)
        self.assertIsNone(venue_table._partition("5"))


class TestCsvLoad(unittest.TestCase):
    def test_english_headers(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write(CSV_EN)
            path = Path(f.name)
        table = venue_table.load_venue_tables([path])
        rec = {"venue": {"name": "Journal of Energy Storage", "issn": ["2352-152X"]}, "metrics": {}}
        method, entries = table.match(rec)
        self.assertEqual(method, "issn_l")
        self.assertEqual(len(entries), 1)
        table.apply([rec])
        self.assertEqual(rec["metrics"]["cas_partition"]["value"], 1)
        self.assertEqual(rec["metrics"]["jcr_quartile"]["value"], "Q1")
        self.assertEqual(rec["metrics"]["jif"]["value"], 10.7)
        self.assertEqual(rec["venue"]["wos_indexes"], ["SCIE"])

    def test_chinese_headers(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8-sig", delete=False) as f:
            f.write(CSV_ZH)
            path = Path(f.name)
        table = venue_table.load_venue_tables([path])
        rec = {"venue": {"name": "Energy", "issn": ["0360-5442"]}, "metrics": {}}
        method, entries = table.match(rec)
        self.assertEqual(method, "issn")
        table.apply([rec])
        self.assertEqual(rec["metrics"]["cas_partition"]["value"], 1)
        self.assertEqual(rec["metrics"]["jif"]["value"], 9.0)

    def test_title_fallback_match(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", encoding="utf-8", delete=False) as f:
            f.write(CSV_EN)
            path = Path(f.name)
        table = venue_table.load_venue_tables([path])
        rec = {"venue": {"name": "Journal of Energy Storage", "issn": []}, "metrics": {}}
        method, _ = table.match(rec)
        self.assertEqual(method, "title")


class TestMetricFields(unittest.TestCase):
    def test_cas_large_zone_with_small_zone_preserved(self):
        row = {
            "journal": "J", "issn_l": "1111-1111", "source": "s", "source_url": "u",
            "edition_year": "2026", "data_year": "2025", "category": "c",
            "cas_large_zone": "2", "cas_small_zone": "1",
        }
        metrics = venue_table._row_to_metrics(row, {})
        self.assertEqual(metrics["cas_partition"]["value"], 2)
        self.assertEqual(metrics["cas_partition"]["narrow_categories"][0]["value"], 1)
        self.assertEqual(metrics["cas_partition"]["broad_category"], "2")

    def test_ccf_rank(self):
        metrics = venue_table._row_to_metrics(
            {"journal": "J", "issn_l": "1111-1111", "ccf_rank": "A", "edition_year": "2025", "category": "AI"},
            {},
        )
        self.assertEqual(metrics["ccf_rank"]["value"], "A")


if __name__ == "__main__":
    unittest.main()
