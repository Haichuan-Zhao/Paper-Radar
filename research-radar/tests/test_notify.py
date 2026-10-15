"""Offline tests for the notification module: no network, SMTP, osascript, or file side effects."""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("notify", ROOT / "scripts" / "notify.py")
notify = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = notify
SPEC.loader.exec_module(notify)


def config(notify_block=None):
    """Build a profile config wrapping an ``automation.notify`` block."""
    return {"automation": {"notify": notify_block or {}}}


def summary(**overrides):
    """Build a representative run summary."""
    base = {
        "run_dir": "/tmp/run",
        "topic": "topic X",
        "started_at": "2026-09-05T00:00:00+00:00",
        "finished_at": "2026-09-05T00:10:00+00:00",
        "status": "ok",
        "shortlist": [
            {"id": "1", "title": "Paper One", "doi": "10.1000/one", "url": "", "total": 88, "status": "shortlist"},
            {"id": "2", "title": "Paper Two", "doi": "10.1000/two", "url": "", "total": 80, "status": "shortlist"},
        ],
        "watchlist_count": 3,
        "error_count": 0,
        "errors": [],
    }
    base.update(overrides)
    return base


def http_response(status=200):
    """A context-manager mock that behaves like a urllib response."""
    response = Mock()
    response.getcode.return_value = status
    response.status = status
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    return response


class NotifyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_json(self, name, data):
        path = self.root / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def argv_for(self, cfg, summ, dry_run=False, run_dir=None):
        cfg_path = self.write_json("config.json", cfg)
        summ_path = self.write_json("summary.json", summ)
        run_dir = run_dir or self.root
        argv = ["--config", str(cfg_path), "--summary", str(summ_path), "--run-dir", str(run_dir)]
        if dry_run:
            argv.append("--dry-run")
        return argv

    def invoke(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = notify.main(argv)
        return code, json.loads(out.getvalue())

    def run_main(self, cfg, summ, dry_run=False, run_dir=None):
        return self.invoke(self.argv_for(cfg, summ, dry_run, run_dir))

    def channel(self, result, name):
        return [c for c in result["channels"] if c["channel"] == name][0]

    # --- policy gating -------------------------------------------------

    def test_policy_never_sends_nothing(self):
        cfg = config({"on": "never", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("no net")):
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        self.assertEqual(result["on"], "never")
        self.assertFalse(result["sent"])
        self.assertEqual(result["channels"], [])

    def test_policy_new_shortlist_skips_when_empty(self):
        cfg = config({"on": "new_shortlist", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("no net")):
            code, result = self.run_main(cfg, summary(shortlist=[]))
        self.assertEqual(code, 0)
        self.assertFalse(result["sent"])
        self.assertEqual(result["channels"], [])

    def test_policy_new_shortlist_sends_when_nonempty(self):
        cfg = config({"on": "new_shortlist", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)):
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        self.assertTrue(result["sent"])

    def test_policy_errors_sends_on_error_count(self):
        cfg = config({"on": "errors", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)):
            code, result = self.run_main(cfg, summary(shortlist=[], error_count=2))
        self.assertEqual(code, 0)
        self.assertTrue(result["sent"])

    def test_policy_errors_sends_on_error_status(self):
        cfg = config({"on": "errors", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)):
            code, result = self.run_main(cfg, summary(shortlist=[], status="partial-with-errors"))
        self.assertTrue(result["sent"])

    def test_policy_errors_stays_silent_without_errors(self):
        cfg = config({"on": "errors", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("no net")):
            code, result = self.run_main(cfg, summary(shortlist=[], error_count=0, status="ok"))
        self.assertEqual(code, 0)
        self.assertFalse(result["sent"])
        self.assertEqual(result["channels"], [])

    def test_policy_always_sends_even_with_empty_shortlist(self):
        cfg = config({"on": "always", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)):
            code, result = self.run_main(cfg, summary(shortlist=[]))
        self.assertEqual(code, 0)
        self.assertTrue(result["sent"])

    # --- webhook -------------------------------------------------------

    def test_webhook_success_records_sent_with_json_content_type(self):
        cfg = config({"on": "always", "webhook": {"enabled": True, "url": "https://example.com/hook", "method": "POST", "headers": {}}})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)) as urlopen:
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        webhook = self.channel(result, "webhook")
        self.assertEqual(webhook["status"], "sent")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Content-type"), "application/json")
        self.assertEqual(request.get_method(), "POST")

    def test_webhook_non_2xx_records_failed_but_exits_zero(self):
        cfg = config({"on": "always", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        error = urllib.error.HTTPError("https://example.com/hook", 500, "err", {}, None)
        with patch.object(notify.urllib.request, "urlopen", side_effect=error):
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        webhook = self.channel(result, "webhook")
        self.assertEqual(webhook["status"], "failed")
        self.assertFalse(result["sent"])

    # --- email ---------------------------------------------------------

    def test_email_attempted_when_password_present(self):
        cfg = config({"on": "always", "email": {"enabled": True, "smtp_host": "smtp.example.com", "smtp_port": 587,
                                                 "starttls": True, "from": "a@example.com", "to": ["b@example.com"]}})
        with patch.dict(os.environ, {"RR_SMTP_PASSWORD": "secret", "RR_SMTP_USER": "user"}, clear=False):
            with patch.object(notify.smtplib, "SMTP") as smtp:
                code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        smtp.assert_called_once()
        email = self.channel(result, "email")
        self.assertEqual(email["status"], "sent")
        self.assertNotIn("secret", json.dumps(result))

    def test_email_skipped_when_password_missing(self):
        cfg = config({"on": "always", "email": {"enabled": True, "smtp_host": "smtp.example.com",
                                                 "from": "a@example.com", "to": ["b@example.com"]}})
        with patch.dict(os.environ, {"RR_SMTP_PASSWORD": "", "RR_SMTP_USER": ""}, clear=False):
            with patch.object(notify.smtplib, "SMTP", side_effect=AssertionError("no smtp")):
                code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        email = self.channel(result, "email")
        self.assertEqual(email["status"], "skipped")
        self.assertEqual(email["detail"], "missing RR_SMTP_PASSWORD")

    # --- desktop -------------------------------------------------------

    def test_desktop_noop_on_non_darwin(self):
        cfg = config({"on": "always", "desktop": True})
        with patch("sys.platform", "linux"), patch.object(notify.subprocess, "run", side_effect=AssertionError("no osascript")):
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        desktop = self.channel(result, "desktop")
        self.assertEqual(desktop["status"], "skipped")
        self.assertEqual(desktop["detail"], "unsupported_platform")

    def test_desktop_attempted_on_darwin(self):
        cfg = config({"on": "always", "desktop": True})
        with patch("sys.platform", "darwin"), patch.object(notify.subprocess, "run", return_value=Mock(returncode=0)) as run:
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        run.assert_called_once()
        command = run.call_args.args[0]
        self.assertEqual(command[0], "osascript")
        self.assertIn("display notification", command[2])
        desktop = self.channel(result, "desktop")
        self.assertEqual(desktop["status"], "sent")

    # --- dry-run -------------------------------------------------------

    def test_dry_run_performs_no_side_effects(self):
        cfg = config({"on": "always",
                      "webhook": {"enabled": True, "url": "https://example.com/hook"},
                      "email": {"enabled": True, "smtp_host": "smtp.example.com", "from": "a@example.com", "to": ["b@example.com"]},
                      "desktop": True,
                      "log_file": "runs/notify.log"})
        argv = self.argv_for(cfg, summary(), dry_run=True)
        with patch.dict(os.environ, {"RR_SMTP_PASSWORD": "secret"}, clear=False):
            with patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("no net")) as urlopen, \
                 patch.object(notify.smtplib, "SMTP", side_effect=AssertionError("no smtp")) as smtp, \
                 patch.object(notify.subprocess, "run", side_effect=AssertionError("no osascript")) as subprocess_run, \
                 patch("builtins.open", side_effect=AssertionError("no file write")) as open_mock:
                code, result = self.invoke(argv)
        self.assertEqual(code, 0)
        self.assertTrue(result["dry_run"])
        self.assertIn("body", result)
        self.assertIn("topic X", result["body"])
        urlopen.assert_not_called()
        smtp.assert_not_called()
        subprocess_run.assert_not_called()
        open_mock.assert_not_called()

    # --- subject/body --------------------------------------------------

    def test_subject_and_body_contain_topic_and_top_title(self):
        summ = summary()
        subject = notify.build_subject(summ)
        body = notify.build_body(summ)
        self.assertIn("topic X", subject)
        self.assertIn("topic X", body)
        self.assertIn("Paper One", body)
        self.assertIn("https://doi.org/10.1000/one", body)

    # --- log file ------------------------------------------------------

    def test_log_file_appends_json_line_with_sent_channels(self):
        cfg = config({"on": "always",
                      "webhook": {"enabled": True, "url": "https://example.com/hook"},
                      "log_file": "runs/notify.log"})
        with patch.object(notify.urllib.request, "urlopen", return_value=http_response(200)):
            code, result = self.run_main(cfg, summary())
        self.assertEqual(code, 0)
        log_path = self.root / "runs" / "notify.log"
        self.assertTrue(log_path.exists())
        lines = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["sent_to"], ["webhook"])
        self.assertEqual(lines[0]["topic"], "topic X")
        self.assertIn("subject", lines[0])
        self.assertIn("at", lines[0])

    # --- error handling ------------------------------------------------

    def test_bad_config_exits_2(self):
        bad = self.root / "bad.json"
        bad.write_text("{invalid json", encoding="utf-8")
        summ_path = self.write_json("summary.json", summary())
        argv = ["--config", str(bad), "--summary", str(summ_path), "--run-dir", str(self.root)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = notify.main(argv)
        self.assertEqual(code, 2)

    def test_malformed_summary_does_not_crash(self):
        cfg = config({"on": "new_shortlist", "webhook": {"enabled": True, "url": "https://example.com/hook"}})
        bad = self.root / "summary.json"
        bad.write_text("{not json", encoding="utf-8")
        argv = ["--config", str(self.write_json("config.json", cfg)), "--summary", str(bad), "--run-dir", str(self.root)]
        with patch.object(notify.urllib.request, "urlopen", side_effect=AssertionError("no net")):
            code, result = self.invoke(argv)
        self.assertEqual(code, 0)
        self.assertFalse(result["sent"])


if __name__ == "__main__":
    unittest.main()
