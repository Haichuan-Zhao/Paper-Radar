#!/usr/bin/env python3
"""Send a Research Radar run summary through configurable notification channels.

Reads a run summary (JSON) and a profile's ``automation.notify`` block, decides
whether to notify based on ``notify.on``, then delivers through any enabled
webhook/email/desktop channel and appends a safe log line. SMTP credentials are
read only from the environment (``RR_SMTP_PASSWORD`` and optional
``RR_SMTP_USER``) and never appear in stdout, the summary, or the log.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import smtplib
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

#: Notification policies accepted by ``automation.notify.on``.
POLICIES = ("never", "always", "new_shortlist", "errors")

#: Statuses (lowercased) that imply errors for the ``errors`` policy.
ERROR_STATUSES = {"error", "failed", "failure", "partial", "partial_with_errors", "partial-with-errors"}

#: How many top shortlist titles to include in the notification body.
TOP_TITLES = 5


class ConfigError(ValueError):
    """Raised when ``--config`` cannot be read as a JSON object."""


def now_iso() -> str:
    """Current UTC timestamp in ISO-8601 form (used for the log line)."""
    return datetime.now(timezone.utc).isoformat()


def _dict(value: Any) -> dict[str, Any]:
    """Coerce a possibly-missing mapping to a plain dict."""
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    """Coerce a possibly-missing sequence to a list."""
    return value if isinstance(value, list) else []


def _count(value: Any, default: int = 0) -> int:
    """Parse a possibly-string/float count, falling back to ``default``."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    """Coerce a value to stripped text."""
    return str(value or "").strip()


def _topic(summary: dict[str, Any]) -> str:
    return _text(summary.get("topic")) or "research-radar"


def _shortlist(summary: dict[str, Any]) -> list[Any]:
    return _list(summary.get("shortlist"))


def _status_is_error(status: Any) -> bool:
    """True when a run status implies errors (``error``, ``partial-with-errors``, etc.)."""
    value = _text(status).lower().replace(" ", "_")
    if not value:
        return False
    return value in ERROR_STATUSES or "error" in value


def _fmt_score(value: Any) -> str:
    """Format a numeric score compactly; empty string when absent."""
    if value is None:
        return ""
    try:
        number = float(value)
        if number == int(number):
            return str(int(number))
        return f"{number:.1f}"
    except (TypeError, ValueError):
        return _text(value)


def _doi_link(item: Any) -> str:
    """Return a link for a shortlist item: its ``url`` or a DOI resolution URL."""
    if not isinstance(item, dict):
        return ""
    url = _text(item.get("url"))
    if url:
        return url
    doi = _text(item.get("doi"))
    if doi:
        return f"https://doi.org/{doi}"
    return ""


def _safe_error(exc: BaseException) -> str:
    """Stringify an exception while redacting the SMTP password if present."""
    message = str(exc) or exc.__class__.__name__
    password = os.environ.get("RR_SMTP_PASSWORD")
    if password:
        message = message.replace(password, "***")
    return message[:500]


def _read_json(path: Path) -> Any:
    """Read and parse a JSON file, raising ConfigError on failure."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"Cannot read file {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid JSON in file {path}: {exc}") from exc


def load_config(path: Path) -> dict[str, Any]:
    """Read the same Markdown/JSON user document as the driver."""
    from config import read_profile_document, ProfileError
    try:
        return read_profile_document(path)
    except ProfileError:
        raise ConfigError("Cannot read notification configuration document") from None


def load_summary(path: Path) -> dict[str, Any]:
    """Load the run summary defensively; any failure yields an empty object."""
    try:
        data = _read_json(path)
    except ConfigError:
        return {}
    return data if isinstance(data, dict) else {}


def _notify_block(config: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``automation.notify`` block, tolerating absent sections."""
    return _dict(_dict(config.get("automation")).get("notify"))


def _policy(notify: dict[str, Any]) -> str:
    """Resolve the send policy, defaulting unknown/absent values to new_shortlist."""
    value = _text(notify.get("on")).lower()
    return value if value in POLICIES else "new_shortlist"


def should_send(policy: str, summary: dict[str, Any]) -> bool:
    """Decide whether to notify based on ``notify.on`` and the summary."""
    policy = _text(policy).lower() or "new_shortlist"
    if policy == "never":
        return False
    if policy == "always":
        return True
    if policy == "errors":
        return _count(summary.get("error_count")) > 0 or _status_is_error(summary.get("status"))
    # new_shortlist (and any unknown policy): only when there is a shortlist.
    return bool(_shortlist(summary))


def build_subject(summary: dict[str, Any]) -> str:
    """Build a concise subject line that always mentions the topic."""
    topic = _topic(summary)
    shortlisted = len(_shortlist(summary))
    watched = _count(summary.get("watchlist_count"))
    return f"Research Radar run for {topic}: {shortlisted} shortlisted, {watched} watchlisted"


def build_body(summary: dict[str, Any]) -> str:
    """Build a plain-text, Markdown-ish notification body."""
    shortlist = _shortlist(summary)
    lines: list[str] = []
    lines.append(f"Topic: {_topic(summary)}")

    started = _text(summary.get("started_at"))
    finished = _text(summary.get("finished_at"))
    if started and finished:
        lines.append(f"Run window: {started} -> {finished}")
    elif started or finished:
        lines.append(f"Run window: {started or finished}")

    lines.append(f"Status: {_text(summary.get('status')) or 'unknown'}")
    lines.append(f"Shortlist: {len(shortlist)} paper(s)")
    lines.append(f"Watchlist: {_count(summary.get('watchlist_count'))} paper(s)")

    if shortlist:
        lines.append("")
        lines.append("Top shortlisted papers:")
        for index, item in enumerate(shortlist[:TOP_TITLES], start=1):
            entry = f"{index}. {_text(item.get('title')) or '(untitled)'}"
            score = _fmt_score(item.get("total"))
            if score:
                entry += f" — score {score}"
            link = _doi_link(item)
            if link:
                entry += f" ({link})"
            lines.append(entry)

    errors = _list(summary.get("errors"))
    error_count = _count(summary.get("error_count"))
    if errors:
        lines.append("")
        lines.append(f"Errors ({len(errors)}):")
        for error in errors:
            lines.append(f"- {_safe_error_str(error)}")
    elif error_count > 0:
        lines.append("")
        lines.append(f"Errors: {error_count}")
    return "\n".join(lines)


def _safe_error_str(value: Any) -> str:
    """Stringify an error entry without ever exposing the SMTP password."""
    text = _text(value) if not isinstance(value, (dict, list)) else json.dumps(value, ensure_ascii=False)
    password = os.environ.get("RR_SMTP_PASSWORD")
    if password:
        text = text.replace(password, "***")
    return text


def _channel(name: str, status: str, detail: str) -> dict[str, str]:
    return {"channel": name, "status": status, "detail": detail}


def _webhook_parts(cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Validate webhook config; returns (parts, error)."""
    url = _text(cfg.get("url"))
    if not url:
        return None, "webhook url is empty"
    method = _text(cfg.get("method")).upper() or "POST"
    headers = {_text(key): _text(value) for key, value in _dict(cfg.get("headers")).items()}
    headers.setdefault("Content-Type", "application/json")
    return {"url": url, "method": method, "headers": headers}, None


def _status_code(response: Any) -> int:
    """Best-effort HTTP status extraction from a urllib response (or mock)."""
    getcode = getattr(response, "getcode", None)
    if callable(getcode):
        try:
            return int(getcode())
        except (TypeError, ValueError):
            pass
    try:
        return int(getattr(response, "status", 200))
    except (TypeError, ValueError):
        return 200


def send_webhook(cfg: dict[str, Any], summary: dict[str, Any]) -> tuple[str, str]:
    """POST the summary to a webhook; returns (status, detail)."""
    parts, error = _webhook_parts(cfg)
    if error:
        return "failed", error
    payload = {"event": "research-radar-run", "topic": summary.get("topic"), "summary": summary}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(parts["url"], data=data, method=parts["method"], headers=parts["headers"])
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            code = _status_code(response)
            if 200 <= code < 300:
                return "sent", f"{parts['method']} {parts['url']} -> {code}"
            return "failed", f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        return "failed", f"HTTP {exc.code}"
    except Exception as exc:  # noqa: BLE001 - never let one channel fail the run
        return "failed", _safe_error(exc)


def _plan_webhook(cfg: dict[str, Any]) -> tuple[str, str]:
    """Preview what a webhook send would do without any network call."""
    parts, error = _webhook_parts(cfg)
    if error:
        return "failed", error
    return "sent", f"would {parts['method']} {parts['url']}"


def _email_parts(cfg: dict[str, Any]) -> tuple[str, str | dict[str, Any]]:
    """Validate email config and resolve credentials from the environment."""
    password = os.environ.get("RR_SMTP_PASSWORD")
    if not password:
        return "skipped", "missing RR_SMTP_PASSWORD"
    host = _text(cfg.get("smtp_host"))
    if not host:
        return "failed", "email smtp_host is empty"
    sender = _text(cfg.get("from"))
    to_raw = cfg.get("to") or []
    if isinstance(to_raw, str):
        recipients = [part.strip() for part in to_raw.split(",") if part.strip()]
    else:
        recipients = [_text(item) for item in to_raw if _text(item)]
    if not sender or not recipients:
        return "failed", "email from/to is missing"
    try:
        port = int(cfg.get("smtp_port", 587) or 587)
    except (TypeError, ValueError):
        port = 587
    return "ok", {
        "password": password,
        "user": os.environ.get("RR_SMTP_USER"),
        "host": host,
        "port": port,
        "sender": sender,
        "recipients": recipients,
        "starttls": bool(cfg.get("starttls")),
    }


def send_email(cfg: dict[str, Any], subject: str, body: str) -> tuple[str, str]:
    """Send the summary via SMTP; credentials come only from the environment."""
    status, detail = _email_parts(cfg)
    if status != "ok":
        return status, detail
    parts = detail  # type: dict[str, Any]
    try:
        message = MIMEText(body, "plain", "utf-8")
        message["Subject"] = subject
        message["From"] = parts["sender"]
        message["To"] = ", ".join(parts["recipients"])
        with smtplib.SMTP(parts["host"], parts["port"], timeout=15) as smtp:
            if parts["starttls"]:
                smtp.starttls()
            if parts["user"]:
                smtp.login(parts["user"], parts["password"])
            smtp.sendmail(parts["sender"], parts["recipients"], message.as_string())
        return "sent", f"email to {len(parts['recipients'])} recipient(s) via {parts['host']}:{parts['port']}"
    except Exception as exc:  # noqa: BLE001 - never let one channel fail the run
        return "failed", _safe_error(exc)


def _plan_email(cfg: dict[str, Any]) -> tuple[str, str]:
    """Preview what an email send would do without contacting an SMTP server."""
    status, detail = _email_parts(cfg)
    if status != "ok":
        return status, detail
    parts = detail  # type: dict[str, Any]
    return "sent", f"would email {len(parts['recipients'])} recipient(s)"


def _desktop_message(subject: str, body: str) -> str:
    """Pick a short message for the desktop notification."""
    first_line = (body or subject or "").splitlines()[0] if body else subject
    return (first_line or subject or "Research Radar run complete").strip()


def send_desktop(subject: str, body: str) -> tuple[str, str]:
    """Show a macOS notification; other platforms are recorded as unsupported."""
    if sys.platform != "darwin":
        return "skipped", "unsupported_platform"
    message = _desktop_message(subject, body)
    script = f'display notification {shlex.quote(message)} with title {shlex.quote(subject)}'
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
    except Exception as exc:  # noqa: BLE001 - never let one channel fail the run
        return "failed", _safe_error(exc)
    if getattr(result, "returncode", 1) == 0:
        return "sent", "desktop notification shown"
    return "failed", f"osascript exited {getattr(result, 'returncode', 1)}"


def _plan_desktop(subject: str, body: str) -> tuple[str, str]:
    """Preview what a desktop notification would do without invoking osascript."""
    if sys.platform != "darwin":
        return "skipped", "unsupported_platform"
    return "sent", "would show desktop notification"


def append_log(log_file: str, run_dir: str, topic: Any, subject: str, sent_to: list[str]) -> bool:
    """Append one JSON log line; always best-effort and never fails the run."""
    path = Path(log_file)
    if not path.is_absolute():
        path = Path(run_dir) / path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {"at": now_iso(), "topic": topic, "subject": subject, "sent_to": sent_to},
            ensure_ascii=False,
        )
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        return False
    return True


def build_channels(
    notify: dict[str, Any],
    summary: dict[str, Any],
    subject: str,
    body: str,
    run_dir: str,
    dry_run: bool,
) -> list[dict[str, str]]:
    """Decide and (unless dry-run) perform each channel, then append the log."""
    channels: list[dict[str, str]] = []
    webhook = _dict(notify.get("webhook"))
    email = _dict(notify.get("email"))
    desktop = bool(notify.get("desktop"))

    if webhook.get("enabled"):
        status, detail = _plan_webhook(webhook) if dry_run else send_webhook(webhook, summary)
        channels.append(_channel("webhook", status, detail))
    else:
        channels.append(_channel("webhook", "disabled", "webhook.enabled is false"))

    if email.get("enabled"):
        status, detail = _plan_email(email) if dry_run else send_email(email, subject, body)
        channels.append(_channel("email", status, detail))
    else:
        channels.append(_channel("email", "disabled", "email.enabled is false"))

    if desktop:
        status, detail = _plan_desktop(subject, body) if dry_run else send_desktop(subject, body)
        channels.append(_channel("desktop", status, detail))
    else:
        channels.append(_channel("desktop", "disabled", "desktop is false"))

    if not dry_run:
        log_file = notify.get("log_file")
        if log_file:
            sent_to = [channel["channel"] for channel in channels if channel["status"] == "sent"]
            append_log(_text(log_file), run_dir, summary.get("topic"), subject, sent_to)
    return channels


def build_result(
    subject: str,
    body: str,
    channels: list[dict[str, str]],
    policy: str,
    dry_run: bool,
) -> dict[str, Any]:
    """Assemble the JSON result object printed on success."""
    result: dict[str, Any] = {
        "dry_run": dry_run,
        "on": policy,
        "sent": any(channel["status"] == "sent" for channel in channels),
        "channels": channels,
        "subject": subject,
    }
    if dry_run:
        result["body"] = body
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", required=True, type=Path, help="Run summary JSON file")
    parser.add_argument("--config", required=True, type=Path, help="User Markdown document or JSON profile")
    parser.add_argument("--run-dir", required=True, type=Path, help="Run directory for relative log paths")
    parser.add_argument("--dry-run", action="store_true", help="Preview without any side effects")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2

    summary = load_summary(args.summary)
    notify = _notify_block(config)
    policy = _policy(notify)
    dry_run = bool(args.dry_run)
    subject = build_subject(summary)
    body = build_body(summary)

    channels: list[dict[str, str]] = []
    if should_send(policy, summary):
        channels = build_channels(notify, summary, subject, body, str(args.run_dir), dry_run)

    result = build_result(subject, body, channels, policy, dry_run)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
