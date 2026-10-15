"""Release checks distinguish dated evidence from a current verified edition."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import metric_registry as registry


class MetricRegistryTests(unittest.TestCase):
    def test_freshness_requires_matching_edition_and_nonfuture_timestamps(self):
        at = datetime(2026, 9, 4, tzinfo=timezone.utc)
        entry = registry.empty_source("jcr")
        entry.update(status="verified", latest_official_edition="test-edition",
                     local_data_edition="test-edition", official_checked_at=at.isoformat(),
                     data_refreshed_at=at.isoformat())
        self.assertTrue(registry.source_state("jcr", entry, at)["current"])
        for changed in (
            {"local_data_edition": "older-edition"},
            {"data_refreshed_at": (at + timedelta(days=1)).isoformat()},
            {"official_checked_at": (at - timedelta(days=2)).isoformat()},
            {"source_url": "https://clarivate.com.unrelated.example/"},
        ):
            with self.subTest(changed=changed):
                self.assertFalse(registry.source_state("jcr", {**entry, **changed}, at)["current"])


if __name__ == "__main__":
    unittest.main()
