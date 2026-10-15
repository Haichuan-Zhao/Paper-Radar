"""Offline tests for the EasyScholar adapter (no network, no secret key leaks)."""
import importlib.util
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from datetime import datetime, timezone

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "easyscholar.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("easyscholar", SCRIPT)
easyscholar = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = easyscholar
spec.loader.exec_module(easyscholar)


def response(code=200, all_rank=None, select_rank=None):
    return {"code": code, "msg": "ok", "data": {"officialRank": {"all": all_rank or {}, "select": select_rank or {}}}}


class TestNormalizers(unittest.TestCase):
    def test_quartile_variants(self):
        for raw, want in (("Q1", "Q1"), ("1", "Q1"), ("1区", "Q1"), ("一区", "Q1"), ("Q3", "Q3"), ("4", "Q4")):
            self.assertEqual(easyscholar._norm_quartile(raw), want, raw)

    def test_partition_variants(self):
        for raw, want in (("1", 1), ("2区", 2), ("中科院3区", 3), ("四区", 4)):
            self.assertEqual(easyscholar._norm_partition(raw), want, raw)
        self.assertIsNone(easyscholar._norm_partition("5区"))

    def test_ccf_variants(self):
        self.assertEqual(easyscholar._norm_ccf("A"), "A")
        self.assertEqual(easyscholar._norm_ccf("CCF-B"), "B")
        self.assertIsNone(easyscholar._norm_ccf("D"))


class TestMapToMetrics(unittest.TestCase):
    def test_full_mapping(self):
        raw = response(
            all_rank={"sciif": "10.7", "ccf": "A"},
            select_rank={"sci": "Q1", "sciUp": "1", "sciBase": "1", "sciUpTop": "是"},
        )
        metrics = easyscholar.map_to_metrics(raw, "Journal of Energy Storage")
        self.assertEqual(metrics["jcr_quartile"]["value"], "Q1")
        self.assertEqual(metrics["jif"]["value"], 10.7)
        self.assertEqual(metrics["cas_partition"]["value"], 1)
        self.assertTrue(metrics["cas_partition"]["top"])
        self.assertEqual(metrics["ccf_rank"]["value"], "A")
        self.assertTrue(all(not m["verified"] and m["source"] == "EasyScholar" for m in metrics.values()))

    def test_non_200_returns_empty(self):
        self.assertEqual(easyscholar.map_to_metrics(response(code=404), "X"), {})

    def test_missing_data_returns_empty(self):
        self.assertEqual(easyscholar.map_to_metrics({"code": 200}, "X"), {})


class TestSecretKey(unittest.TestCase):
    @patch.dict("os.environ", {}, clear=True)
    def test_env_takes_precedence(self):
        with patch.dict("os.environ", {"EASYSCHOLAR_SECRET_KEY": "env-key"}):
            self.assertEqual(easyscholar.resolve_secret_key({}), "env-key")

    def test_config_fallback(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(easyscholar.resolve_secret_key({"secret_key": "cfg-key"}), "cfg-key")

    def test_none_when_missing(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(easyscholar.resolve_secret_key({}))


class TestEnrich(unittest.TestCase):
    def test_enrich_injects_and_caches(self):
        records = [
            {"id": "doi:1", "title": "T1", "venue": {"name": "Journal of Energy Storage"}, "metrics": {}},
            {"id": "doi:2", "title": "T2", "venue": {"name": "Energy"}, "metrics": {}},
        ]
        fake = response(all_rank={"sciif": "10.7"}, select_rank={"sci": "Q1", "sciUp": "1"})
        with patch.object(easyscholar, "query_publication", return_value=fake) as mock_q, \
             patch.object(easyscholar, "time", sleep=None):
            report = easyscholar.enrich(records, "k", None, pause=0)
        self.assertEqual(report["journals_queried"], 2)
        self.assertEqual(report["papers_observed"], 2)
        self.assertEqual(report["papers_enriched"], 0)
        self.assertEqual(records[0]["metrics"]["jcr_quartile"]["value"], "Q1")
        self.assertEqual(records[1]["metrics"]["cas_partition"]["value"], 1)
        self.assertEqual(mock_q.call_count, 2)

    def test_enrich_survives_failure(self):
        records = [{"id": "doi:1", "title": "T", "venue": {"name": "Bad Journal"}, "metrics": {}}]
        with patch.object(easyscholar, "query_publication", side_effect=easyscholar.EasyScholarError("http_500")), \
             patch.object(easyscholar, "time", sleep=None):
            report = easyscholar.enrich(records, "k", None, pause=0)
        self.assertEqual(report["papers_enriched"], 0)
        self.assertEqual(len(report["failures"]), 1)
        self.assertEqual(records[0]["metrics"], {})

    def test_cache_avoids_requery(self):
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", encoding="utf-8", delete=False) as f:
            f.write(json.dumps({"schema_version": 2, "account": hashlib.sha256(b"k").hexdigest(),
                               "name": "Journal of Energy Storage", "retrieved_at": datetime.now(timezone.utc).isoformat(), "raw": response(
                all_rank={"sciif": "9"}, select_rank={"sci": "Q1", "sciUp": "2"})}, ensure_ascii=False) + "\n")
            cache = Path(f.name)
        records = [{"id": "doi:1", "title": "T", "venue": {"name": "Journal of Energy Storage"}, "metrics": {}}]
        with patch.object(easyscholar, "query_publication", return_value={}) as mock_q, \
             patch.object(easyscholar, "time", sleep=None):
            report = easyscholar.enrich(records, "k", cache, pause=0)
        self.assertEqual(report["journals_queried"], 0)
        self.assertEqual(records[0]["metrics"]["cas_partition"]["value"], 2)
        mock_q.assert_not_called()


if __name__ == "__main__":
    unittest.main()
