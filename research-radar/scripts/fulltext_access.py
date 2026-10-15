"""Resolve lawful full-text routes from metadata; never download or create access.

An OA index link is a lead, not proof that its target was read. Optional host
observations describe actual access, separately from the paper-quality rubric.
All network requests in this module go to fixed public metadata API endpoints.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import auth_profile
from discover_papers import doi as normalize_doi

VERSIONS = {"submittedVersion", "acceptedVersion", "publishedVersion", "unknown"}
METHODS = {"open_access", "institution", "publisher_api", "user_file"}
OUTCOMES = {"readable_full_text", "login_required", "subscription_required", "not_found", "blocked", "timeout"}


class AccessError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def settings(value=None):
    value = {} if value is None else value
    if not isinstance(value, dict) or set(value) - {"unpaywall", "europepmc", "institution", "max_lookups", "timeout", "pause"}:
        raise AccessError("fulltext_access accepts unpaywall/europepmc/institution/max_lookups/timeout/pause")
    result = {"max_lookups": value.get("max_lookups", 60), "timeout": value.get("timeout", 15), "pause": value.get("pause", 1)}
    if type(result["max_lookups"]) is not int or not 0 <= result["max_lookups"] <= 1000:
        raise AccessError("fulltext_access.max_lookups must be an integer in [0, 1000]")
    for field, low, high in (("timeout", 0.1, 120), ("pause", 0, 60)):
        v = result[field]
        if type(v) not in (int, float) or not math.isfinite(v) or not low <= v <= high:
            raise AccessError("Invalid fulltext_access." + field)
    for name, defaults in (
        ("unpaywall", {"enabled": False, "email_env": "UNPAYWALL_EMAIL", "email": None}),
        ("europepmc", {"enabled": False}),
        ("institution", {"enabled": False, "profile": None, "config_file": None, "routing": None}),
    ):
        block = value.get(name, {})
        if not isinstance(block, dict) or set(block) - set(defaults):
            raise AccessError("Unknown fulltext_access." + name + " fields")
        block = {**defaults, **block}
        if type(block["enabled"]) is not bool:
            raise AccessError("fulltext_access." + name + ".enabled must be boolean")
        result[name] = block
    env = result["unpaywall"]["email_env"]
    if not isinstance(env, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
        raise AccessError("unpaywall.email_env must name an environment variable")
    email = result["unpaywall"]["email"]
    if email is not None and (not isinstance(email, str) or not valid_email(email)):
        raise AccessError("unpaywall.email must be the user's contact email")
    for key in ("profile", "config_file"):
        if result["institution"][key] is not None and (not isinstance(result["institution"][key], str) or not result["institution"][key].strip()):
            raise AccessError("institution." + key + " must be a nonempty string or null")
    routing = result["institution"]["routing"]
    if routing is not None:
        if not isinstance(routing, dict):
            raise AccessError("institution.routing must be a non-secret institution profile")
        if result["institution"]["config_file"]:
            raise AccessError("Use institution.routing or config_file, not both")
        try:
            auth_profile.validate_no_secrets(routing)
            routing = dict(routing)
            if routing.get("credential_source") is not None:
                from institution_credentials import source_config
                routing["credential_source"] = source_config(routing["credential_source"])
        except ValueError:
            raise AccessError("institution.routing accepts public metadata and credential references only") from None
        result["institution"]["routing"] = routing
    return result


def valid_email(value):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value or ""))


def contact(config):
    block = config["unpaywall"]
    email = (os.environ.get(block["email_env"]) or block["email"] or "").strip()
    return email if valid_email(email) else None


def institution_route(config):
    block = config["institution"]
    if not block["enabled"]:
        return None
    try:
        if block.get("routing") is not None:
            name = block["profile"] or "user-institution"
            p = block["routing"]
            if auth_profile.validate_profile(name, p):
                raise AccessError("Invalid institution.routing; check stable entry URLs, allowed domains and credential references")
        else:
            path = Path(block["config_file"]).expanduser() if block["config_file"] else auth_profile.default_config_path()
            data = auth_profile.load_config(path)
            name = block["profile"] or data.get("default_profile")
            if not name or name not in data["profiles"]:
                raise AccessError("Configured institution profile is missing; set its stable library URL first")
            p = data["profiles"][name]
        # Only non-secret routing fields. A profile does not prove a live login
        # or a subscription to this particular article, journal, year or issue.
        return {"kind": "institution", "profile": name, "url": p["library_url"],
                "login_url": p.get("login_url"), "session_probe_url": p.get("session_probe_url"),
                "browser": p.get("browser"), "browser_profile_label": p.get("browser_profile_label"),
                "credential_login_mode": p.get("credential_login_mode", "browser_only"),
                "credential_source": p.get("credential_source"),
                "allowed_domains": p.get("allowed_domains", []), "status": "needs_session_check",
                "entitlement": "unknown", "version": "unknown", "retrieval_method": "institution"}
    except auth_profile.ProfileError as exc:
        raise AccessError(str(exc)) from None


def safe_url(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return auth_profile.validate_url(value, "full-text route", required=True)
    except (auth_profile.ProfileError, ValueError):
        return None


def preprint_url_matches(record, source):
    """Reject a known native URL pointing to another paper/version.

    Unknown repository/proxy/file paths need the host's actual document check.
    An unversioned URL is only a lead; it does not establish a pinned version.
    """
    native = record.get("preprint") or {}
    if not native or not isinstance(source, str):
        return True
    parsed = urllib.parse.urlparse(source)
    host = (parsed.hostname or "").lower()
    if native.get("server") == "arxiv" and host in {"arxiv.org", "www.arxiv.org", "export.arxiv.org"}:
        match = re.fullmatch(r"/(?:abs|pdf|html)/(.+?)(?:\.pdf)?/?", parsed.path)
        if match:
            target = match.group(1)
            parts = re.fullmatch(r"(.+?)v(\d+)", target)
            return (parts.group(1) == native.get("native_id") and int(parts.group(2)) == record.get("version")) if parts else target == native.get("native_id")
    if native.get("server") in {"biorxiv", "medrxiv"} and host in {native["server"] + ".org", "www." + native["server"] + ".org"}:
        match = re.match(r"/content/(10\.[^/]+/.+?)v(\d+)(?:\.full|/|$)", parsed.path)
        if match:
            return normalize_doi(match.group(1)) == normalize_doi(record.get("doi")) and int(match.group(2)) == record.get("version")
    return True


def fetch_json(url, timeout):
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "ResearchRadar/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise AccessError("metadata_response_too_large")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise AccessError("invalid_metadata_object")
        return data
    except urllib.error.HTTPError as exc:
        # API HTTP codes say nothing about the article subscription. Avoid
        # exception URLs/bodies, which can contain the user's contact email.
        raise AccessError("metadata_http_" + str(exc.code)) from None
    except (OSError, ValueError) as exc:
        if isinstance(exc, AccessError):
            raise
        raise AccessError("metadata_" + type(exc).__name__) from None


def route(url, source, version="unknown", license=None, format="landing", oa=False, **extra):
    url = safe_url(url)
    if not url:
        return None
    return {"kind": "open_copy" if oa else "publisher", "url": url, "source": source,
            "version": version if version in VERSIONS else "unknown", "license": license,
            "format": format, "reported_open_access": oa is True, "status": "link_unverified",
            "entitlement": "unknown", **extra}


def unpaywall_routes(data, doi):
    if normalize_doi(data.get("doi")) != doi:
        raise AccessError("unpaywall_doi_mismatch")
    found = []
    locations = data.get("oa_locations") or []
    if not isinstance(locations, list):
        raise AccessError("unpaywall_invalid_locations")
    # Embargoed future locations are deliberately excluded from usable routes.
    for loc in [data.get("best_oa_location")] + locations:
        if not isinstance(loc, dict):
            continue
        for field, fmt in (("url_for_pdf", "pdf"), ("url_for_landing_page", "landing"), ("url", "landing")):
            r = route(loc.get(field), "Unpaywall", loc.get("version"), loc.get("license"), fmt, True,
                      host_type=loc.get("host_type"), oa_date=loc.get("oa_date"))
            if r:
                found.append(r)
    return found


def europepmc_routes(data, doi):
    results = (data.get("resultList") or {}).get("result")
    if not isinstance(results, list):
        raise AccessError("europepmc_invalid_results")
    found, matched = [], False
    for item in results:
        if not isinstance(item, dict) or normalize_doi(item.get("doi")) != doi:
            continue
        matched = True
        for link in (item.get("fullTextUrlList") or {}).get("fullTextUrl", []):
            if not isinstance(link, dict):
                continue
            # Free-to-read is a route; it is not a redistribution licence.
            oa = link.get("availability") in {"Open access", "Free"}
            r = route(link.get("url"), "Europe PMC", license=item.get("license"),
                      format=str(link.get("documentStyle") or "landing").lower(), oa=oa,
                      availability=link.get("availability"), pmcid=item.get("pmcid"))
            if r:
                found.append(r)
        pmcid = item.get("pmcid")
        if isinstance(pmcid, str) and re.fullmatch(r"PMC\d+", pmcid) and item.get("isOpenAccess") == "Y":
            # OA-subset API XML, not a claim that every free PMC page permits
            # API/bulk retrieval. Body is fetched only by the host when reading.
            found.append(route("https://www.ebi.ac.uk/europepmc/webservices/rest/" + pmcid + "/fullTextXML",
                               "Europe PMC OA subset", license=item.get("license"), format="xml", oa=True, pmcid=pmcid))
    if results and not matched:
        raise AccessError("europepmc_doi_mismatch")
    return [r for r in found if r]


def local_routes(record):
    found = []
    native = record.get("preprint") or {}
    is_preprint = record.get("publication_type") == "preprint"
    for link in record.get("full_text_urls") or []:
        if not isinstance(link, dict):
            continue
        oa = link.get("reported_open_access") is True or bool(native)
        r = route(link.get("url"), link.get("source") or native.get("server") or "discovery metadata",
                  link.get("version") or ("submittedVersion" if is_preprint else "unknown"),
                  link.get("license"), link.get("format") or "landing", oa,
                  native_version=record.get("version") if is_preprint else None)
        if r:
            found.append(r)
    r = route(record.get("url") or ("https://doi.org/" + record["doi"] if record.get("doi") else None),
              "candidate landing page", "submittedVersion" if is_preprint else "unknown", oa=bool(native),
              native_version=record.get("version") if is_preprint else None)
    if r:
        found.append(r)
    return found


def deduplicate(routes):
    unique = {}
    for r in routes:
        key = (r["url"], r["version"], r.get("format"))
        if key not in unique:
            unique[key] = copy.deepcopy(r)
        elif r.get("reported_open_access"):
            unique[key]["reported_open_access"] = True
            unique[key]["kind"] = "open_copy"
    ranks = {"publishedVersion": 0, "acceptedVersion": 1, "submittedVersion": 2, "unknown": 3}
    return sorted(unique.values(), key=lambda r: (not r.get("reported_open_access"), ranks[r["version"]], r.get("format") != "pdf"))


def observation_template(record, fingerprint):
    return {"candidate_id": record["id"], "candidate_fingerprint": fingerprint,
            "outcome": None, "source": "", "checked_at": "", "retrieval_method": "",
            "material_version": "unknown", "native_version": record.get("version"),
            "identity_verified": False, "evidence": {"locator": "", "excerpt": ""}}


def validate_observation(obs, record, fingerprint):
    if obs.get("candidate_fingerprint") != fingerprint:
        raise AccessError("Stale access observation for " + record["id"])
    if obs.get("outcome") not in OUTCOMES or obs.get("retrieval_method") not in METHODS:
        raise AccessError("Invalid access outcome/method for " + record["id"])
    try:
        timestamp = datetime.fromisoformat(obs.get("checked_at", "").replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp > datetime.now(timezone.utc):
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise AccessError("Access observation needs an actual check time") from None
    evidence = obs.get("evidence")
    if not isinstance(evidence, dict) or any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in ("locator", "excerpt")):
        raise AccessError("Access observation needs observed page/file evidence")
    source = obs.get("source")
    if obs["retrieval_method"] == "user_file":
        if not isinstance(source, str) or not Path(source).is_absolute() or not Path(source).is_file():
            raise AccessError("User-file observation needs an existing absolute local file")
    elif not safe_url(source):
        raise AccessError("Access observation needs a stable, credential-free source URL")
    if obs.get("material_version") not in VERSIONS:
        raise AccessError("Unknown access material version")
    if obs["outcome"] == "readable_full_text":
        if obs.get("identity_verified") is not True or obs["material_version"] == "unknown":
            raise AccessError("Readable full text requires identity and version verification")
        if record.get("preprint") and (obs.get("native_version") != record.get("version") or obs["material_version"] != "submittedVersion"):
            raise AccessError("Preprint access observation belongs to a different version")
        if not preprint_url_matches(record, source):
            raise AccessError("Preprint source URL belongs to a different identity/version")
    return copy.deepcopy(obs)


def resolve(records, profile, fingerprint, observations=None):
    """Return a separate manifest. Never change candidates or content scores."""
    config = settings(profile.get("fulltext_access"))
    institutional = institution_route(config)
    indexed = {}
    ids = {r["id"] for r in records}
    for obs in observations or []:
        key = obs.get("candidate_id")
        if key not in ids or key in indexed:
            raise AccessError("Unknown or duplicate access observation candidate_id")
        indexed[key] = obs
    # Same finite topic-first queue as content review. Non-queue papers still
    # receive preserved links and a not-checked status, never a paywall label.
    eligible = sorted([r for r in records if (r.get("filter") or {}).get("decision") != "exclude"],
                      key=lambda r: (r.get("preliminary") or {}).get("relevance", 0), reverse=True)
    lookup_ids = {r["id"] for r in eligible[:min(config["max_lookups"], (profile.get("assessment") or {}).get("review_limit", 60))]}
    rows, calls = [], 0
    for record in records:
        routes, attempts = local_routes(record), []
        doi = normalize_doi(record.get("doi"))
        native_preprint = bool(record.get("preprint"))
        for provider in ("unpaywall", "europepmc"):
            if not config[provider]["enabled"]:
                continue
            if record["id"] not in lookup_ids or not doi or native_preprint:
                attempts.append({"source": provider, "status": "not_checked", "reason": "budget_or_no_article_doi"})
                continue
            email = contact(config) if provider == "unpaywall" else None
            if provider == "unpaywall" and not email:
                attempts.append({"source": provider, "status": "inconclusive", "reason": "user_contact_email_missing"})
                continue
            if calls:
                time.sleep(config["pause"])
            calls += 1
            endpoint = ("https://api.unpaywall.org/v2/" + urllib.parse.quote(doi, safe="") + "?" + urllib.parse.urlencode({"email": email})
                        if provider == "unpaywall" else "https://www.ebi.ac.uk/europepmc/webservices/rest/search?" +
                        urllib.parse.urlencode({"query": 'DOI:"' + doi + '"', "format": "json", "resultType": "core", "pageSize": 10}))
            try:
                data = fetch_json(endpoint, config["timeout"])
                additions = unpaywall_routes(data, doi) if provider == "unpaywall" else europepmc_routes(data, doi)
                routes.extend(additions)
                attempts.append({"source": provider, "status": "links_found" if any(r.get("reported_open_access") for r in additions) else "no_open_copy_found", "checked_at": now()})
            except AccessError as exc:
                attempts.append({"source": provider, "status": "inconclusive", "reason": str(exc), "checked_at": now()})
        if institutional:
            routes.append(copy.deepcopy(institutional))
        routes = deduplicate(routes)
        status = ("oa_link_found" if any(r.get("reported_open_access") for r in routes) else
                  "institution_route_available" if institutional else
                  "lookup_inconclusive" if any(a["status"] == "inconclusive" for a in attempts) else
                  "no_open_copy_found" if any(a["status"] == "no_open_copy_found" for a in attempts) else "not_checked")
        observation = None
        if record["id"] in indexed:
            observation = validate_observation(indexed[record["id"]], record, fingerprint(record))
            status = {"readable_full_text": "readable_copy_verified", "login_required": "login_required",
                      "subscription_required": "subscription_required", "not_found": "route_not_found",
                      "blocked": "access_blocked", "timeout": "lookup_inconclusive"}[observation["outcome"]]
            if observation["outcome"] == "readable_full_text" and observation["material_version"] == "submittedVersion" and record.get("publication_type") != "preprint":
                status = "alternative_version_available"
            elif observation["outcome"] != "readable_full_text" and any(r.get("reported_open_access") and r["url"] != observation["source"] for r in routes):
                # A denial concerns that route, not every available copy.
                status = "oa_link_found"
        rows.append({"schema_version": 1, "candidate_id": record["id"], "candidate_fingerprint": fingerprint(record),
                     "status": status, "routes": routes, "metadata_attempts": attempts, "observation": observation,
                     "assessed_content": False, "generated_at": now(),
                     "next_action": "inspect_full_text_and_figures" if status in {"oa_link_found", "readable_copy_verified"} else
                                    "verify_alternative_as_separate_version" if status == "alternative_version_available" else
                                    "reuse_institution_browser_session" if status in {"institution_route_available", "login_required"} else
                                    "user_pdf_or_library_document_delivery",
                     "manual_options": ["user_provided_file", "library_document_delivery", "author_repository_or_author_request", "user_decides_purchase"]})
    return rows, {"schema_version": 1, "candidates": len(rows), "metadata_requests": calls,
                  "statuses": dict(Counter(r["status"] for r in rows)), "user_contact_configured": bool(contact(config)),
                  "institution_configured": institutional is not None,
                  "scope": "Metadata routes and host access observations; no full-text downloads, subscriptions, quality scores or automated purchases"}


def write(output, rows, summary, records, fingerprint):
    output = Path(output)
    names = ("access-manifest.jsonl", "access-summary.json", "access-observations.template.jsonl", "access-plan.md")
    if any((output / name).exists() for name in names):
        raise AccessError("Access output already exists; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    for name, values in ((names[0], rows), (names[2], [observation_template(r, fingerprint(r)) for r in records])):
        (output / name).write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in values), encoding="utf-8")
    (output / names[1]).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    titles = {r["id"]: r.get("title") or r["id"] for r in records}
    lines = ["# 全文获取计划", "", "链接与订阅权限需实际确认。未找到开放副本不等于必须购买；可读性不计入 Q/M/S。", ""]
    for row in rows:
        lines.extend(["## " + titles[row["candidate_id"]], "", "状态：" + row["status"] + "；下一步：" + row["next_action"], ""])
        for r in row["routes"]:
            lines.append("- [" + str(r.get("source") or r.get("profile") or r["kind"]) + "](" + r["url"] + ") — " + r["version"] + "；" + r["status"] + "；license=" + str(r.get("license") or "unknown"))
        if row["observation"]:
            o = row["observation"]
            lines.append("- 实际检查：" + o["material_version"] + " / " + o["retrieval_method"] + " / " + o["checked_at"])
        lines.append("")
    (output / names[3]).write_text("\n".join(lines), encoding="utf-8")
    return summary
