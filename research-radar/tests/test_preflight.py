"""Before-search checks require an actual choice without leaking credentials."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import config
import credentials
import institution_credentials
import preflight

spec = importlib.util.spec_from_file_location("preflight_driver", ROOT / "radar.py")
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "config.json"
        self.raw = {"topic": "Synthetic battery methods", "user_prompt": "Synthetic test only: battery SOH methods.",
                    "queries": ["battery SOH"], "date": {"from": "2026-01-01", "to": "2026-01-02"},
                    "sources": ["crossref", "openalex"], "easyscholar": {"enabled": True}}
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def profile(self):
        self.path.write_text(json.dumps(self.raw))
        return config.load_profile(self.path)

    def discover(self, script, p, kinds, dest, cap):
        dest.mkdir(parents=True)
        (dest / "candidates.jsonl").write_text("")
        return {"source": dest.name, "status": "complete", "exit": 0, "detail": "synthetic empty fixture", "stderr": ""}

    def test_missing_keys_stop_before_any_network_or_output(self):
        out = self.root / "run"
        with patch.object(driver, "_run_discovery") as discovery, patch("urllib.request.urlopen") as network, contextlib.redirect_stdout(io.StringIO()) as stream:
            code = driver.main(["run", "--profile", str(self.profile()["_source_path"]), "--out", str(out)])
        self.assertEqual(code, 3)
        self.assertFalse(out.exists())
        discovery.assert_not_called()
        network.assert_not_called()
        self.assertEqual(set(json.loads(stream.getvalue())["gaps"]), {"easyscholar", "openalex"})

    def test_explicit_choice_is_recorded_and_does_not_modify_user_document(self):
        profile = self.profile()
        original = self.path.read_bytes()
        out = self.root / "run"
        with patch.object(driver, "_run_discovery", side_effect=self.discover), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(driver.run(profile, out, None, False, True), 0)
        report = json.loads((out / "preflight.json").read_text())
        self.assertEqual(report["decision"], "continue_with_disclosed_gaps")
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(profile["easyscholar"]["enabled"])
        self.assertFalse(json.loads((out / "profile.json").read_text())["easyscholar"]["enabled"])

    def test_complete_keys_pass_but_are_not_claimed_valid_or_returned(self):
        key = "synthetic-own-key-never-print-485"
        with patch.dict(os.environ, {"EASYSCHOLAR_SECRET_KEY": key, "OPENALEX_API_KEY": key}), patch("urllib.request.urlopen") as network:
            result = preflight.check(self.profile())
        self.assertEqual(result["status"], "ready_for_discovery")
        self.assertNotIn(key, json.dumps(result))
        self.assertEqual({c["state"] for c in result["checks"] if c["id"] in {"easyscholar", "openalex"}}, {"configured_not_verified"})
        network.assert_not_called()

    def test_removed_key_is_detected_again_on_next_check(self):
        p = self.profile()
        with patch.dict(os.environ, {"EASYSCHOLAR_SECRET_KEY": "synthetic", "OPENALEX_API_KEY": "synthetic"}):
            self.assertFalse(preflight.check(p)["gaps"])
        self.assertEqual(set(preflight.check(p)["gaps"]), {"easyscholar", "openalex"})

    def test_disabled_optional_services_do_not_require_every_account(self):
        self.raw.update(sources=["crossref"], easyscholar={"enabled": False})
        self.assertEqual(preflight.check(self.profile())["gaps"], [])

    def test_broken_or_placeholder_keys_can_be_explicitly_skipped_for_this_run(self):
        for entry in ({"credentials_file": "missing.json"}, {"secret_key": "[REDACTED]"}):
            self.raw["easyscholar"] = {"enabled": True, **entry}
            p = self.profile()
            report = preflight.check(p)
            self.assertIn("easyscholar", report["gaps"])
            effective = preflight.effective_profile(p, report)
            self.assertFalse(effective["easyscholar"]["enabled"])
            self.assertIsNone(credentials.resolve_key(effective["easyscholar"], "easyscholar"))

    def test_requested_venue_gates_are_never_removed_to_allow_a_run(self):
        self.raw.update(filters={"include_only": {"min_jif": 10}}, easyscholar={"enabled": False})
        p = self.profile()
        report = preflight.check(p)
        self.assertIn("venue_gate_provider", report["gaps"])
        self.assertEqual(preflight.effective_profile(p, report)["filters"]["include_only"]["min_jif"], 10)

    def test_unpaywall_email_and_invalid_venue_file_have_specific_fallbacks(self):
        self.raw.update(fulltext_access={"unpaywall": {"enabled": True}}, venue_metrics_files=["missing.csv"])
        p = self.profile()
        report = preflight.check(p)
        self.assertTrue({"unpaywall_contact", "venue_table_1"} <= set(report["gaps"]))
        effective = preflight.effective_profile(p, report)
        self.assertEqual(effective["venue_metrics_files"], [])
        self.assertFalse(effective["fulltext_access"]["unpaywall"]["enabled"])

    def test_school_account_presence_is_checked_without_returning_email_or_password(self):
        raw = config.read_profile_document(ROOT / "USER_CONFIG.template.md")
        block = copy.deepcopy(raw["fulltext_access"]["institution"])
        block["enabled"] = True
        block["routing"].update(institution="Synthetic University", library_url="https://library.example.edu/",
                                login_url="https://login.example.edu/", allowed_domains=["library.example.edu", "login.example.edu"])
        self.raw["fulltext_access"] = {"institution": block}
        p = self.profile()
        self.assertIn("institution_account", preflight.check(p)["gaps"])
        username, password = "synthetic-user@example.edu", "synthetic-password-163"
        institution_credentials.save(self.root / "private/institution-accounts.json", "my-school", username, password)
        result = preflight.check(p)
        self.assertNotIn("institution_account", result["gaps"])
        self.assertNotIn(username, json.dumps(result))
        self.assertNotIn(password, json.dumps(result))

    def test_invalid_required_configuration_remains_blocked_even_with_continue_flag(self):
        self.raw["topic"] = ""
        self.path.write_text(json.dumps(self.raw))
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()), patch.object(driver, "_run_discovery") as discovery:
            self.assertEqual(driver.main(["preflight", "--profile", str(self.path)]), 2)
            self.assertEqual(driver.main(["run", "--profile", str(self.path), "--continue-with-gaps"]), 2)
        discovery.assert_not_called()


if __name__ == "__main__":
    unittest.main()
