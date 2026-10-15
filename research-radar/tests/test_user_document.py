"""The single user document works through validation, access and the driver."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config
import fulltext_access as access
import notify

spec = importlib.util.spec_from_file_location("document_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class UserDocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.md"
        self.raw = config.read_profile_document(ROOT / "USER_CONFIG.template.md")
        self.raw.update(topic="Synthetic document validation", user_prompt="Find battery SOH methods for a synthetic fixture.",
                        queries=["battery SOH"], date={"from": "2026-01-01", "to": "2026-01-02"}, sources=["crossref"])
        self.raw["easyscholar"]["enabled"] = False

    def write(self, raw=None):
        self.path.write_text("# User input\n\n```json\n" + json.dumps(self.raw if raw is None else raw) + "\n```\n", encoding="utf-8")
        return self.path

    def institution(self):
        block = self.raw["fulltext_access"]["institution"]
        block["enabled"] = True
        block["routing"].update(institution="Example University", library_url="https://library.example.edu/resources",
                                login_url="https://sso.example.edu/login", allowed_domains=["library.example.edu", "sso.example.edu"])
        return block

    def test_empty_intake_does_not_search_an_example_topic(self):
        with self.assertRaises(config.ProfileError):
            config.load_profile(ROOT / "USER_CONFIG.template.md")

    def test_markdown_and_json_use_same_validation_and_relative_paths(self):
        self.raw["venue_metrics_files"] = ["private/ratings.csv"]
        md = config.load_profile(self.write())
        path = self.root / "config.json"
        path.write_text(json.dumps(self.raw))
        js = config.load_profile(path)
        md.pop("_source_path")
        js.pop("_source_path")
        self.assertEqual(md, js)
        self.assertEqual(md["venue_metrics_files"], [str((self.root / "private/ratings.csv").resolve())])

    def test_missing_multiple_and_invalid_json_blocks_are_not_guessed(self):
        secret = "synthetic-private-value-733"
        for text in ("# Plain prose", "```json\n{}\n```\n```json\n{}\n```", "```json\n" + secret + "\n```"):
            with self.subTest(text_kind=text[:8]):
                self.path.write_text(text)
                with self.assertRaises(config.ProfileError) as error:
                    config.read_profile_document(self.path)
                self.assertNotIn(secret, str(error.exception))

    def test_markdown_prose_is_not_executed(self):
        marker = self.root / "unexpected"
        self.write()
        self.path.write_text(self.path.read_text() + "\n```python\nopen(" + repr(str(marker)) + ", 'w').write('unexpected')\n```\n")
        self.assertEqual(config.load_profile(self.path)["topic"], self.raw["topic"])
        self.assertFalse(marker.exists())

    def test_inline_institution_needs_no_separate_routing_file(self):
        self.institution()
        loaded = config.load_profile(self.write())
        institution = loaded["fulltext_access"]["institution"]
        self.assertEqual(institution["routing"]["credential_source"]["credentials_file"],
                         str((self.root / "private/institution-accounts.json").resolve()))
        route = access.institution_route(loaded["fulltext_access"])
        self.assertEqual(route["profile"], "my-school")
        self.assertEqual((route["status"], route["entitlement"]), ("needs_session_check", "unknown"))

    def test_school_account_values_are_rejected_even_when_route_is_disabled(self):
        for key in ("username", "password", "cookie", "token"):
            raw = copy.deepcopy(self.raw)
            raw["fulltext_access"]["institution"]["routing"][key] = "synthetic-secret"
            with self.subTest(key=key), self.assertRaises(config.ProfileError) as error:
                config.load_profile(self.write(raw))
            self.assertNotIn("synthetic-secret", str(error.exception))

    def test_inline_and_external_routing_are_not_ambiguously_combined(self):
        self.raw["fulltext_access"]["institution"]["config_file"] = "other-auth.json"
        with self.assertRaises(config.ProfileError):
            config.load_profile(self.write())

    def test_invalid_login_domain_fails_validation_before_discovery(self):
        block = self.institution()
        block["routing"]["login_url"] = "https://unexpected.example.org/login"
        with self.assertRaises(config.ProfileError):
            config.load_profile(self.write())

    def test_obsolete_scoring_block_fails_instead_of_silently_ignoring_preferences(self):
        self.raw["scoring"] = {"venue_points": {"jcr": {"Q1": 100}}}
        with self.assertRaises(config.ProfileError) as error:
            config.load_profile(self.write())
        self.assertIn("assessment", str(error.exception))

    def test_inline_api_key_is_redacted_by_cli_for_markdown_too(self):
        self.raw["easyscholar"]["secret_key"] = "synthetic-key-do-not-print-819"
        result = subprocess.run([sys.executable, str(ROOT / "radar.py"), "validate", "--profile", str(self.write())],
                                capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.raw["easyscholar"]["secret_key"], result.stdout + result.stderr)
        self.assertIn("[REDACTED]", result.stdout)

    def test_optional_notification_reads_same_document_without_network(self):
        self.raw["automation"] = {"enabled": False, "notify": {"on": "never"}}
        self.assertEqual(notify.load_config(self.write())["automation"]["notify"]["on"], "never")

    def test_driver_runs_from_document_with_only_synthetic_discovery(self):
        self.institution()
        path = self.write()
        out = self.root / "run"
        def discover(script, profile, kinds, destination, cap):
            destination.mkdir(parents=True)
            row = {"id": "doi:10.1234/synthetic-document", "doi": "10.1234/synthetic-document", "title": "Synthetic battery SOH",
                   "url": "https://example.org/synthetic-document", "publication_type": "journal-article", "metrics": {}, "venue": {}}
            (destination / "candidates.jsonl").write_text(json.dumps(row) + "\n")
            return {"source": "crossref", "status": "complete", "exit": 0, "detail": "synthetic offline fixture", "stderr": ""}
        with patch.object(driver, "_run_discovery", side_effect=discover), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.main(["run", "--profile", str(path), "--out", str(out)]), 3)
            self.assertFalse(out.exists())
            self.assertEqual(driver.main(["run", "--profile", str(path), "--out", str(out), "--continue-with-gaps"]), 0)
        row = json.loads((out / "candidates.jsonl").read_text())
        self.assertEqual(row["fulltext_access"]["status"], "institution_route_available")
        saved = config.load_profile(out / "profile.json")
        self.assertEqual(saved["user_prompt"], self.raw["user_prompt"])
        self.assertFalse((out / "assessment").exists())
        self.assertEqual(json.loads((out / "preflight.json").read_text())["decision"], "continue_with_disclosed_gaps")


if __name__ == "__main__":
    unittest.main()
