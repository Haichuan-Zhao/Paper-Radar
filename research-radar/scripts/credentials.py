"""Portable user-owned API credentials; never put resolved keys in profiles."""
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
from typing import Any


class CredentialError(ValueError):
    pass


DEFAULT_ENVS = {"easyscholar": "EASYSCHOLAR_SECRET_KEY", "openalex": "OPENALEX_API_KEY"}
SECRET_FIELDS = {"secret_key", "secretkey", "api_key", "apikey", "password", "token",
                 "authorization", "cookie", "client_secret"}


def save_key(path, service, value):
    """Atomically save a user-owned key without returning it or losing other keys."""
    if service not in DEFAULT_ENVS or not isinstance(value, str) or not value.strip():
        raise CredentialError("Choose a supported service and a nonempty key")
    path = Path(path).expanduser().absolute()
    temporary = None
    try:
        if path.is_symlink():
            raise CredentialError("Private credential destination must not be a symlink")
        data = {}
        if path.exists():
            if not stat.S_ISREG(path.stat().st_mode):
                raise CredentialError("Private credentials must be a regular file")
            data = json.loads(path.read_text(encoding="utf-8"))
            if (not isinstance(data, dict) or set(data) - set(DEFAULT_ENVS)
                    or any(not isinstance(entry, dict) for entry in data.values())):
                raise CredentialError("Configure needs a JSON object keyed by service name")
        field = "secret_key" if service == "easyscholar" else "api_key"
        data[service] = {field: value.strip()}
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
    except (OSError, ValueError):
        raise CredentialError("Cannot save private API keys; check the destination and JSON format") from None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def resolve_key(config: dict[str, Any], service: str) -> str | None:
    """Environment > private JSON file > explicitly supplied inline key.

    JSON: {"easyscholar": {"secret_key": "..."}, "openalex": {"api_key": "..."}}.
    A file may also be a single-service object with secret_key/api_key.
    """
    env_field = "secret_key_env" if service == "easyscholar" else "api_key_env"
    value = os.environ.get(str(config.get(env_field) or DEFAULT_ENVS[service]), "").strip()
    if value:
        return value
    path = config.get("credentials_file")
    if path:
        try:
            payload = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise CredentialError("Cannot read credentials JSON; check the file and JSON syntax") from None
        if not isinstance(payload, dict):
            raise CredentialError("Credentials JSON must be an object")
        entry = payload.get(service, payload)
        if not isinstance(entry, dict):
            raise CredentialError("Credential service entry must be an object")
        field = "secret_key" if service == "easyscholar" else "api_key"
        value = entry.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise CredentialError("Credential value must be a non-empty string")
        if value:
            return value.strip()
    field = "secret_key" if service == "easyscholar" else "api_key"
    value = config.get(field)
    if value is not None and not isinstance(value, str):
        raise CredentialError("Credential value must be a string")
    return value.strip() if value and value.strip() else None


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    """Redact inline credentials recursively, including URL query parameters."""
    if isinstance(value, dict):
        return {k: "[REDACTED]" if str(k).casefold().replace("-", "_") in SECRET_FIELDS and v
                else redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"(?i)([?&](?:secretKey|secret_key|api_key|token)=)[^&#\s]+", r"\1[REDACTED]", value)
    return value


class PrivateArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        self.exit(2, "Invalid credential arguments; use configure --service NAME --out PRIVATE_FILE\n")


def main(argv=None):
    parser = PrivateArgumentParser(description="Configure your own API key using hidden local terminal input")
    sub = parser.add_subparsers(dest="command", required=True)
    configure = sub.add_parser("configure", help="Save an EasyScholar or OpenAlex key privately")
    configure.add_argument("--service", choices=sorted(DEFAULT_ENVS), required=True)
    configure.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    if not sys.stdin.isatty():
        print("Use an interactive local terminal or the host's secret input; no keys via arguments or stdin pipes", file=sys.stderr)
        return 2
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            value = getpass.getpass(args.service + " key (hidden): ")
        save_key(args.out, args.service, value)
        print(json.dumps({"status": "saved", "service": args.service, "credential_values_returned": False}))
        return 0
    except (OSError, CredentialError, getpass.GetPassWarning):
        print("Cannot save private API key; check the destination and configuration", file=sys.stderr)
        return 2
    except (EOFError, KeyboardInterrupt):
        print("Credential entry cancelled", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
