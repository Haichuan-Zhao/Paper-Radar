#!/usr/bin/env python3
"""Manage non-secret Research Radar browser authentication profiles."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse
import re


SCHEMA_VERSION = 1
FORBIDDEN_KEYS = {
    "username",
    "user_name",
    "account",
    "password",
    "passwd",
    "secret",
    "token",
    "cookie",
    "cookies",
    "session",
    "session_token",
    "otp",
    "api_key",
    "apikey",
    "credential",
    "credentials",
    "access_token", "refresh_token", "authorization", "client_secret",
    "recovery_code", "sessionid", "session_id", "samlresponse", "ticket",
}
TRANSIENT_URL_KEYS = FORBIDDEN_KEYS | {
    "code", "samlrequest", "assertion", "jwt", "auth", "signature", "sig",
    "x_amz_signature", "x_amz_credential", "x_amz_security_token",
    "x_goog_signature", "x_goog_credential", "key_pair_id",
    "accesskey", "secretkey", "sessionkey",
}


class ProfileError(ValueError):
    pass


def default_config_path() -> Path:
    custom = os.environ.get("RESEARCH_RADAR_CONFIG_DIR")
    root = Path(custom).expanduser() if custom else Path.home() / ".config" / "research-radar"
    return root / "auth-profiles.json"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_config() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "default_profile": None, "profiles": {}}


def validate_no_secrets(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().casefold().replace("-", "_")
            if normalized in FORBIDDEN_KEYS:
                raise ProfileError(f"Secret-bearing field is forbidden at {path}.{key}")
            validate_no_secrets(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            validate_no_secrets(child, f"{path}[{index}]")


def validate_url(value: str | None, field: str, required: bool = False) -> str | None:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ProfileError(f"{field} is required")
        return None
    parsed = urlparse(text)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname:
        raise ProfileError(f"{field} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ProfileError(f"{field} must not contain embedded credentials")
    for key, child in parse_qsl(parsed.query, keep_blank_values=True) + parse_qsl(parsed.fragment, keep_blank_values=True):
        normalized = key.casefold().replace("-", "_")
        if normalized in TRANSIENT_URL_KEYS:
            raise ProfileError(f"{field} must be a stable entry URL without authentication parameters")
        if child.startswith(("https://", "http://")):
            validate_url(child, f"{field} nested URL")
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ProfileError(f"{field} must use HTTPS for non-local hosts")
    return text


def normalize_domain(value: str) -> str:
    text = value.strip().casefold()
    if not text:
        raise ProfileError("allowed domains must not be empty")
    if "://" in text:
        validate_url(text, "allowed domain URL")
        parsed = urlparse(text)
        text = parsed.hostname or ""
    text = text.removeprefix("*.").rstrip(".")
    try:
        text = text.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ProfileError("Invalid allowed domain") from exc
    if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", text):
        raise ProfileError("Invalid allowed domain")
    return text


def domain_allowed(url: str, allowed_domains: list[str]) -> bool:
    """A routing aid; the browser must still verify the expected live login page."""
    host = urlparse(validate_url(url, "URL", required=True) or "").hostname or ""
    host = normalize_domain(host)
    return any(host == domain or host.endswith("." + domain) for domain in allowed_domains)


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return empty_config()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfileError(f"Cannot read profile config {path}: {exc}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != SCHEMA_VERSION:
        raise ProfileError("Unsupported or missing auth-profile schema_version")
    if not isinstance(config.get("profiles"), dict):
        raise ProfileError("profiles must be an object")
    validate_no_secrets(config)
    problems = []
    for name, profile in config["profiles"].items():
        problems.extend(validate_profile(name, profile))
    if config.get("default_profile") and config["default_profile"] not in config["profiles"]:
        problems.append("default_profile does not exist")
    if problems:
        raise ProfileError("; ".join(problems))
    return config


def atomic_write(path: Path, value: dict[str, Any]) -> None:
    validate_no_secrets(value)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False)
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def set_profile(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    name = args.name.strip()
    if not name or any(char.isspace() for char in name):
        raise ProfileError("Profile name must be non-empty and contain no whitespace")
    profiles = config["profiles"]
    existing = profiles.get(name)
    existing = dict(existing) if isinstance(existing, dict) else {}
    institution = args.institution if args.institution is not None else existing.get("institution")
    library_url = args.library_url if args.library_url is not None else existing.get("library_url")
    browser_label = (
        args.browser_profile_label
        if args.browser_profile_label is not None
        else existing.get("browser_profile_label")
    )
    if not str(institution or "").strip():
        raise ProfileError("--institution is required for a new profile")
    if not str(browser_label or "").strip():
        raise ProfileError("--browser-profile-label is required for a new profile")

    allowed_domains = existing.get("allowed_domains", [])
    if args.allowed_domain:
        allowed_domains = [normalize_domain(value) for value in args.allowed_domain]
    if not allowed_domains:
        library_host = urlparse(validate_url(library_url, "library_url", required=True) or "").hostname
        allowed_domains = [library_host] if library_host else []

    auto_confirm = existing.get("auto_confirm_saved_login", False)
    if args.auto_confirm_saved_login is not None:
        auto_confirm = args.auto_confirm_saved_login

    created_at = existing.get("created_at") or now_iso()
    from institution_credentials import source_config, CredentialError
    source = existing.get("credential_source")
    supplied = {key: getattr(args, key, None) for key in ("username_env", "password_env", "credentials_file")}
    if any(value is not None for value in supplied.values()):
        try:
            source = source_config({**(source or {}), **{key: value for key, value in supplied.items() if value is not None}})
            if source["credentials_file"]:
                path = Path(source["credentials_file"]).expanduser()
                source["credentials_file"] = str((Path(args.config).expanduser().resolve().parent / path).resolve())
        except CredentialError as exc:
            raise ProfileError(str(exc)) from None
    profile = {
        "institution": str(institution).strip(),
        "library_url": validate_url(library_url, "library_url", required=True),
        "login_url": validate_url(
            args.login_url if args.login_url is not None else existing.get("login_url"),
            "login_url",
        ),
        "session_probe_url": validate_url(
            args.session_probe_url
            if args.session_probe_url is not None
            else existing.get("session_probe_url"),
            "session_probe_url",
        ),
        "allowed_domains": sorted(set(allowed_domains)),
        "browser": args.browser or existing.get("browser", "chrome"),
        "browser_profile_label": str(browser_label).strip(),
        "reuse_authenticated_tabs": True,
        "auto_confirm_saved_login": bool(auto_confirm),
        "secret_storage": "external_secret_reference" if source else "browser_password_manager_only",
        "credential_login_mode": args.credential_login_mode or existing.get("credential_login_mode", "browser_only"),
        "created_at": created_at,
        "updated_at": now_iso(),
    }
    if source:
        profile["credential_source"] = source
    problems = validate_profile(name, profile)
    if problems:
        raise ProfileError("; ".join(problems))
    profiles[name] = profile
    if args.make_default or not config.get("default_profile"):
        config["default_profile"] = name
    return profile


def validate_profile(name: str, profile: Any) -> list[str]:
    problems: list[str] = []
    if not isinstance(profile, dict):
        return [f"{name}: profile is not an object"]
    try:
        validate_no_secrets(profile, f"profiles.{name}")
    except ProfileError as exc:
        problems.append(str(exc))
    for field in ("institution", "library_url", "browser_profile_label"):
        if not str(profile.get(field) or "").strip():
            problems.append(f"{name}: missing {field}")
    if profile.get("secret_storage") not in {"browser_password_manager_only", "external_secret_reference"}:
        problems.append(f"{name}: unsupported secret_storage")
    if profile.get("credential_source") is not None:
        from institution_credentials import source_config, CredentialError
        try:
            source = source_config(profile["credential_source"])
            if source["credentials_file"] and not Path(source["credentials_file"]).expanduser().is_absolute():
                problems.append(f"{name}: credential_source.credentials_file must be absolute; use the set command to resolve relative paths")
        except CredentialError:
            problems.append(f"{name}: invalid credential_source references")
    elif profile.get("secret_storage") == "external_secret_reference":
        problems.append(f"{name}: external_secret_reference requires credential_source")
    if profile.get("credential_login_mode", "browser_only") not in {"browser_only", "user_authorized_ephemeral"}:
        problems.append(f"{name}: unsupported credential_login_mode")
    if profile.get("browser", "chrome") not in {"chrome", "edge", "firefox", "safari"}:
        problems.append(f"{name}: unsupported browser")
    domains = profile.get("allowed_domains")
    if not isinstance(domains, list) or not domains:
        problems.append(f"{name}: allowed_domains must be a non-empty list")
    else:
        try:
            domains = [normalize_domain(value) for value in domains if isinstance(value, str)]
            if len(domains) != len(profile["allowed_domains"]):
                raise ProfileError("allowed_domains must contain strings")
            for field in ("library_url", "login_url", "session_probe_url"):
                if profile.get(field) and not domain_allowed(profile[field], domains):
                    problems.append(f"{name}: {field} host is outside allowed_domains")
        except ProfileError as exc:
            problems.append(f"{name}: {exc}")
    try:
        validate_url(profile.get("library_url"), "library_url", required=True)
        validate_url(profile.get("login_url"), "login_url")
        validate_url(profile.get("session_probe_url"), "session_probe_url")
    except ProfileError as exc:
        problems.append(f"{name}: {exc}")
    return problems


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=default_config_path())
    subparsers = parser.add_subparsers(dest="command", required=True)

    setter = subparsers.add_parser("set", help="Create or update a non-secret profile")
    setter.add_argument("--name", required=True)
    setter.add_argument("--institution")
    setter.add_argument("--library-url")
    setter.add_argument("--login-url")
    setter.add_argument("--session-probe-url")
    setter.add_argument("--allowed-domain", action="append", default=[])
    setter.add_argument("--browser-profile-label")
    setter.add_argument("--browser", choices=["chrome", "edge", "firefox", "safari"])
    setter.add_argument("--credential-login-mode", choices=["browser_only", "user_authorized_ephemeral"],
                        help="Ephemeral mode records authorization policy only, never credential values")
    setter.add_argument("--credentials-file", help="Private institution credential JSON reference; never its contents")
    setter.add_argument("--username-env", help="Environment variable name for the username")
    setter.add_argument("--password-env", help="Environment variable name for the password")
    setter.add_argument("--make-default", action="store_true")
    confirm_group = setter.add_mutually_exclusive_group()
    confirm_group.add_argument(
        "--auto-confirm-saved-login",
        dest="auto_confirm_saved_login",
        action="store_true",
        help="Allow one click only after the browser has already filled credentials",
    )
    confirm_group.add_argument(
        "--no-auto-confirm-saved-login",
        dest="auto_confirm_saved_login",
        action="store_false",
    )
    setter.set_defaults(auto_confirm_saved_login=None)

    show = subparsers.add_parser("show", help="Show non-secret profile metadata")
    show.add_argument("--name")

    select = subparsers.add_parser("select", help="Select the default profile")
    select.add_argument("--name", required=True)

    plan = subparsers.add_parser("plan", help="Inspect login references/presence; no browser login or secret output")
    plan.add_argument("--name")

    subparsers.add_parser("check", help="Validate all profiles without opening a browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        config = load_config(args.config)
        if args.command == "set":
            profile = set_profile(config, args)
            atomic_write(args.config, config)
            output = {
                "status": "saved",
                "profile": args.name,
                "default_profile": config["default_profile"],
                "config": str(args.config),
                "secret_fields_stored": False,
                "profile_data": profile,
            }
        elif args.command == "show":
            if args.name:
                if args.name not in config["profiles"]:
                    raise ProfileError(f"Unknown profile: {args.name}")
                output = {"name": args.name, "profile": config["profiles"][args.name]}
            else:
                output = config
        elif args.command == "select":
            if args.name not in config["profiles"]:
                raise ProfileError(f"Unknown profile: {args.name}")
            config["default_profile"] = args.name
            atomic_write(args.config, config)
            output = {"status": "selected", "default_profile": args.name}
        elif args.command == "plan":
            from institution_credentials import login_plan
            name = args.name or config.get("default_profile")
            if not name or name not in config["profiles"]:
                raise ProfileError("Select a valid institution profile first")
            output = login_plan(config["profiles"][name], name)
        else:
            problems = []
            for name, profile in config["profiles"].items():
                problems.extend(validate_profile(name, profile))
            output = {
                "status": "valid" if not problems else "invalid",
                "default_profile": config.get("default_profile"),
                "profile_count": len(config["profiles"]),
                "problems": problems,
                "browser_session_check_required": True,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0 if not problems else 2
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except ProfileError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
