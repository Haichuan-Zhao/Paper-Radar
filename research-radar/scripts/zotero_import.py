#!/usr/bin/env python3
"""Plan or import explicitly selected Research Radar records into Zotero 10+."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, unquote
from urllib.request import Request, HTTPRedirectHandler, ProxyHandler, build_opener


BASE_URL = "http://localhost:23119/api"
USER_PREFIX = "/users/0"
APP_NAME = "Research Radar"
USER_AGENT = "ResearchRadarZoteroImporter/1.0"


class ImportErrorBase(RuntimeError):
    """Base class for importer errors."""


class ZoteroNotRunning(ImportErrorBase):
    pass


class AuthorizationDenied(ImportErrorBase):
    pass


class ZoteroProtocolError(ImportErrorBase):
    pass


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def local_api_url(path_or_url: str) -> str:
    url = urljoin(BASE_URL + "/", path_or_url) if path_or_url.startswith(("http://", "https://")) else BASE_URL + path_or_url
    parsed, base = urlparse(url), urlparse(BASE_URL)
    if (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
        raise ZoteroProtocolError("Refusing to send Zotero data outside the configured local server")
    if parsed.username or parsed.password or not parsed.path.startswith("/api/") or parsed.fragment:
        raise ZoteroProtocolError("Invalid local Zotero API URL")
    return url


@dataclass
class Response:
    status: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


def request(
    method: str,
    path_or_url: str,
    *,
    body: bytes | BinaryIO | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120.0,
) -> Response:
    url = local_api_url(path_or_url)
    merged_headers = {
        "User-Agent": USER_AGENT,
        "Zotero-API-Version": "3",
        "Zotero-Allowed-Request": "1",
    }
    if headers:
        merged_headers.update(headers)
    req = Request(url, data=body, headers=merged_headers, method=method)
    try:
        # Never forward local keys/files through environment proxies or redirects.
        with build_opener(ProxyHandler({}), NoRedirects()).open(req, timeout=timeout) as response:
            return Response(
                status=response.status,
                headers={key.lower(): value for key, value in response.headers.items()},
                body=response.read(),
            )
    except HTTPError as exc:
        return Response(
            status=exc.code,
            headers={key.lower(): value for key, value in exc.headers.items()},
            body=exc.read(),
        )
    except (URLError, TimeoutError, ConnectionError) as exc:
        raise ZoteroNotRunning(
            "Cannot reach Zotero local API. Open Zotero and enable local API access in Settings -> Advanced."
        ) from exc


def json_body(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.strip()


def file_hash(path: Path, algorithm: str = "md5") -> str:
    digest = hashlib.new(algorithm)  # MD5 is required by the Zotero upload protocol.
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_title(value: Any) -> str:
    text = re.sub(r"[^\w\s]", " ", str(value or "").casefold())
    return " ".join(text.split())


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ImportErrorBase(f"Cannot read {path}: {exc}") from exc
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ImportErrorBase(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
        if not isinstance(record, dict):
            raise ImportErrorBase(f"Record at {path}:{line_number} is not an object")
        records.append(record)
    return records


def record_aliases(record: dict[str, Any]) -> set[str]:
    aliases = {str(record.get("id") or "").strip()}
    doi = normalize_doi(record.get("doi"))
    if doi:
        aliases.update({doi, f"doi:{doi}", f"https://doi.org/{doi}"})
    return {alias.casefold() for alias in aliases if alias}


def select_records(records: list[dict[str, Any]], raw_ids: str) -> list[dict[str, Any]]:
    requested = [value.strip() for value in raw_ids.split(",") if value.strip()]
    if not requested:
        raise ImportErrorBase("--ids must contain one or more explicit paper IDs or DOIs")
    selected: list[dict[str, Any]] = []
    missing: list[str] = []
    seen: set[str] = set()
    for requested_id in requested:
        key = requested_id.casefold()
        matches = [record for record in records if key in record_aliases(record)]
        if len(matches) != 1:
            missing.append(requested_id if not matches else f"{requested_id} (ambiguous)")
            continue
        record = matches[0]
        record_id = str(record.get("id") or requested_id)
        if record_id not in seen:
            selected.append(record)
            seen.add(record_id)
    if missing:
        raise ImportErrorBase(f"Unresolved selection: {', '.join(missing)}")
    return selected


def resolve_pdf(record: dict[str, Any], input_path: Path) -> tuple[Path | None, str | None]:
    raw_path = str(record.get("pdf_path") or "").strip()
    if not raw_path:
        return None, "pdf_path is missing"
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = input_path.parent / path
    path = path.resolve()
    if not path.is_file():
        return path, "PDF does not exist"
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            signature = handle.read(5)
    except OSError as exc:
        return path, f"Cannot read PDF: {exc}"
    if size < 256:
        return path, "PDF is implausibly small"
    if size >= 4 * 1024**3:
        return path, "PDF exceeds Zotero local API's file-size limit"
    if signature != b"%PDF-":
        return path, "File does not have a PDF signature"
    return path, None


def paper_plan(record: dict[str, Any], input_path: Path, metadata_only: bool) -> dict[str, Any]:
    pdf, pdf_error = resolve_pdf(record, input_path)
    if not metadata_only and pdf_error:
        action = "invalid_pdf"
    elif metadata_only:
        action = "planned_metadata_only"
    else:
        action = "planned"
    radar = record.get("radar") if isinstance(record.get("radar"), dict) else {}
    return {
        "id": record.get("id"),
        "title": record.get("title"),
        "doi": normalize_doi(record.get("doi")) or None,
        "score": radar.get("total"),
        "screening_status": radar.get("status"),
        "action": action,
        "pdf_path": str(pdf) if pdf else None,
        "pdf_error": pdf_error,
        "pdf_sha256": file_hash(pdf, "sha256") if pdf and not pdf_error and not metadata_only else None,
        "pdf_validation": "signature_and_hash_only; verify title/DOI and pages during download",
        "duplicate_check": "deferred_until_commit",
    }


def unwrap_item(wrapper: Any) -> dict[str, Any]:
    if not isinstance(wrapper, dict):
        return {}
    data = wrapper.get("data")
    return data if isinstance(data, dict) else wrapper


def successful_key(payload: Any) -> str:
    if not isinstance(payload, dict):
        raise ZoteroProtocolError("Zotero create response is not an object")
    successful = payload.get("successful")
    if not isinstance(successful, dict) or not successful:
        failed = payload.get("failed")
        raise ZoteroProtocolError(f"Zotero create failed: {failed or payload}")
    first = unwrap_item(next(iter(successful.values())))
    key = str(first.get("key") or "")
    if not key:
        raise ZoteroProtocolError(f"Zotero response lacks item key: {payload}")
    return key


class ZoteroClient:
    def __init__(self) -> None:
        self.server_id = ""
        self.api_key: str | None = None

    def preflight(self) -> None:
        response = request("GET", "/")
        if response.status != 200:
            raise ZoteroProtocolError(f"Zotero local API returned HTTP {response.status}")
        self.server_id = response.headers.get("zotero-server-id", "")
        api_version = response.headers.get("zotero-api-version", "3")
        if not self.server_id:
            raise ZoteroProtocolError("Zotero did not return Zotero-Server-ID; Zotero 10+ is required")
        if api_version != "3":
            raise ZoteroProtocolError(f"Unsupported Zotero API version: {api_version}")

    def read(self, path: str) -> Response:
        response = request("GET", path, headers={"Zotero-Server-ID": self.server_id})
        if response.status == 412:
            raise ZoteroProtocolError("Zotero Server ID changed; stop and rebuild the plan")
        if not 200 <= response.status < 300:
            raise ZoteroProtocolError(f"Zotero read failed HTTP {response.status}: {response.body[:300]!r}")
        return response

    def authorize(self) -> None:
        response = request(
            "POST",
            "/local/authorize",
            body=json_body({"appName": APP_NAME}),
            headers={
                "Content-Type": "application/json",
                "Zotero-Server-ID": self.server_id,
            },
        )
        if response.status == 403:
            raise AuthorizationDenied("The Zotero write-authorization dialog was denied")
        if response.status == 429:
            raise AuthorizationDenied("Too many Zotero authorization prompts; wait before retrying")
        if response.status != 200:
            raise ZoteroProtocolError(f"Zotero authorization failed HTTP {response.status}")
        payload = response.json()
        key = payload.get("key") if isinstance(payload, dict) else None
        if not isinstance(key, str) or not key:
            raise ZoteroProtocolError("Zotero authorization response did not contain a key")
        self.api_key = key

    def write(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
        retry_authorize: bool = True,
    ) -> Response:
        if not self.api_key:
            self.authorize()
        write_headers = {
            "Zotero-Server-ID": self.server_id,
            "Zotero-API-Key": self.api_key or "",
        }
        if headers:
            write_headers.update(headers)
        response = request(method, path, body=body, headers=write_headers)
        if response.status == 401 and retry_authorize:
            self.api_key = None
            self.authorize()
            return self.write(method, path, body=body, headers=headers, retry_authorize=False)
        if response.status == 412:
            raise ZoteroProtocolError("Zotero object/server version changed; stop and rebuild the plan")
        if not 200 <= response.status < 300:
            raise ZoteroProtocolError(f"Zotero write failed HTTP {response.status}: {response.body[:500]!r}")
        return response

    def template(self, item_type: str, link_mode: str | None = None) -> dict[str, Any]:
        query = f"/items/new?{urlencode({'itemType': item_type, **({'linkMode': link_mode} if link_mode else {})})}"
        payload = self.read(query).json()
        if not isinstance(payload, dict):
            raise ZoteroProtocolError(f"Invalid Zotero template for {item_type}")
        return payload

    def find_collection(self, name: str) -> str | None:
        path = f"{USER_PREFIX}/collections?{urlencode({'q': name, 'format': 'json'})}"
        payload = self.read(path).json()
        if not isinstance(payload, list):
            return None
        matches = []
        for wrapper in payload:
            data = unwrap_item(wrapper)
            if str(data.get("name") or "").strip().casefold() == name.strip().casefold():
                matches.append(str(data.get("key") or ""))
        if len(matches) > 1:
            raise ZoteroProtocolError("Multiple collections have that name; choose a unique collection name")
        return matches[0] if matches else None

    def ensure_collection(self, name: str) -> str:
        existing = self.find_collection(name)
        if existing:
            return existing
        response = self.write(
            "POST",
            f"{USER_PREFIX}/collections",
            body=json_body([{"name": name, "parentCollection": False, "relations": {}}]),
            headers={
                "Content-Type": "application/json",
                "Zotero-Write-Token": str(uuid.uuid4()),
            },
        )
        return successful_key(response.json())

    def search_items(self, query: str) -> list[dict[str, Any]]:
        path = f"{USER_PREFIX}/items?{urlencode({'q': query, 'qmode': 'everything', 'itemType': '-attachment', 'format': 'json'})}"
        payload = self.read(path).json()
        if not isinstance(payload, list):
            return []
        return [unwrap_item(item) for item in payload]

    def find_duplicate(self, record: dict[str, Any]) -> dict[str, Any] | None:
        doi = normalize_doi(record.get("doi"))
        if doi:
            for item in self.search_items(doi):
                if normalize_doi(item.get("DOI")) == doi:
                    return item
        title = str(record.get("title") or "").strip()
        if title:
            normalized = normalize_title(title)
            for item in self.search_items(title):
                # Equal titles with distinct known DOIs are distinct records.
                other_doi = normalize_doi(item.get("DOI"))
                if doi and other_doi and doi != other_doi:
                    continue
                year = str(record.get("published_online") or record.get("published_print") or record.get("publication_date") or record.get("date") or record.get("year") or "")[:4]
                other_year = str(item.get("date") or "")[:4]
                if year.isdigit() and other_year.isdigit() and year != other_year:
                    continue
                if normalize_title(item.get("title")) == normalized:
                    return item
        return None

    def create_item(self, data: dict[str, Any]) -> str:
        response = self.write(
            "POST",
            f"{USER_PREFIX}/items",
            body=json_body([data]),
            headers={
                "Content-Type": "application/json",
                "Zotero-Write-Token": str(uuid.uuid4()),
            },
        )
        return successful_key(response.json())

    def ensure_item_collection(self, item: dict[str, Any], collection_key: str) -> bool:
        item_key = str(item.get("key") or "")
        if not item_key:
            raise ZoteroProtocolError("Existing Zotero item has no key")
        collections = item.get("collections")
        collections = list(collections) if isinstance(collections, list) else []
        if collection_key in collections:
            return False
        version = item.get("version")
        if version is None:
            raise ZoteroProtocolError("Existing Zotero item has no version for safe collection update")
        collections.append(collection_key)
        self.write(
            "PATCH",
            f"{USER_PREFIX}/items/{item_key}",
            body=json_body({"version": version, "collections": collections}),
            headers={"Content-Type": "application/json"},
        )
        return True

    def child_attachments(self, parent_key: str) -> list[dict[str, Any]]:
        path = f"{USER_PREFIX}/items/{parent_key}/children?{urlencode({'itemType': 'attachment', 'format': 'json'})}"
        payload = self.read(path).json()
        if not isinstance(payload, list):
            return []
        return [unwrap_item(item) for item in payload]

    def attachment_file_matches(self, item: dict[str, Any], digest: str) -> bool:
        if str(item.get("md5") or "").lower() != digest:
            return False
        try:
            response = self.read(f"{USER_PREFIX}/items/{item['key']}/file/view/url")
            parsed = urlparse(response.body.decode("utf-8").strip())
            if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
                return False
            path = Path(unquote(parsed.path))
            return path.is_file() and file_hash(path) == digest
        except (OSError, KeyError, UnicodeError, ZoteroProtocolError):
            return False

    def find_attachment(self, parent_key: str, pdf_path: Path) -> tuple[str | None, bool]:
        """Find identical content, or reuse an empty attachment left by a failed upload."""
        digest = file_hash(pdf_path)
        pending_key = None
        for item in self.child_attachments(parent_key):
            if self.attachment_file_matches(item, digest):
                return str(item["key"]), True
            if (item.get("linkMode") in {"imported_file", "imported_url"}
                    and str(item.get("filename") or "").casefold() == pdf_path.name.casefold()
                    and not item.get("md5")):
                pending_key = str(item.get("key") or "") or None
        return pending_key, False

    def create_attachment(self, parent_key: str, pdf_path: Path) -> str:
        template = self.template("attachment", "imported_file")
        template.update({
            "parentItem": parent_key,
            "linkMode": "imported_file",
            "title": pdf_path.name,
            "filename": pdf_path.name,
            "contentType": mimetypes.guess_type(pdf_path.name)[0] or "application/pdf",
            "charset": "",
        })
        return self.create_item(template)

    def upload_file(self, attachment_key: str, pdf_path: Path) -> None:
        digest = file_hash(pdf_path)
        stat = pdf_path.stat()
        form = urlencode({
            "md5": digest,
            "filename": pdf_path.name,
            "filesize": stat.st_size,
            "mtime": int(stat.st_mtime * 1000),
        }).encode("ascii")
        endpoint = f"{USER_PREFIX}/items/{attachment_key}/file"
        first = self.write(
            "POST",
            endpoint,
            body=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "If-None-Match": "*",
            },
        )
        payload = first.json()
        if isinstance(payload, dict) and payload.get("exists") == 1:
            return
        if not isinstance(payload, dict) or not payload.get("url") or not payload.get("uploadKey"):
            raise ZoteroProtocolError("Invalid Zotero upload authorization")
        upload_url = urljoin(f"{BASE_URL}/", str(payload["url"]))
        local_api_url(upload_url)
        if not urlparse(upload_url).path.startswith("/api/local/uploads/"):
            raise ZoteroProtocolError("Unexpected Zotero local upload path")
        if payload.get("prefix") or payload.get("suffix"):
            raise ZoteroProtocolError("Expected the local raw-file upload protocol")
        with pdf_path.open("rb") as stream:
            upload_response = request(
                "POST", upload_url, body=stream,
                headers={
                    "Content-Type": str(payload.get("contentType") or "application/octet-stream"),
                    "Content-Length": str(stat.st_size),
                },
            )
        if not 200 <= upload_response.status < 300:
            raise ZoteroProtocolError(f"Zotero file upload failed HTTP {upload_response.status}")
        finalize = urlencode({"upload": payload["uploadKey"]}).encode("ascii")
        self.write(
            "POST",
            endpoint,
            body=finalize,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "If-None-Match": "*",
            },
        )


def creator_list(authors: Any) -> list[dict[str, str]]:
    if not isinstance(authors, list):
        return []
    creators: list[dict[str, str]] = []
    for author in authors:
        if isinstance(author, dict):
            family = str(author.get("family") or author.get("lastName") or "").strip()
            given = str(author.get("given") or author.get("firstName") or "").strip()
            name = str(author.get("name") or "").strip()
            if family:
                creators.append({"creatorType": "author", "firstName": given, "lastName": family})
            elif name:
                creators.append({"creatorType": "author", "name": name})
            continue
        text = str(author or "").strip()
        if not text:
            continue
        if "," in text:
            family, given = [part.strip() for part in text.split(",", 1)]
        else:
            parts = text.split()
            family, given = parts[-1], " ".join(parts[:-1])
        creators.append({"creatorType": "author", "firstName": given, "lastName": family})
    return creators


def set_if_present(template: dict[str, Any], key: str, value: Any) -> None:
    if key in template and value not in (None, "", []):
        template[key] = value


def item_type_for(record: dict[str, Any]) -> str:
    venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
    publication_type = str(record.get("publication_type") or "").lower()
    if venue.get("kind") == "conference" or "conference" in publication_type:
        return "conferencePaper"
    return "journalArticle"


def build_item(
    client: ZoteroClient,
    record: dict[str, Any],
    collection_key: str,
    extra_tags: list[str],
) -> dict[str, Any]:
    item_type = item_type_for(record)
    item = client.template(item_type)
    venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
    radar = record.get("radar") if isinstance(record.get("radar"), dict) else {}
    set_if_present(item, "title", record.get("title"))
    set_if_present(item, "abstractNote", record.get("abstract"))
    set_if_present(item, "DOI", normalize_doi(record.get("doi")))
    set_if_present(item, "url", record.get("url"))
    set_if_present(item, "date", record.get("published_online") or record.get("published_print"))
    set_if_present(item, "volume", venue.get("volume"))
    set_if_present(item, "issue", venue.get("issue"))
    set_if_present(item, "pages", venue.get("pages"))
    issn = venue.get("issn")
    if isinstance(issn, list):
        issn = ", ".join(str(value) for value in issn if value)
    set_if_present(item, "ISSN", issn)
    if item_type == "conferencePaper":
        set_if_present(item, "conferenceName", venue.get("name"))
        set_if_present(item, "proceedingsTitle", venue.get("proceedings_title") or venue.get("name"))
    else:
        set_if_present(item, "publicationTitle", venue.get("name"))
    if "creators" in item:
        item["creators"] = creator_list(record.get("authors"))
    if "collections" in item:
        item["collections"] = [collection_key]
    tags = ["research-radar"] + extra_tags
    if radar.get("status"):
        tags.append(f"radar:{radar['status']}")
    if radar.get("priority"):
        tags.append(f"priority:{radar['priority']}")
    if "tags" in item:
        item["tags"] = [{"tag": tag} for tag in dict.fromkeys(tags) if tag]
    if "extra" in item:
        score = radar.get("total")
        confidence = radar.get("confidence")
        lines = []
        if score is not None:
            lines.append(f"Research Radar Score: {score}")
        if confidence:
            lines.append(f"Research Radar Confidence: {confidence}")
        item["extra"] = "\n".join(lines)
    return item


def commit_record(
    client: ZoteroClient,
    record: dict[str, Any],
    plan: dict[str, Any],
    collection_key: str,
    tags: list[str],
    metadata_only: bool,
) -> dict[str, Any]:
    # Preserve created parent/attachment keys in the report if a later step fails.
    result = plan
    if result["action"] == "invalid_pdf":
        return result
    if not metadata_only and file_hash(Path(str(result["pdf_path"])), "sha256") != result.get("pdf_sha256"):
        raise ZoteroProtocolError("PDF changed after planning; rebuild the plan before importing")
    duplicate = client.find_duplicate(record)
    if duplicate:
        parent_key = str(duplicate.get("key") or "")
        if not parent_key:
            raise ZoteroProtocolError("Matched Zotero item has no key")
        result["parent_status"] = "existing_reused"
        result["collection_action"] = (
            "existing_item_added_to_collection"
            if client.ensure_item_collection(duplicate, collection_key)
            else "already_in_collection"
        )
    else:
        item = build_item(client, record, collection_key, tags)
        parent_key = client.create_item(item)
        result["parent_status"] = "metadata_only_created" if metadata_only else "created"
        result["collection_action"] = "created_in_collection"
    result["zotero_item_key"] = parent_key
    result["duplicate_check"] = "complete"
    if metadata_only:
        result["action"] = result["parent_status"]
        return result

    pdf_path = Path(str(result["pdf_path"]))
    attachment_key, already_present = client.find_attachment(parent_key, pdf_path)
    if already_present:
        result["attachment_key"] = attachment_key
        result["action"] = "skipped_duplicate_attachment"
        return result
    attachment_key = attachment_key or client.create_attachment(parent_key, pdf_path)
    result["attachment_key"] = attachment_key
    result["attachment_status"] = "pending_upload"
    client.upload_file(attachment_key, pdf_path)
    result["attachment_status"] = "uploaded"
    result["action"] = "attachment_uploaded"
    return result


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def export_ris(records: list[dict[str, Any]], path: Path) -> None:
    """Offline metadata fallback. PDFs remain separate for explicit manual attachment."""
    lines: list[str] = []

    def field(tag: str, value: Any) -> None:
        if value not in (None, "", []):
            lines.append(f"{tag}  - {' '.join(str(value).split())}")

    for record in records:
        venue = record.get("venue") if isinstance(record.get("venue"), dict) else {}
        field("TY", "CONF" if item_type_for(record) == "conferencePaper" else "JOUR")
        field("TI", record.get("title"))
        for creator in creator_list(record.get("authors")):
            field("AU", creator.get("name") or f"{creator.get('lastName', '')}, {creator.get('firstName', '')}".strip(", "))
        field("T2", venue.get("name"))
        field("AB", record.get("abstract"))
        field("DO", normalize_doi(record.get("doi")))
        field("UR", record.get("url"))
        field("PY", str(record.get("published_online") or record.get("published_print") or "")[:4])
        field("DA", record.get("published_online") or record.get("published_print"))
        field("VL", venue.get("volume"))
        field("IS", venue.get("issue"))
        field("SP", venue.get("pages"))
        for issn in venue.get("issn", []) if isinstance(venue.get("issn"), list) else [venue.get("issn")]:
            field("SN", issn)
        field("KW", "research-radar")
        field("ID", record.get("id"))
        lines.extend(["ER  -", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Scored Research Radar JSONL")
    parser.add_argument("--ids", required=True, help="Comma-separated exact IDs or DOIs approved by the user")
    parser.add_argument("--collection", required=True, help="Exact Zotero collection name")
    parser.add_argument("--tags", default="", help="Optional comma-separated Zotero tags")
    parser.add_argument("--metadata-only", action="store_true", help="Explicitly create metadata without requiring PDFs")
    parser.add_argument("--commit", action="store_true", help="Write to Zotero; omission is a no-network dry run")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    parser.add_argument("--export-ris", type=Path, help="Offline RIS metadata export for the selected IDs; does not contact Zotero")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    report: dict[str, Any] = {"mode": "commit" if args.commit else "dry_run"}
    try:
        if not args.collection.strip():
            raise ImportErrorBase("--collection must be non-empty")
        if args.commit and args.export_ris:
            raise ImportErrorBase("--export-ris and --commit are mutually exclusive")
        records = load_jsonl(args.input)
        selected = select_records(records, args.ids)
        plans = [paper_plan(record, args.input, args.metadata_only) for record in selected]
        report = {
            "mode": "commit" if args.commit else "dry_run",
            "collection": args.collection,
            "selected_count": len(selected),
            "metadata_only": args.metadata_only,
            "results": plans,
        }
        if args.export_ris:
            export_ris(selected, args.export_ris)
            report.update(mode="ris_export", ris_path=str(args.export_ris.resolve()),
                          zotero_written=False, attachment_import="manual")
            report["results"] = [dict(plan, action="metadata_exported") for plan in plans]
            write_report(args.report, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if not args.commit:
            write_report(args.report, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if all(plan["action"] != "invalid_pdf" for plan in plans) else 2

        if all(plan["action"] == "invalid_pdf" for plan in plans):
            write_report(args.report, report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 2
        tags = [tag.strip() for tag in args.tags.split(",") if tag.strip()]
        client = ZoteroClient()
        client.preflight()
        collection_key = client.ensure_collection(args.collection)
        results: list[dict[str, Any]] = []
        report["results"] = results
        report["collection_key"] = collection_key
        for index, (record, plan) in enumerate(zip(selected, plans)):
            try:
                results.append(commit_record(client, record, plan, collection_key, tags, args.metadata_only))
            except AuthorizationDenied as exc:
                failed = dict(plan, action="authorization_denied", error=str(exc))
                results.append(failed)
                results.extend(dict(p, action="not_attempted") for p in plans[index + 1:])
                raise
            except Exception as exc:  # continue the approved batch and report per-paper failure
                failed = dict(plan)
                failed["action"] = "failed"
                failed["error"] = str(exc)
                results.append(failed)
            write_report(args.report, report)
        report["results"] = results
        report["collection_key"] = collection_key
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if all(item["action"] not in {"failed", "invalid_pdf"} for item in results) else 3
    except AuthorizationDenied as exc:
        report.update(status="authorization_denied", error=str(exc))
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 4
    except ZoteroNotRunning as exc:
        report.update(status="zotero_not_running", error=str(exc))
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 5
    except (ImportErrorBase, OSError, ValueError) as exc:
        report.update(status="failed", error=str(exc))
        write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
