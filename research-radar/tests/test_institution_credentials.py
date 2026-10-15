"""Private local credential and adapter checks; all accounts are synthetic."""
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
from unittest.mock import Mock, patch
import warnings

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import auth_profile as auth
import institution_credentials as login
import fulltext_access as access


def public_profile(**changes):
    return {"institution": "Example University", "library_url": "https://library.example.edu/resources",
            "login_url": "https://sso.example.edu/login", "allowed_domains": ["library.example.edu", "sso.example.edu"],
            "browser_profile_label": "Research", "secret_storage": "browser_password_manager_only",
            "credential_login_mode": "user_authorized_ephemeral", **changes}


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "private" / "accounts.json"
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.username, self.password = "synthetic-account-731", "synthetic-password-982"

    def source(self):
        return {"credentials_file": str(self.private)}

    def save(self, name="school"):
        login.save(self.private, name, self.username, self.password)

    def assert_private(self, value):
        text = value if isinstance(value, str) else json.dumps(value)
        self.assertNotIn(self.username, text)
        self.assertNotIn(self.password, text)

    def test_save_is_private_and_preserves_other_institutions(self):
        self.save()
        login.save(self.private, "second-school", "other-account", "other-password")
        if os.name == "posix":
            self.assertEqual(self.private.stat().st_mode & 0o777, 0o600)
            self.assertEqual(self.private.parent.stat().st_mode & 0o777, 0o700)
        pair = login.resolve(self.source(), "school")
        self.assertEqual((pair.username, pair.password), (self.username, self.password))
        self.assertIsNone(login.resolve(self.source(), "missing-school"))
        self.assertEqual(len(list(self.private.parent.iterdir())), 1)

    def test_pair_representation_hides_values_and_clear_drops_references(self):
        pair = login.CredentialPair(self.username, self.password)
        self.assert_private(repr(pair))
        pair.clear()
        self.assertEqual((pair.username, pair.password), ("", ""))

    def test_environment_pair_precedes_file_as_one_unit(self):
        self.save()
        with patch.dict(os.environ, {"RR_LIBRARY_USERNAME": "env-account", "RR_LIBRARY_PASSWORD": "env-password"}):
            pair = login.resolve(self.source(), "school")
        self.assertEqual((pair.username, pair.password), ("env-account", "env-password"))

    def test_partial_environment_never_uses_another_source_password(self):
        self.save()
        for values in ({"RR_LIBRARY_USERNAME": "env-account"}, {"RR_LIBRARY_PASSWORD": "env-password"},
                       {"RR_LIBRARY_USERNAME": "", "RR_LIBRARY_PASSWORD": "env-password"}):
            with self.subTest(values=list(values)), patch.dict(os.environ, values), self.assertRaises(login.CredentialError):
                login.resolve(self.source(), "school")

    def test_custom_environment_names_allow_distinct_institution_accounts(self):
        with patch.dict(os.environ, {"SCHOOL_A_USER": "A", "SCHOOL_A_PASS": "P1", "SCHOOL_B_USER": "B", "SCHOOL_B_PASS": "P2"}):
            pair = login.resolve({"username_env": "SCHOOL_B_USER", "password_env": "SCHOOL_B_PASS"}, "school-b")
        self.assertEqual((pair.username, pair.password), ("B", "P2"))

    def test_credential_sources_reject_inline_values_and_invalid_references(self):
        for source in ({"password": self.password}, {"username_env": "account name"},
                       {"username_env": "SAME", "password_env": "SAME"}, {"credentials_file": ""}, []):
            with self.subTest(source_type=type(source).__name__), self.assertRaises(login.CredentialError) as error:
                login.source_config(source)
            self.assert_private(str(error.exception))

    def test_missing_invalid_and_nonregular_files_return_only_fixed_errors(self):
        with self.assertRaises(login.CredentialError) as error:
            login.resolve(self.source(), "school")
        self.assert_private(str(error.exception))
        self.save()
        for text in (self.password, json.dumps({"schema_version": 2, "institutions": {}}),
                     json.dumps({"schema_version": 1, "institutions": {"school": {"username": self.username}}})):
            self.private.write_text(text)
            with self.assertRaises(login.CredentialError) as error:
                login.resolve(self.source(), "school")
            self.assert_private(str(error.exception))
        with self.assertRaises(login.CredentialError):
            login.read_store(self.private.parent)

    @unittest.skipUnless(os.name == "posix", "POSIX permission check")
    def test_shared_readable_private_file_is_rejected(self):
        self.save()
        self.private.chmod(0o644)
        with self.assertRaises(login.CredentialError):
            login.resolve(self.source(), "school")

    def test_saving_through_symlink_does_not_replace_target(self):
        self.save()
        link = self.root / "alias.json"
        link.symlink_to(self.private)
        before = self.private.read_bytes()
        with self.assertRaises(login.CredentialError):
            login.save(link, "school", "different", "different")
        self.assertEqual(self.private.read_bytes(), before)

    def test_plan_reports_presence_but_never_login_or_entitlement(self):
        self.save()
        p = public_profile(secret_storage="external_secret_reference", credential_source=self.source())
        result = login.login_plan(p, "school")
        self.assertTrue(result["credentials_configured"])
        self.assertEqual((result["status"], result["entitlement"]), ("session_not_checked", "unknown"))
        self.assert_private(result)
        self.private.write_text(self.password)
        result = login.login_plan(p, "school")
        self.assertEqual(result["credential_state"], "invalid_private_credential_source")
        self.assert_private(result)

    def adapter(self, **prepared):
        return Mock(prepare=Mock(return_value={"state": "credentials_required", "credential_url": "https://sso.example.edu/login", **prepared}),
                    submit_credentials=Mock(return_value={"state": "authenticated", "context_ref": "browser:research-1"}))

    def test_authorized_local_pair_reaches_adapter_then_is_cleared(self):
        adapter = self.adapter()
        observed = []
        def submit(pair, *, expected_origin):
            observed.append((pair.username, pair.password))
            self.assertEqual(expected_origin, ("https", "sso.example.edu", 443))
            return {"state": "authenticated", "context_ref": "browser:research-1", "password": pair.password}
        adapter.submit_credentials.side_effect = submit
        result = login.authenticate(public_profile(), "school", adapter, authorized=True,
                                    username=self.username, password=self.password)
        self.assertEqual(observed, [(self.username, self.password)])
        pair = adapter.submit_credentials.call_args.args[0]
        self.assertEqual((pair.username, pair.password), ("", ""))
        self.assertEqual((result["status"], result["entitlement"]), ("authenticated", "unknown"))
        self.assert_private(result)

    def test_private_file_pair_is_used_only_after_exact_login_origin_check(self):
        self.save()
        p = public_profile(secret_storage="external_secret_reference", credential_source=self.source())
        adapter = self.adapter()
        observed = []
        adapter.submit_credentials.side_effect = lambda pair, **kw: observed.append((pair.username, pair.password)) or {"state": "authenticated"}
        self.assertEqual(login.authenticate(p, "school", adapter, authorized=True)["status"], "authenticated")
        self.assertEqual(observed, [(self.username, self.password)])

    def test_unexpected_host_port_scheme_and_embedded_credentials_stop_before_secret_read(self):
        for url in ("https://sso.example.edu.evil.test/login", "https://library.example.edu/login",
                    "https://sso.example.edu:444/login", "http://sso.example.edu/login",
                    "https://user:password@sso.example.edu/login", None):
            adapter = self.adapter(credential_url=url)
            with self.subTest(url=url), patch.object(login, "resolve") as read:
                result = login.authenticate(public_profile(), "school", adapter, authorized=True)
            self.assertEqual(result["status"], "credentials_required")
            read.assert_not_called()
            adapter.submit_credentials.assert_not_called()

    def test_permission_and_browser_only_mode_stop_before_reading_credentials(self):
        for permission, mode in ((False, "user_authorized_ephemeral"), ("true", "user_authorized_ephemeral"), (True, "browser_only")):
            adapter = self.adapter()
            with self.subTest(permission=permission, mode=mode), patch.object(login, "resolve") as read:
                result = login.authenticate(public_profile(credential_login_mode=mode), "school", adapter, authorized=permission)
            self.assertEqual(result["status"], "credentials_required")
            read.assert_not_called()
            adapter.submit_credentials.assert_not_called()

    def test_existing_session_and_challenges_do_not_request_or_submit_credentials(self):
        for state in ("authenticated", "mfa_required", "captcha_required", "qr_required", "consent_required", "expired", "credentials_rejected"):
            adapter = self.adapter(state=state, context_ref="browser:research-1")
            with self.subTest(state=state), patch.object(login, "resolve") as read:
                result = login.authenticate(public_profile(), "school", adapter, authorized=True)
            self.assertEqual(result["status"], state)
            self.assertEqual(result["context_ref"], "browser:research-1")
            read.assert_not_called()
            adapter.submit_credentials.assert_not_called()

    def test_challenge_after_submission_is_returned_without_retry(self):
        adapter = self.adapter()
        adapter.submit_credentials.return_value = {"state": "mfa_required", "context_ref": "browser:research-1"}
        result = login.authenticate(public_profile(), "school", adapter, authorized=True, username=self.username, password=self.password)
        self.assertEqual(result["status"], "mfa_required")
        adapter.submit_credentials.assert_called_once()

    def test_adapter_exception_and_payload_cannot_echo_pair_or_cookies(self):
        adapter = self.adapter()
        adapter.submit_credentials.side_effect = RuntimeError(self.username + self.password)
        result = login.authenticate(public_profile(), "school", adapter, authorized=True, username=self.username, password=self.password)
        self.assertEqual(result["reason"], "adapter_failed")
        self.assert_private(result)
        self.assertEqual(adapter.submit_credentials.call_args.args[0].password, "")
        adapter = self.adapter(state="authenticated", context_ref="https://sso.example.edu/?token=private", cookies="secret")
        result = login.authenticate(public_profile(), "school", adapter, authorized=True)
        self.assertNotIn("context_ref", result)
        self.assertNotIn("cookies", result)

    def test_invalid_adapter_result_is_not_success(self):
        for value in (None, {"state": "clicked_login"}, {"state": "ok"}):
            adapter = self.adapter()
            adapter.prepare.return_value = value
            self.assertEqual(login.authenticate(public_profile(), "school", adapter)["status"], "failed")
            adapter.submit_credentials.assert_not_called()

    def test_malformed_and_missing_pairs_do_not_submit(self):
        for values in ({}, {"username": self.username}, {"username": self.username, "password": ""}):
            adapter = self.adapter()
            result = login.authenticate(public_profile(), "school", adapter, authorized=True, **values)
            self.assertEqual(result["status"], "credentials_required")
            adapter.submit_credentials.assert_not_called()

    def test_public_profile_and_fulltext_route_carry_references_only(self):
        self.save()
        p = public_profile(secret_storage="external_secret_reference", credential_source=self.source())
        config = {"schema_version": 1, "default_profile": "school", "profiles": {"school": p}}
        path = self.root / "auth.json"
        auth.atomic_write(path, config)
        route = access.institution_route(access.settings({"institution": {"enabled": True, "config_file": str(path), "profile": "school"}}))
        self.assertEqual(route["credential_source"]["credentials_file"], str(self.private))
        self.assert_private(route)
        self.assertTrue(auth.validate_profile("school", dict(p, password=self.password)))

    def test_hidden_input_cli_saves_without_returning_values(self):
        output = io.StringIO()
        with patch.object(login.sys.stdin, "isatty", return_value=True), patch.object(login.getpass, "getpass", side_effect=[self.username, self.password]), contextlib.redirect_stdout(output):
            code = login.main(["configure", "--profile", "school", "--out", str(self.private)])
        self.assertEqual(code, 0)
        self.assert_private(output.getvalue())
        self.assertEqual(login.resolve(self.source(), "school").password, self.password)

    def test_hidden_input_failure_never_falls_back_to_echo(self):
        output = io.StringIO()
        def unavailable(prompt):
            warnings.warn("No hidden input", getpass.GetPassWarning)
        with patch.object(login.sys.stdin, "isatty", return_value=True), patch.object(login.getpass, "getpass", side_effect=unavailable), contextlib.redirect_stderr(output):
            code = login.main(["configure", "--profile", "school", "--out", str(self.private)])
        self.assertEqual(code, 2)
        self.assertFalse(self.private.exists())

    def test_credential_cli_rejects_password_arguments_without_echoing_them(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "institution_credentials.py"), "configure", "--profile", "school",
                                 "--out", str(self.private), "--password", self.password], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assert_private(result.stdout + result.stderr)

    def test_credential_cli_rejects_piped_stdin(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "institution_credentials.py"), "configure", "--profile", "school",
                                 "--out", str(self.private)], input=self.password, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assert_private(result.stdout + result.stderr)
        self.assertFalse(self.private.exists())

    def test_auth_cli_resolves_relative_private_path_and_plan_works_in_other_cwd(self):
        self.save()
        config = self.root / "auth.json"
        command = [sys.executable, str(SCRIPTS / "auth_profile.py"), "--config", str(config)]
        result = subprocess.run(command + ["set", "--name", "school", "--institution", "Example University", "--library-url",
                                "https://library.example.edu/resources", "--login-url", "https://sso.example.edu/login",
                                "--allowed-domain", "library.example.edu", "--allowed-domain", "sso.example.edu",
                                "--browser-profile-label", "Research", "--credentials-file", "private/accounts.json",
                                "--credential-login-mode", "user_authorized_ephemeral"], capture_output=True, text=True, cwd=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_private(result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["profile_data"]["credential_source"]["credentials_file"], str(self.private.resolve()))
        result = subprocess.run(command + ["plan"], capture_output=True, text=True, cwd=self.private.parent)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["credentials_configured"])
        self.assert_private(result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
