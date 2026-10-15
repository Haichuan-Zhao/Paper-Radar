"""Offline tests for the deterministic filter "switch" semantics."""
import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "filters.py"
spec = importlib.util.spec_from_file_location("filters", SCRIPT)
filters = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = filters
spec.loader.exec_module(filters)


def record(**overrides):
    base = {
        "id": "doi:10.1234/test",
        "title": "A battery state of health estimation method",
        "abstract": "We generate synthetic data with a diffusion model.",
        "publication_type": "journal-article",
        "venue": {"name": "Journal of Energy Storage", "publisher": "Elsevier", "issn": ["2352-152X"]},
        "metrics": {},
    }
    base.update(overrides)
    return base


def cas_metric(value):
    return {"value": value, "verified": True, "year": 2025, "source_url": "https://example.com"}


class TestExcludeSwitches(unittest.TestCase):
    def test_excluded_type_dropped(self):
        result = filters.filter_record(record(publication_type="editorial"), {"include_only": {}, "exclude": {"types": ["editorial"]}})
        self.assertEqual(result["decision"], "exclude")

    def test_blocked_publisher_dropped(self):
        result = filters.filter_record(record(), {"include_only": {}, "exclude": {"publishers": ["elsevier"]}})
        self.assertEqual(result["decision"], "exclude")

    def test_title_keyword_dropped(self):
        result = filters.filter_record(record(), {"include_only": {}, "exclude": {"title_keywords": ["battery"]}})
        self.assertEqual(result["decision"], "exclude")


class TestCasSwitch(unittest.TestCase):
    def test_cas1_keeps(self):
        r = record(metrics={"cas_partition": cas_metric(1)})
        result = filters.filter_record(r, {"include_only": {"cas_partitions": [1]}, "exclude": {}})
        self.assertEqual(result["decision"], "keep")

    def test_cas2_excluded_when_only_cas1(self):
        r = record(metrics={"cas_partition": cas_metric(2)})
        result = filters.filter_record(r, {"include_only": {"cas_partitions": [1]}, "exclude": {}})
        self.assertEqual(result["decision"], "exclude")

    def test_missing_cas_needs_verification_not_dropped(self):
        result = filters.filter_record(record(), {"include_only": {"cas_partitions": [1]}, "exclude": {}})
        self.assertEqual(result["decision"], "needs_verification")

    def test_unverified_cas_needs_verification(self):
        r = record(metrics={"cas_partition": {"value": 1, "verified": False}})
        result = filters.filter_record(r, {"include_only": {"cas_partitions": [1]}, "exclude": {}})
        self.assertEqual(result["decision"], "needs_verification")


class TestWosSwitch(unittest.TestCase):
    def test_scie_keeps(self):
        r = record(metrics={"wos_indexes": {"value": ["SCIE"], "verified": True}})
        result = filters.filter_record(r, {"include_only": {"wos_indexes": ["SCIE"]}, "exclude": {}})
        self.assertEqual(result["decision"], "keep")

    def test_esci_excluded_when_scie_only(self):
        r = record(metrics={"wos_indexes": {"value": ["ESCI"], "verified": True}})
        result = filters.filter_record(r, {"include_only": {"wos_indexes": ["SCIE"]}, "exclude": {}})
        self.assertEqual(result["decision"], "exclude")

    def test_missing_wos_needs_verification(self):
        result = filters.filter_record(record(), {"include_only": {"wos_indexes": ["SCIE"]}, "exclude": {}})
        self.assertEqual(result["decision"], "needs_verification")


class TestNumericSwitch(unittest.TestCase):
    def test_min_jif_excludes_below(self):
        r = record(metrics={"jif": {"value": 3.0, "verified": True}})
        result = filters.filter_record(r, {"include_only": {"min_jif": 10}, "exclude": {}})
        self.assertEqual(result["decision"], "exclude")

    def test_min_jif_missing_needs_verification(self):
        result = filters.filter_record(record(), {"include_only": {"min_jif": 10}, "exclude": {}})
        self.assertEqual(result["decision"], "needs_verification")


class TestTypeSwitch(unittest.TestCase):
    def test_type_not_in_include_only_excluded(self):
        result = filters.filter_record(record(publication_type="journal-article"), {"include_only": {"types": ["proceedings-article"]}, "exclude": {}})
        self.assertEqual(result["decision"], "exclude")

    def test_proceedings_alias_matches_conference_paper(self):
        # The discovery scripts normalize proceedings-article -> conference-paper.
        result = filters.filter_record(record(publication_type="conference-paper"), {"include_only": {"types": ["proceedings-article"]}, "exclude": {}})
        self.assertEqual(result["decision"], "keep")


class TestPartition(unittest.TestCase):
    def test_partition_splits(self):
        records = [
            record(id="doi:10.1/keep", metrics={"cas_partition": cas_metric(1)}),
            record(id="doi:10.2/pending"),
            record(id="doi:10.3/excluded", publication_type="editorial"),
        ]
        filters.apply_filters(records, {"include_only": {"cas_partitions": [1]}, "exclude": {"types": ["editorial"]}})
        kept, pending, excluded = filters.partition(records)
        self.assertEqual(len(kept), 1)
        self.assertEqual(len(pending), 1)
        self.assertEqual(len(excluded), 1)


if __name__ == "__main__":
    unittest.main()
