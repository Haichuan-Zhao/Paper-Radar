#!/usr/bin/env python3
"""Check the repository without reading personal configuration or using the network."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = Path(".agents/skills/paper-radar")
BUNDLE_FILES = {"SKILL.md", "agents/openai.yaml", "LICENSE"}
DOCUMENTS = ["README.md", str(SKILL_DIR / "SKILL.md"), "tests/acceptance.md", "tests/fixtures/behavior.md"]
IGNORED_EXAMPLES = [
    "USER_CONFIG.md", "USER_CONFIG.md.bak", "USER_CONFIG.backup.md", "USER_CONFIG.local.md",
    "USER_CONFIG.md~", ".USER_CONFIG.md.swp", ".USER_CONFIG.md.swo", ".USER_CONFIG.md.swn",
    ".USER_CONFIG.md.un~", ".~lock.USER_CONFIG.md#", "nested/USER_CONFIG.md",
    "nested/USER_CONFIG.backup.md", "paper-radar-results/run-a/selection-catalog.json",
    "paper-radar-results/run-b/downloads/manifest.md", "downloads/example.pdf",
]


class UniqueSafeLoader(yaml.SafeLoader):
    pass


def _unique_mapping(loader, node, deep=False):
    mapping = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError("Duplicate YAML key.")
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueSafeLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _unique_mapping)


def parse_yaml(text):
    return yaml.load(text, Loader=UniqueSafeLoader)


def prose_only(text):
    prose, marker = [], None
    for line in text.splitlines():
        match = re.match(r"^\s*(`{3,}|~{3,})(.*)$", line)
        if match:
            fence = match.group(1)
            if marker is None:
                marker = (fence[0], len(fence))
            elif fence[0] == marker[0] and len(fence) >= marker[1] and not match.group(2).strip():
                marker = None
        elif marker is None:
            prose.append(line)
    if marker is not None:
        raise ValueError("Unclosed Markdown fence.")
    return "\n".join(prose)


def headings(text):
    result, counts = set(), {}
    for title in re.findall(r"^#{1,6}\s+(.+?)\s*#*\s*$", prose_only(text), flags=re.M):
        slug = re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug if count == 0 else "%s-%d" % (slug, count))
    return result


def check_project(root=ROOT):
    root = Path(root).resolve()
    bundle = root / SKILL_DIR
    for relative in [".agents", ".agents/skills", str(SKILL_DIR)]:
        if (root / relative).is_symlink():
            raise ValueError("Skill directory ancestors must not be symbolic links.")
    actual = set()
    for path in bundle.rglob("*"):
        if path.is_symlink():
            raise ValueError("The skill bundle must not contain symbolic links.")
        if path.is_file() and path.name != ".DS_Store":
            actual.add(path.relative_to(bundle).as_posix())
    if actual != BUNDLE_FILES:
        raise ValueError("Skill bundle differs from the three-file public allowlist.")
    skill = (bundle / "SKILL.md").read_text(encoding="utf-8")
    front = re.match(r"\A---\n(.*?)\n---(?:\n|$)", skill, flags=re.S)
    if front is None:
        raise ValueError("Missing skill YAML frontmatter.")
    metadata = parse_yaml(front.group(1))
    if (not isinstance(metadata, dict) or metadata.get("name") != "paper-radar"
            or metadata.get("license") != "MIT" or metadata.get("metadata", {}).get("language") != "zh-CN"):
        raise ValueError("Invalid skill identity, license or language.")
    description = metadata.get("description")
    if not isinstance(description, str) or not 1 <= len(description) <= 1024 or re.search(r"[<>]", description):
        raise ValueError("Invalid skill discovery description.")
    ui = parse_yaml((bundle / "agents/openai.yaml").read_text(encoding="utf-8"))
    interface = ui.get("interface", {}) if isinstance(ui, dict) else {}
    if (not isinstance(interface.get("display_name"), str) or not interface["display_name"].strip()
            or not isinstance(interface.get("short_description"), str)
            or not 25 <= len(interface["short_description"]) <= 64
            or "$paper-radar" not in interface.get("default_prompt", "")):
        raise ValueError("Invalid skill interface metadata.")
    license_bytes = (bundle / "LICENSE").read_bytes()
    if not license_bytes.startswith(b"MIT License") or license_bytes != (root / "LICENSE").read_bytes():
        raise ValueError("The two MIT licenses must match.")

    for name in DOCUMENTS:
        path = root / name
        text = path.read_text(encoding="utf-8")
        boundary = bundle.resolve() if path.is_relative_to(bundle) else root
        for target in re.findall(r"\]\(([^)]+)\)", prose_only(text)):
            url = urlsplit(target.strip().strip("<>"))
            if url.scheme or url.netloc:
                continue
            resolved = (path.parent / unquote(url.path)).resolve() if url.path else path.resolve()
            if not resolved.is_relative_to(boundary) or not resolved.is_file():
                raise ValueError("Local Markdown link is missing or leaves its distribution boundary.")
            if url.fragment and resolved.suffix == ".md":
                if unquote(url.fragment) not in headings(resolved.read_text(encoding="utf-8")):
                    raise ValueError("Local Markdown heading target does not exist.")
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"], cwd=root,
        input="\n".join(IGNORED_EXAMPLES) + "\n", capture_output=True, text=True, check=False,
    )
    if result.returncode not in (0, 1) or set(result.stdout.splitlines()) != set(IGNORED_EXAMPLES):
        raise ValueError("Personal configuration or task-output ignore coverage is incomplete.")
    return {"skill_files": len(actual), "documents": len(DOCUMENTS),
            "skill_sha256": hashlib.sha256((bundle / "SKILL.md").read_bytes()).hexdigest()}


def main():
    try:
        result = check_project()
    except (OSError, ValueError, yaml.YAMLError, TypeError, AttributeError):
        # Keep parse errors and file contents out of logs, including unexpected private files.
        print("Project check failed; inspect structure, metadata, links and ignore rules.", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
