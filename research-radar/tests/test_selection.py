"""Report selections bind versions and subsets without any network acquisition."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import assessment as a
import selection
from test_content_assessment import driver, paper, profile, review


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.output = self.root / "assessed"
        self.p = profile()
        first = paper()
        second = paper("arxiv:2601.00001v2")
        second.update(version=2, url="https://arxiv.org/abs/2601.00001v2", preprint={"server": "arxiv", "native_id": "2601.00001", "version": 2})
        self.rows = [first, second]
        self.summary = a.score(self.rows, [review(first, self.p)], self.p, self.output)
        self.catalog = json.loads((self.output / "selection-catalog.json").read_text())

    def test_stage_one_emits_numbers_but_no_download_selection(self):
        self.assertTrue(self.summary["selected_ids"])
        self.assertEqual(self.summary["workflow"]["download_status"], "awaiting_user_selection")
        self.assertEqual([i["number"] for i in self.catalog["items"]], [1, 2])
        self.assertFalse((self.output / "download-plan.json").exists())
        self.assertFalse(list(self.root.rglob("*.pdf")))
        text = (self.output / "reading-list.md").read_text()
        self.assertIn("|1|shortlist|", text)
        self.assertIn("|2|needs_content_review|", text)

    def test_selected_order_and_exact_versions_are_preserved(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("No network in selection")):
            result, rows = selection.plan(self.output, numbers="2、1")
        self.assertEqual(result["selected_ids"], [self.rows[1]["id"], self.rows[0]["id"]])
        self.assertEqual([r["version"] for r in rows], [2, 1])
        self.assertIsNone(result["items"][0]["scores"]["Q"])
        self.assertEqual(result["items"][1]["scores"]["Q"], 80)
        self.assertEqual(result["catalog_id"], self.catalog["catalog_id"])
        self.assertEqual(result["status"], "planned")

    def test_ids_never_expand_to_related_versions(self):
        result, rows = selection.plan(self.output, ids=self.rows[1]["id"])
        self.assertEqual(result["selected_ids"], [self.rows[1]["id"]])
        self.assertEqual(len(rows), 1)
        with self.assertRaises(selection.SelectionError):
            selection.plan(self.output, ids="arxiv:2601.00001")

    def test_unknown_duplicate_empty_or_implicit_selections_create_no_output(self):
        for numbers in ("", "1,", "0", "3", "1,1", "1-2", "all", "1.0"):
            with self.subTest(numbers=numbers), self.assertRaises(selection.SelectionError):
                selection.write(self.output, self.root / "chosen", numbers=numbers)
            self.assertFalse((self.root / "chosen").exists())
        for kwargs in ({}, {"numbers": "1", "ids": self.rows[0]["id"]}):
            with self.assertRaises(selection.SelectionError):
                selection.plan(self.output, **kwargs)

    def test_stale_catalog_reordered_rows_changed_identity_and_scores_are_rejected(self):
        original = a.load_jsonl(self.output / "ranked.jsonl")
        for field in ("order", "title", "version", "scores", "request"):
            changed = json.loads(json.dumps(original))
            if field == "order":
                changed.reverse()
            elif field == "scores":
                changed[0]["assessment"]["quality"]["score"] = 99
            elif field == "request":
                changed[0]["assessment"]["request_fingerprint"] = "different-request"
            else:
                changed[0][field] = "changed"
            a.write_jsonl(self.output / "ranked.jsonl", changed)
            with self.subTest(field=field), self.assertRaises(selection.SelectionError):
                selection.plan(self.output, numbers="1")

    def test_missing_or_modified_catalog_does_not_fall_back_to_recommendations(self):
        path = self.output / "selection-catalog.json"
        changed = dict(self.catalog, catalog_id="stale")
        path.write_text(json.dumps(changed))
        with self.assertRaises(selection.SelectionError):
            selection.plan(self.output, numbers="1")
        path.unlink()
        with self.assertRaises(selection.SelectionError):
            selection.plan(self.output, numbers="1")

    def test_plan_only_writes_chosen_metadata_and_never_overwrites(self):
        out = self.root / "chosen"
        result = selection.write(self.output, out, numbers="2", include_si=True)
        self.assertEqual({p.name for p in out.iterdir()}, {"download-plan.json", "selected-papers.jsonl"})
        self.assertEqual(result["selected_ids"], [self.rows[1]["id"]])
        self.assertTrue(result["include_si"])
        self.assertFalse(Path(result["destination"]).exists())
        self.assertEqual(len(a.load_jsonl(out / "selected-papers.jsonl")), 1)
        with self.assertRaises(selection.SelectionError):
            selection.write(self.output, out, numbers="1")

    def test_cli_creates_only_an_explicit_plan(self):
        out = self.root / "chosen"
        with contextlib.redirect_stdout(io.StringIO()), patch("urllib.request.urlopen", side_effect=AssertionError("No network")):
            code = driver.main(["select", "--assessment", str(self.output), "--numbers", "1", "--out", str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads((out / "download-plan.json").read_text())["selected_ids"], [self.rows[0]["id"]])
        self.assertFalse(list(out.rglob("*.pdf")))


if __name__ == "__main__":
    unittest.main()
