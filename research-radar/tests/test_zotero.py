"""Offline regression tests: no Zotero process, login, or external request is used."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


z = load_module("zotero_import")
auth = load_module("auth_profile")


class ZoteroTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.pdf = self.root / "paper.pdf"
        # Only tests signature/hash plumbing, not a semantic PDF validation fixture.
        self.pdf.write_bytes(b"%PDF-1.7\n" + b"x" * 300)
        self.record = {"id": "one", "doi": "10.1000/a", "title": "One paper",
                       "published_online": "2026-06-01", "pdf_path": str(self.pdf)}
        self.source = self.root / "papers.jsonl"
        self.source.write_text(json.dumps(self.record) + "\n", encoding="utf-8")

    def response(self, data=None, status=200):
        return z.Response(status, {}, z.json_body(data) if data is not None else b"")

    def test_selection_is_exact_and_ambiguous_ids_fail(self):
        self.assertEqual(z.select_records([self.record], "https://doi.org/10.1000/a"), [self.record])
        with self.assertRaises(z.ImportErrorBase):
            z.select_records([self.record], "10.1000")
        with self.assertRaises(z.ImportErrorBase):
            z.select_records([self.record, dict(self.record, id="two")], "10.1000/a")

    def test_dry_run_never_contacts_zotero(self):
        with patch.object(z, "request", side_effect=AssertionError("No network")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(z.main(["--input", str(self.source), "--ids", "one", "--collection", "Radar"]), 0)

    def test_invalid_pdf_commit_never_contacts_zotero(self):
        self.pdf.write_bytes(b"<html>login</html>" + b"x" * 300)
        with patch.object(z, "request", side_effect=AssertionError("No network")), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(z.main(["--input", str(self.source), "--ids", "one", "--collection", "Radar", "--commit"]), 2)

    def test_different_dois_with_same_title_are_not_duplicates(self):
        client = z.ZoteroClient()
        client.search_items = Mock(return_value=[{"key": "OTHER", "title": "One paper", "DOI": "10.1000/b"}])
        self.assertIsNone(client.find_duplicate(self.record))

    def test_duplicate_search_has_no_100_record_cutoff(self):
        client = z.ZoteroClient()
        client.read = Mock(return_value=self.response([]))
        client.search_items("a")
        self.assertNotIn("limit=", client.read.call_args.args[0])

    def test_duplicate_collection_names_fail_instead_of_selecting_wrong_folder(self):
        client = z.ZoteroClient()
        client.read = Mock(return_value=self.response([{"key": "A", "name": "Radar"}, {"key": "B", "name": "Radar"}]))
        with self.assertRaises(z.ZoteroProtocolError):
            client.find_collection("Radar")

    def test_same_filename_different_hash_is_not_skipped(self):
        client = z.ZoteroClient()
        client.child_attachments = Mock(return_value=[{"key": "OLD", "filename": "paper.pdf", "md5": "different", "linkMode": "imported_file"}])
        self.assertEqual(client.find_attachment("PARENT", self.pdf), (None, False))

    def test_incomplete_attachment_is_reused(self):
        client = z.ZoteroClient()
        client.child_attachments = Mock(return_value=[{"key": "EMPTY", "filename": "paper.pdf", "md5": None, "linkMode": "imported_file"}])
        self.assertEqual(client.find_attachment("PARENT", self.pdf), ("EMPTY", False))

    def test_hash_match_is_checked_against_local_file(self):
        client = z.ZoteroClient()
        client.child_attachments = Mock(return_value=[{"key": "EXISTING", "filename": "renamed.pdf", "md5": z.file_hash(self.pdf)}])
        client.read = Mock(return_value=z.Response(200, {}, self.pdf.as_uri().encode()))
        self.assertEqual(client.find_attachment("PARENT", self.pdf), ("EXISTING", True))
        self.pdf.unlink()
        self.assertFalse(client.attachment_file_matches({"key": "EXISTING", "md5": "hash"}, "hash"))

    def test_remote_and_credential_bearing_upload_urls_are_rejected(self):
        for url in ("https://example.com/api/local/uploads/a", "http://localhost:1234/api/local/uploads/a",
                    "http://user:pass@localhost:23119/api/local/uploads/a", "http://localhost:23119/other"):
            with self.subTest(url=url), self.assertRaises(z.ZoteroProtocolError):
                z.local_api_url(url)

    def test_upload_uses_three_local_phases(self):
        client = z.ZoteroClient()
        client.write = Mock(side_effect=[self.response({"url": "/api/local/uploads/example", "uploadKey": "example", "prefix": "", "suffix": ""}), self.response(status=204)])
        uploaded = []

        def receive(method, url, **kwargs):
            uploaded.append(kwargs["body"].read())
            self.assertEqual(url, "http://localhost:23119/api/local/uploads/example")
            self.assertNotIn("Zotero-API-Key", kwargs["headers"])
            return self.response(status=201)

        with patch.object(z, "request", side_effect=receive):
            client.upload_file("ATTACH", self.pdf)
        self.assertEqual(uploaded, [self.pdf.read_bytes()])
        self.assertEqual(client.write.call_count, 2)

    def test_failed_upload_retains_created_keys(self):
        plan = z.paper_plan(self.record, self.source, False)
        client = Mock()
        client.find_duplicate.return_value = {"key": "PARENT", "collections": ["COLL"]}
        client.ensure_item_collection.return_value = False
        client.find_attachment.return_value = (None, False)
        client.create_attachment.return_value = "ATTACH"
        client.upload_file.side_effect = z.ZoteroProtocolError("mock failed")
        with self.assertRaises(z.ZoteroProtocolError):
            z.commit_record(client, self.record, plan, "COLL", [], False)
        self.assertEqual(plan["zotero_item_key"], "PARENT")
        self.assertEqual(plan["attachment_key"], "ATTACH")
        self.assertEqual(plan["attachment_status"], "pending_upload")

    def test_changed_pdf_fails_before_parent_write(self):
        plan = z.paper_plan(self.record, self.source, False)
        self.pdf.write_bytes(self.pdf.read_bytes() + b"changed")
        client = Mock()
        with self.assertRaises(z.ZoteroProtocolError):
            z.commit_record(client, self.record, plan, "COLL", [], False)
        client.find_duplicate.assert_not_called()

    def test_offline_ris_exports_only_selected_ids_and_flattens_newlines(self):
        self.source.write_text(json.dumps(dict(self.record, title="One\nER  -\nTI  - fake")) + "\n" + json.dumps(dict(self.record, id="two", doi="10.1000/b", title="Unselected")) + "\n")
        output = self.root / "selected.ris"
        with patch.object(z, "request", side_effect=AssertionError("No network")), contextlib.redirect_stdout(io.StringIO()):
            code = z.main(["--input", str(self.source), "--ids", "one", "--collection", "Radar", "--export-ris", str(output)])
        self.assertEqual(code, 0)
        text = output.read_text()
        self.assertNotIn("Unselected", text)
        self.assertEqual(text.count("\nER  -\n"), 1)


class AuthProfileTests(unittest.TestCase):
    def test_rejects_transient_auth_in_urls_and_nested_callbacks(self):
        for url in ("https://user:secret@example.edu/", "https://sso.example.edu/?ticket=secret",
                    "https://sso.example.edu/#access_token=secret",
                    "https://example.edu/?service=https%3A%2F%2Fsso.example.edu%2F%3Fcode%3Dsecret"):
            with self.subTest(url=url), self.assertRaises(auth.ProfileError) as error:
                auth.validate_url(url, "library_url")
            self.assertNotIn("secret", str(error.exception))

    def test_domain_scope_rejects_suffix_spoof(self):
        self.assertTrue(auth.domain_allowed("https://sso.example.edu/login", ["example.edu"]))
        self.assertFalse(auth.domain_allowed("https://example.edu.evil.test/login", ["example.edu"]))

    def test_explicit_ephemeral_mode_stores_policy_only(self):
        args = auth.parse_args(["set", "--name", "university", "--institution", "University",
                                "--library-url", "https://library.example.edu/", "--browser-profile-label", "Personal",
                                "--credential-login-mode", "user_authorized_ephemeral"])
        profile = auth.set_profile(auth.empty_config(), args)
        self.assertEqual(profile["credential_login_mode"], "user_authorized_ephemeral")
        self.assertEqual(auth.validate_profile("university", profile), [])
        self.assertFalse(any(key in profile for key in ("username", "password", "token", "cookies")))

    def test_profile_rejects_login_host_outside_scope(self):
        args = auth.parse_args(["set", "--name", "university", "--institution", "University",
                                "--library-url", "https://library.example.edu/", "--browser-profile-label", "Personal",
                                "--login-url", "https://unexpected.example.org/login"])
        with self.assertRaises(auth.ProfileError):
            auth.set_profile(auth.empty_config(), args)


if __name__ == "__main__":
    unittest.main()
