#!/usr/bin/env python3
"""Build and verify a portable release offline, without user keys or accounts."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

import package_skill

PROJECT = package_skill.PROJECT


def require(condition, message):
    if not condition:
        raise ValueError(message)


def check_links(root):
    documents = [root] if root.is_file() else root.rglob("*.md")
    for doc in documents:
        for raw in re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", doc.read_text(encoding="utf-8")):
            if raw.startswith(("https:", "http:", "mailto:", "#")):
                continue
            target = raw.split("#", 1)[0].strip("<>")
            require((doc.parent / target).exists(), "Broken document link in " + doc.name + ": " + target)


def verify(output):
    check_links(PROJECT / "research-radar")
    for name in ("README.md", "README.zh-CN.md"):
        document = PROJECT / name
        require(document.is_file(), "Missing README: " + name)
        check_links(document)
    for folder in ("scripts", "references"):
        actual = {str(p.relative_to(package_skill.SOURCE)).replace(os.sep, "/")
                  for p in (package_skill.SOURCE / folder).iterdir() if p.is_file()}
        require(actual <= set(package_skill.FILES), "Unpackaged runtime resource in " + folder)
    manifest = package_skill.build(output)
    checks = []
    with tempfile.TemporaryDirectory(prefix="research-radar-release-") as temporary:
        work = Path(temporary)
        zip_path = output / "research-radar.zip"
        skill_path = output / "research-radar.skill"
        require(zip_path.read_bytes() == skill_path.read_bytes(), "ZIP and .skill archives differ")
        digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
        require(digest == manifest["archives"][zip_path.name], "Archive hash differs from manifest")
        with zipfile.ZipFile(zip_path) as bundle:
            require(set(bundle.namelist()) == {f["path"] for f in manifest["files"]}, "Archive member list differs")
            for entry in manifest["files"]:
                data = bundle.read(entry["path"])
                require(hashlib.sha256(data).hexdigest() == entry["sha256"], "Payload hash differs")
                require(not any(prefix in data for prefix in (b"/Users/", b"/var/folders/", b"/home/")),
                        "Developer machine path in " + entry["path"])
            bundle.extractall(work)
        root = work / "research-radar"
        check_links(root)
        second = package_skill.build(work / "second-build")
        require(second["archives"] == manifest["archives"], "Identical sources did not reproduce identical archives")
        require((root / "LICENSE").read_bytes() == (PROJECT / "LICENSE").read_bytes(), "MIT license missing from release")

        def run(name, args, expected=0):
            result = subprocess.run([sys.executable] + [str(v) for v in args], cwd=work,
                                    capture_output=True, text=True)
            require(result.returncode == expected, name + " failed: " + result.stderr[-1000:])
            checks.append({"name": name, "exit": result.returncode})
            return result

        radar = root / "radar.py"
        run("CLI help outside checkout", [radar, "--help"])
        run("unfilled intake fails before search", [radar, "validate", "--profile", root / "USER_CONFIG.template.md"], 2)
        profile = package_skill.read_profile_document(root / "USER_CONFIG.template.md")
        today = date.today()
        profile.update(topic="Synthetic release fixture", user_prompt="Check packaging with synthetic battery SOH metadata only.",
                       queries=["battery SOH"], date={"from": (today - timedelta(days=90)).isoformat(), "to": today.isoformat()},
                       sources=["crossref"])
        profile["easyscholar"]["enabled"] = False
        block = profile["fulltext_access"]["institution"]
        block["enabled"] = True
        block["routing"].update(institution="Example University", library_url="https://library.example.edu/resources",
                                login_url="https://sso.example.edu/login", allowed_domains=["library.example.edu", "sso.example.edu"])
        document = work / "user-data" / "config.md"
        document.parent.mkdir()
        document.write_text("# Synthetic fixture\n\n```json\n" + json.dumps(profile) + "\n```\n", encoding="utf-8")
        run("validate single Markdown document", [radar, "validate", "--profile", document])
        run("doctor with inline institution routing", [radar, "doctor", "--profile", document])
        run("preflight offers a choice before discovery", [radar, "preflight", "--profile", document], 3)
        before_search = work / "no-choice-no-search"
        run("run stops on gaps before requests", [radar, "run", "--profile", document, "--out", before_search], 3)
        require(not before_search.exists(), "Unaccepted configuration gaps created search evidence")
        json_profile = document.with_suffix(".json")
        json_profile.write_text(json.dumps(profile), encoding="utf-8")
        run("JSON profile remains supported", [radar, "validate", "--profile", json_profile])
        fixture = work / "fixture.jsonl"
        fixture.write_text(json.dumps({"id": "doi:10.1234/synthetic-release", "doi": "10.1234/synthetic-release",
            "title": "Synthetic battery SOH fixture", "abstract": "Synthetic metadata for offline verification only.",
            "url": "https://example.org/synthetic-release", "publication_type": "journal-article", "metrics": {},
            "published_online": today.isoformat(), "venue": {}}) + "\n", encoding="utf-8")
        driver_code = """import importlib.util,sys
from pathlib import Path
root,profile,out,fixture=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('release_driver',root/'radar.py')
d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
def discover(script,p,kinds,dest,cap):
 dest.mkdir(parents=True)
 (dest/'candidates.jsonl').write_text(fixture.read_text())
 return {'source':dest.name,'status':'complete','exit':0,'detail':'synthetic offline fixture','stderr':''}
d._run_discovery=discover
raise SystemExit(d.main(['run','--profile',str(profile),'--out',str(out),'--continue-with-gaps']))
"""
        run_dir = work / "run"
        run("driver with local discovery fixture", ["-c", driver_code, root, document, run_dir, fixture])
        require((run_dir / "search-plan.json").exists() and (run_dir / "search-ledger.template.json").exists(),
                "Deep-search resources missing from installed runtime")
        run("blank search ledger stays incomplete", [radar, "audit-search", "--run", run_dir,
            "--ledger", run_dir / "search-ledger.template.json", "--out", work / "search-audit.json"], 2)
        run("metadata access handoff without login", [radar, "access", "--run", run_dir, "--out", work / "access"])
        run("prepare version-bound review", [radar, "prepare-review", "--run", run_dir, "--out", work / "review"])
        run("unfilled review stays pending", [radar, "assess", "--run", run_dir,
            "--reviews", work / "review/reviews.template.jsonl", "--out", work / "assessed"])
        require(not json.loads((work / "assessed/assessment-summary.json").read_text())["selected_ids"],
                "Unfilled reviews produced recommendations")
        require((work / "assessed/selection-catalog.json").exists(), "No numbered download selection catalog")
        require(not list(work.rglob("*.pdf")), "Stage 1 unexpectedly saved PDFs")
        run("selected plan without downloads", [radar, "select", "--assessment", work / "assessed",
            "--numbers", "1", "--out", work / "chosen"])
        selected = json.loads((work / "chosen/download-plan.json").read_text())
        require(selected["selected_ids"] == ["doi:10.1234/synthetic-release"] and selected["status"] == "planned",
                "Plan broadened selection or claimed downloads")
        require(not (work / "chosen/pdfs").exists(), "Selection planned but unexpectedly downloaded files")
        run("unknown number rejected without output", [radar, "select", "--assessment", work / "assessed",
            "--numbers", "99", "--out", work / "unknown"], 2)
        require(not (work / "unknown").exists(), "Invalid selection created output")
        adapter_code = """import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'scripts'))
from config import load_profile
from institution_credentials import authenticate
p=load_profile(sys.argv[2])['fulltext_access']['institution']['routing']
class SyntheticAdapter:
 def prepare(self,profile):
  return {'state':'credentials_required','credential_url':profile['login_url']}
 def submit_credentials(self,pair,expected_origin):
  assert pair.username=='synthetic-user' and pair.password=='synthetic-password'
  return {'state':'mfa_required','context_ref':'browser:synthetic'}
result=authenticate(p,'my-school',SyntheticAdapter(),authorized=True,username='synthetic-user',password='synthetic-password')
assert result['status']=='mfa_required' and result['entitlement']=='unknown'
assert 'synthetic-password' not in json.dumps(result)
print(json.dumps(result))
"""
        run("local credential adapter returns human challenge", ["-c", adapter_code, root, document])
    report = {"status": "passed", "checked_at": datetime.now(timezone.utc).isoformat(),
              "files": manifest["file_count"], "archive_sha256": manifest["archives"]["research-radar.zip"],
              "hashes_match": True, "reproducible_archive": True, "documentation_links_resolve": True,
              "scope": "Offline archive and CLI checks; run unit suite separately. No real institution login, paid access or harness installation verified.",
              "checks": checks}
    (output / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=PROJECT / "dist")
    args = parser.parse_args()
    try:
        report = verify(args.output_dir.resolve())
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, "Release check failed: " + str(exc) + "\n")
    print(json.dumps({"status": report["status"], "files": report["files"], "checks": len(report["checks"]),
                      "output_dir": str(args.output_dir.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
