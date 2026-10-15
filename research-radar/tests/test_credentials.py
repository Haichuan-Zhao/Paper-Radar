"""User-owned API key input, redaction and preservation; synthetic secrets only."""
import contextlib
import getpass
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import credentials as c


class KeyConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private" / "api-keys.json"
        self.key = "synthetic-key-should-stay-private-917"

    def test_key_roundtrip_preserves_other_service_and_private_permissions(self):
        c.save_key(self.path, "openalex", "other-synthetic-key")
        c.save_key(self.path, "easyscholar", self.key)
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(c.resolve_key({"credentials_file": str(self.path)}, "easyscholar"), self.key)
            self.assertEqual(c.resolve_key({"credentials_file": str(self.path)}, "openalex"), "other-synthetic-key")
        if os.name == "posix":
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(len(list(self.path.parent.iterdir())), 1)

    def test_hidden_input_saves_without_echo_or_network(self):
        output = io.StringIO()
        with patch.object(c.sys.stdin, "isatty", return_value=True), patch.object(c.getpass, "getpass", return_value=self.key), contextlib.redirect_stdout(output):
            code = c.main(["configure", "--service", "easyscholar", "--out", str(self.path)])
        self.assertEqual(code, 0)
        self.assertNotIn(self.key, output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["credential_values_returned"])
        self.assertEqual(json.loads(self.path.read_text())["easyscholar"]["secret_key"], self.key)

    def test_cannot_hide_input_stops_before_writing(self):
        def unavailable(*args):
            warnings.warn("Cannot hide", getpass.GetPassWarning)
        with patch.object(c.sys.stdin, "isatty", return_value=True), patch.object(c.getpass, "getpass", side_effect=unavailable), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(c.main(["configure", "--service", "easyscholar", "--out", str(self.path)]), 2)
        self.assertFalse(self.path.exists())

    def test_stdin_pipe_cannot_configure_a_key(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/credentials.py"), "configure", "--service", "easyscholar", "--out", str(self.path)],
                                input=self.key, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(self.key, result.stdout + result.stderr)
        self.assertFalse(self.path.exists())

    def test_mistaken_secret_argument_is_not_echoed(self):
        result = subprocess.run([sys.executable, str(ROOT / "scripts/credentials.py"), "configure", "--service", "easyscholar", "--out", str(self.path), "--key", self.key],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(self.key, result.stdout + result.stderr)
        self.assertFalse(self.path.exists())

    def test_invalid_existing_json_is_not_overwritten_or_echoed(self):
        self.path.parent.mkdir()
        self.path.write_text(self.key)
        with self.assertRaises(c.CredentialError) as error:
            c.save_key(self.path, "easyscholar", "new-synthetic-key")
        self.assertNotIn(self.key, str(error.exception))
        self.assertEqual(self.path.read_text(), self.key)

    def test_blank_keys_and_symlinks_do_not_write(self):
        for value in ("", " ", None):
            with self.subTest(value=value), self.assertRaises(c.CredentialError):
                c.save_key(self.path, "easyscholar", value)
        self.path.parent.mkdir()
        target = self.path.parent / "target.json"
        target.write_text("{}")
        self.path.symlink_to(target)
        with self.assertRaises(c.CredentialError):
            c.save_key(self.path, "easyscholar", self.key)
        self.assertEqual(target.read_text(), "{}")


if __name__ == "__main__":
    unittest.main()
