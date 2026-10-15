# Lawful Download and Zotero Import

Read this reference after the user has selected a definite set of papers for
download/import, or when configuring the download workflow.

## Selected batch

This is stage 2. Stage 1 finishes with a numbered reading-list.md and its
selection-catalog.json, then waits for a human selection. Recommendation
summary.selected_ids means recommended reading, never a download request.

Resolve the user's selected numbers/IDs/DOIs to an exact list from the same
assessment. Keep the catalog's numbers when presenting a shorter response;
do not renumber a subset. Bind numbers to its catalog_id if several results
exist. Clarify an ambiguous reference before acting.

```bash
python3 radar.py select --assessment /path/to/new-run/assessment \
  --numbers 1,3,5 --out /path/to/chosen-downloads
```

Alternatively use --ids with exact, versioned candidate IDs. The helper rejects
unknown/duplicate selections and mismatched catalogs, preserves order and
scores, and writes download-plan.json and selected-papers.jsonl. It performs
no network requests. Do not claim that a planned download is complete. The host
then downloads this exact set to the plan's destination (default its pdfs/
subdirectory), verifies files and delivers a per-paper download manifest.
For older assessment results without a catalog, run assess into a new directory
using the existing candidates and completed reviews; do not overwrite evidence.

The user's explicit selection supplies authorization to download those papers.
Import into Zotero only when the user also requests import. Show the selected
titles and destination, make the internal plan, and proceed without asking for
the same approval again. Clarify
only an ambiguous selection or destination. Include the main paper by default;
include Supporting Information (SI) with --include-si only when requested.

A requested full-text quality assessment includes opening and reading lawful
full text for that evaluation, using the harness's normal tools. It does not
automatically request a persistent batch PDF/SI collection, purchases or Zotero
writes. Temporary reading caches are allowed; do not turn assessment into
automatic archival downloads. A selected download request does not authorize importing other records
or changing existing Zotero items. Read [fulltext-access.md](fulltext-access.md)
for metadata routes, access observations and version binding before acquisition.

## Download routing

Use the host's available lawful download tools or a suitable installed downloader.
The portable core contains no universal publisher or school downloader. Preserve
the manifest and typed failures; if the harness cannot save files, report that
capability gap and provide lawful routes. Use these route principles:

```text
exact DOI/title and publisher identified
|- configured Elsevier/Springer Nature/IEEE full-text API entitlement -> try provider API
|  `- on failure -> lawful OA resolution
|- other English publisher -> lawful OA resolution first
|  `- unavailable -> user-authorized institutional browser route
`- no authorized route -> report unavailable; do not seek pirate mirrors
```

The existing authenticated browser profile is the authority boundary. If a
publisher or library route opens a new unauthenticated profile, do not conclude
that the institution lacks access.

## Reusable login profile

Read [institution-login.md](institution-login.md). Use the institution routing in
user config or its named profile, and reuse the same verified browser context for
the selected batch. Check the actual article's entitlement after session login.
If expired, retain the batch at session_refresh_required and refresh the session
once, then resume remaining papers. Account/password input requires the host's
private local adapter; otherwise use interactive sign-in. CAPTCHA/2FA stays in
the user's browser. Do not export session cookies or tokens.

## File verification

Before Zotero import, verify:

- the file exists, is plausibly sized, and begins with `%PDF` when PDF was
  requested;
- page count is nonzero;
- extracted text or metadata matches the selected title or DOI;
- SI is labelled as belonging to the same paper;
- the manifest records source URL, access mode, retrieval time, SHA-256, and
  typed failure if any.

Do not label HTML, a login page, or a native database format as a PDF.

## Zotero local import

Use Zotero 10+ local API, not direct SQLite access. Official documentation:

- Local API: https://www.zotero.org/support/dev/web_api/v3/local_api
- Write requests: https://www.zotero.org/support/dev/web_api/v3/write_requests
- File uploads: https://www.zotero.org/support/dev/web_api/v3/file_upload

Preconditions:

- Zotero desktop is open.
- Settings -> Advanced -> "Allow other applications on this computer to
  communicate with Zotero" is enabled.
- The user approves the local write-authorization dialog.
- The dry-run plan contains only the selected IDs.

Run dry-run first:

```bash
python3 scripts/zotero_import.py \
  --input scored-papers.jsonl \
  --ids "doi:10.x/a,doi:10.y/b" \
  --collection "Research Radar"
```

For the already authorized selected set, after validating the dry run:

```bash
python3 scripts/zotero_import.py \
  --input scored-papers.jsonl \
  --ids "doi:10.x/a,doi:10.y/b" \
  --collection "Research Radar" \
  --commit \
  --report zotero-import-report.json
```

The importer requires a local `pdf_path` by default. Its programmatic file
check covers signature, size and content hash; the download stage must verify
page count and selected-paper identity before assigning that path. Do not
represent the signature check alone as title/DOI validation. Use `--metadata-only`
only when the user explicitly asks to create metadata items without attachments.

It checks DOI/title duplicates before creating items. Distinct DOIs with a
shared title remain distinct, and same-named attachments are compared by
content hash rather than filename alone. When a matching item
already exists, it safely adds that item to the selected collection, reuses the
parent, and only plans a missing verified PDF attachment; it does not overwrite
bibliographic fields. The local authorization key stays in memory and is never
printed or saved.

If Zotero is older than version 10 or local writes are unavailable, use the
offline RIS fallback for the selected records and deliver verified PDFs
separately for manual attachment. This exports metadata, not a successful local
Zotero write:

```bash
python3 scripts/zotero_import.py \
  --input scored-papers.jsonl --ids "doi:10.x/a,doi:10.y/b" \
  --collection "Research Radar" --export-ris selected-papers.ris \
  --report ris-export-report.json
```

`--export-ris` needs no running Zotero or PDF and cannot be combined with
`--commit`. If an attachment upload fails after a parent or attachment item was
created, retain the reported item keys, inspect that state, and retry the
missing upload. Do not blindly recreate the parent. Never modify
`zotero.sqlite`.

## Result report

For every selected record, report one of:

```text
planned
created
existing_reused
attachment_uploaded
metadata_only_created
metadata_exported
skipped_duplicate_attachment
invalid_pdf
download_unavailable
session_refresh_required
zotero_not_running
authorization_denied
failed
```

Report partial success per paper rather than claiming the batch succeeded.
