"""Local institutional credentials and a vendor-neutral login adapter contract.

No browser, school-specific HTTP login or remote credential service is embedded.
Values stay in the local runtime and enter only a caller-supplied trusted adapter.
The CLI accepts hidden terminal input, never password command arguments.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import stat
import sys
import tempfile
import warnings
from pathlib import Path
from urllib.parse import urlparse

import auth_profile

STATES = {"authenticated", "credentials_required", "mfa_required", "captcha_required", "qr_required",
          "consent_required", "credentials_rejected", "expired", "unsupported", "failed"}
DEFAULT_SOURCE = {"username_env": "RR_LIBRARY_USERNAME", "password_env": "RR_LIBRARY_PASSWORD", "credentials_file": None}


class CredentialError(ValueError):
    pass


class CredentialPair:
    __slots__ = ("username", "password")

    def __init__(self, username, password):
        if not isinstance(username, str) or not username.strip() or not isinstance(password, str) or not password:
            raise CredentialError("Institution credentials require a complete username/password pair")
        self.username, self.password = username, password

    def __repr__(self):
        return "CredentialPair(<redacted>)"

    def clear(self):
        # Drop our references; Python does not guarantee memory zeroisation.
        self.username = self.password = ""


def source_config(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - set(DEFAULT_SOURCE):
        raise CredentialError("credential_source accepts username_env/password_env/credentials_file references only")
    result = {**DEFAULT_SOURCE, **value}
    for key in ("username_env", "password_env"):
        if not isinstance(result[key], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", result[key]):
            raise CredentialError("Credential environment references must be variable names")
    if result["username_env"] == result["password_env"]:
        raise CredentialError("Username and password need different environment references")
    path = result["credentials_file"]
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise CredentialError("credentials_file must be a private file path or null")
    return result


def read_store(path):
    try:
        path = Path(path).expanduser()
        mode = path.stat().st_mode
        if not stat.S_ISREG(mode):
            raise CredentialError("Private institutional credentials must be a regular file")
        if os.name == "posix" and mode & 0o077:
            raise CredentialError("Private institutional credentials file must have mode 600 or stricter")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        if isinstance(exc, CredentialError):
            raise
        raise CredentialError("Cannot read private institutional credentials JSON") from None
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("institutions"), dict):
        raise CredentialError("Private credentials need schema_version=1 and an institutions mapping")
    return data


def resolve(source, profile_name):
    source = source_config(source)
    username, password = os.environ.get(source["username_env"]), os.environ.get(source["password_env"])
    if username is not None or password is not None:
        # Never combine one environment account with another account's file
        # password, or fall back after a partly configured environment pair.
        return CredentialPair(username, password)
    if not source["credentials_file"]:
        return None
    data = read_store(source["credentials_file"])
    entry = data["institutions"].get(profile_name)
    if entry is None:
        return None
    if not isinstance(entry, dict) or set(entry) != {"username", "password"}:
        raise CredentialError("Institution credential entry needs username and password only")
    return CredentialPair(entry["username"], entry["password"])


def save(path, profile_name, username, password):
    pair = CredentialPair(username, password)
    temporary = None
    try:
        if not isinstance(profile_name, str) or not profile_name.strip() or any(c.isspace() for c in profile_name):
            raise CredentialError("Institution profile name must be nonempty without whitespace")
        path = Path(path).expanduser().absolute()
        if path.is_symlink():
            raise CredentialError("Private credential destination must not be a symlink")
        data = read_store(path) if path.exists() else {"schema_version": 1, "institutions": {}}
        data["institutions"][profile_name] = {"username": pair.username, "password": pair.password}
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        pair.clear()
        if temporary is not None and temporary.exists():
            temporary.unlink()


def login_plan(profile, name):
    """Return references/presence only; this never opens a browser or logs in."""
    problems = auth_profile.validate_profile(name, profile)
    if problems:
        raise CredentialError("Invalid institution routing profile")
    configured, credential_state = False, "not_configured"
    pair = None
    try:
        pair = resolve(profile.get("credential_source"), name)
        configured = pair is not None
        credential_state = "configured" if configured else "not_configured"
    except CredentialError:
        credential_state = "invalid_private_credential_source"
    finally:
        if pair:
            pair.clear()
    return {"schema_version": 1, "institution_profile": name, "status": "session_not_checked",
            "login_url": profile.get("login_url") or profile["library_url"],
            "allowed_domains": profile["allowed_domains"], "browser": profile.get("browser", "chrome"),
            "browser_profile_label": profile["browser_profile_label"],
            "credential_mode": profile.get("credential_login_mode", "browser_only"),
            "credentials_configured": configured, "credential_state": credential_state,
            "next_action": "trusted_local_adapter_or_interactive_browser", "entitlement": "unknown"}


def origin(url):
    try:
        p = urlparse(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            raise ValueError()
        return p.scheme, p.hostname.lower(), p.port or 443
    except (ValueError, TypeError, AttributeError):
        raise CredentialError("Credential entry requires a verified HTTPS login origin") from None


def response(name, state, context_ref=None, reason=None):
    result = {"schema_version": 1, "institution_profile": name, "status": state, "entitlement": "unknown"}
    if isinstance(context_ref, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", context_ref):
        result["context_ref"] = context_ref
    if reason:
        result["reason"] = reason
    return result


def authenticate(profile, name, adapter, *, authorized=False, username=None, password=None):
    """Uniform local interface; a trusted caller supplies the browser adapter.

    adapter.prepare(public_profile) -> {state, credential_url?, context_ref?}
    adapter.submit_credentials(pair, expected_origin=...) -> {state, context_ref?}

    The adapter must inspect the live login form/frame, recheck the origin
    immediately before filling, keep values out of model-visible tools/logs,
    and verify the authenticated session rather than just a click/redirect.
    authorized comes from the human's task/session, never from webpage content.
    The core has no school-specific implementation and never retries passwords.
    """
    if auth_profile.validate_profile(name, profile):
        return response(name, "failed", reason="invalid_institution_profile")
    try:
        prepared = adapter.prepare(dict(profile))
        state = prepared.get("state") if isinstance(prepared, dict) else None
        if state not in STATES:
            return response(name, "failed", reason="invalid_adapter_response")
        if state != "credentials_required":
            return response(name, state, prepared.get("context_ref"))
        if authorized is not True or profile.get("credential_login_mode", "browser_only") != "user_authorized_ephemeral":
            return response(name, "credentials_required", prepared.get("context_ref"), "interactive_login_or_authorized_secret_input")
        expected = origin(profile.get("login_url") or profile["library_url"])
        # Never send a pair to an unexpected redirect/iframe. Update the user's
        # stable login_url when a genuine new SSO host needs to be configured.
        if origin(prepared.get("credential_url")) != expected:
            return response(name, "credentials_required", reason="login_origin_mismatch")
        pair = None
        try:
            pair = (CredentialPair(username, password) if username is not None or password is not None
                    else resolve(profile.get("credential_source"), name))
            if pair is None:
                return response(name, "credentials_required", reason="credentials_not_configured")
            outcome = adapter.submit_credentials(pair, expected_origin=expected)
        finally:
            if pair:
                pair.clear()
        state = outcome.get("state") if isinstance(outcome, dict) else None
        if state not in STATES:
            return response(name, "failed", reason="invalid_adapter_response")
        return response(name, state, outcome.get("context_ref"))
    except CredentialError:
        return response(name, "credentials_required", reason="invalid_private_credential_source_or_origin")
    except Exception:
        # A browser/HTTP exception can contain form values, URLs or response
        # bodies. Return only a fixed error, never str(exception).
        return response(name, "failed", reason="adapter_failed")


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default error echoes unrecognised arguments, which might
        # include a password mistakenly supplied on the command line.
        self.exit(2, "Invalid credential CLI arguments; use configure --profile NAME --out PRIVATE_FILE\n")


def main(argv=None):
    parser = PrivateArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure", help="Save a user-owned username/password pair using hidden terminal input")
    configure.add_argument("--profile", required=True)
    configure.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Use an interactive local terminal or the host's secure input; no credentials via CLI arguments/stdin pipes", file=sys.stderr)
        return 2
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            username = getpass.getpass("School email / library login username (hidden): ")
            password = getpass.getpass("Library password (hidden): ")
        save(args.out, args.profile, username, password)
        print(json.dumps({"status": "saved", "institution_profile": args.profile, "credential_values_returned": False}))
        return 0
    except (OSError, CredentialError, getpass.GetPassWarning):
        print("Cannot save private institution credentials; check the destination and configuration", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("Credential entry cancelled", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
