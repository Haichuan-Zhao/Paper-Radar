"""Offline tests for profile config loading and validation."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "config.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("config", SCRIPT)
config = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = config
spec.loader.exec_module(config)


def write_profile(payload):
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
    json.dump(payload, handle)
    handle.close()
    return Path(handle.name)


def minimal(**overrides):
    base = {"topic": "测试主题", "queries": ["battery SOH"], "date": {"from": "2026-01-01", "to": "today"}}
    base.update(overrides)
    return base


class TestValidation(unittest.TestCase):
    def test_missing_topic_rejected(self):
        p = write_profile({"queries": ["x"], "date": {"from": "2026-01-01"}})
        with self.assertRaises(config.ProfileError):
            config.load_profile(p)

    def test_no_query_or_synonym_rejected(self):
        p = write_profile(minimal(queries=[], synonyms=[]))
        with self.assertRaises(config.ProfileError):
            config.load_profile(p)

    def test_invalid_cas_partition_rejected(self):
        p = write_profile(minimal(filters={"include_only": {"cas_partitions": [5]}}))
        with self.assertRaises(config.ProfileError):
            config.load_profile(p)

    def test_invalid_quartile_rejected(self):
        p = write_profile(minimal(filters={"include_only": {"jcr_quartiles": ["Q5"]}}))
        with self.assertRaises(config.ProfileError):
            config.load_profile(p)

    def test_date_order_rejected(self):
        p = write_profile(minimal(date={"from": "2026-06-01", "to": "2026-01-01"}))
        with self.assertRaises(config.ProfileError):
            config.load_profile(p)

    def test_today_resolves(self):
        p = write_profile(minimal())
        loaded = config.load_profile(p)
        self.assertNotEqual(loaded["date"]["to"], "today")
        self.assertGreaterEqual(loaded["date"]["to"], loaded["date"]["from"])

    def test_defaults_applied(self):
        p = write_profile(minimal())
        loaded = config.load_profile(p)
        self.assertEqual(loaded["count"], 20)
        self.assertIn("editorial", loaded["filters"]["exclude"]["types"])
        self.assertEqual(loaded["automation"]["enabled"], False)


class TestExpandQueries(unittest.TestCase):
    def test_dedup_preserves_order(self):
        loaded = config.load_profile(write_profile(minimal(queries=["a", "B"], synonyms=["a", "c"])))
        self.assertEqual(config.expand_queries(loaded), ["a", "B"])


if __name__ == "__main__":
    unittest.main()
