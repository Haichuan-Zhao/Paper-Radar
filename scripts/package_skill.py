#!/usr/bin/env python3
"""Build the maintained skill using a fixed allowlist; never package user data."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / "research-radar"
sys.path.insert(0, str(SOURCE / "scripts"))
from config import read_profile_document
from fulltext_access import settings as access_settings

FILES = (
    "SKILL.md", "USER_CONFIG.template.md", "radar.py", "agents/openai.yaml",
    "scripts/auth_profile.py", "scripts/config.py", "scripts/credentials.py",
    "scripts/assessment.py", "scripts/claim_audit.py", "scripts/calibrate_assessments.py", "scripts/discover_preprints.py",
    "scripts/fulltext_access.py", "scripts/selection.py", "scripts/preflight.py", "scripts/search_strategy.py",
    "scripts/institution_credentials.py",
    "scripts/discover_openalex.py", "scripts/discover_papers.py", "scripts/easyscholar.py",
    "scripts/filters.py", "scripts/identifiers.py", "scripts/metric_registry.py",
    "scripts/notify.py", "scripts/relevance.py", "scripts/resolve_journal.py",
    "scripts/venue_table.py", "scripts/zotero_import.py",
    "references/candidate-schema.md", "references/credentials.md",
    "references/deployment.md", "references/discovery-and-evidence.md",
    "references/download-and-zotero.md", "references/matching.md",
    "references/metric-freshness.md", "references/scoring.md", "references/venue-metrics-template.csv",
    "references/preprints.md", "references/quality-evaluation.md",
    "references/fulltext-access.md",
    "references/institution-login.md", "references/preflight.md",
)


def build(output: Path) -> dict:
    # Only the public sample is a profile; never resolve environment/file keys.
    sample = read_profile_document(SOURCE / "USER_CONFIG.template.md")
    if any(sample.get(key) for key in ("topic", "topic_en", "user_prompt", "queries", "synonyms", "venue_metrics_files")):
        raise ValueError("Distribution intake must remain blank; fill a separate user-owned document")
    for service, field in (("easyscholar", "secret_key"), ("openalex", "api_key")):
        if sample.get(service, {}).get(field) or sample.get(service, {}).get("credentials_file"):
            raise ValueError("Distribution sample must not contain credentials or private file paths")
    access = access_settings(sample.get("fulltext_access"))
    institution = access.get("institution") or {}
    routing = institution.get("routing") or {}
    if ((access.get("unpaywall") or {}).get("email") or institution.get("enabled") or institution.get("config_file")
            or any(routing.get(k) for k in ("institution", "library_url", "login_url", "session_probe_url"))
            or (routing.get("credential_source") or {}).get("credentials_file") != "private/institution-accounts.json"):
        raise ValueError("Distribution sample must not contain personal contact or institution configuration")
    payloads = [(name, (SOURCE / name).read_bytes()) for name in sorted(FILES)]
    payloads.append(("LICENSE", (PROJECT / "LICENSE").read_bytes()))
    payloads.sort()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / "research-radar.zip"
    temporary = output / "research-radar.zip.tmp"
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name, payload in payloads:
            info = zipfile.ZipInfo("research-radar/" + name, date_time=(2026, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, payload)
    temporary.replace(archive)
    skill = output / "research-radar.skill"
    shutil.copyfile(archive, skill)
    manifest = {
        "skill": "research-radar", "source": "research-radar/", "file_count": len(payloads),
        "built_at": datetime.now(timezone.utc).isoformat(), "python": "3.9+ standard library",
        "archives": {name: hashlib.sha256((output / name).read_bytes()).hexdigest()
                     for name in (archive.name, skill.name)},
        "files": [{"path": "research-radar/" + name, "sha256": hashlib.sha256(payload).hexdigest()}
                  for name, payload in payloads],
        "validation_scope": "Archive structure and fixed public file allowlist; no live credentials or harness installation test",
    }
    (output / "package-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "dist")
    args = parser.parse_args()
    try:
        result = build(args.output_dir)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Packaging failed: {exc}\n")
    print(json.dumps({"output_dir": str(args.output_dir.resolve()), "file_count": result["file_count"],
                      "archive_sha256": result["archives"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
