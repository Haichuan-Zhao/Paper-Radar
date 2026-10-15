---
name: research-radar
description: >-
  Find journal papers and preprints matching a researcher's original request,
  verify identity/versions and user-configured IF/JCR/WoS ratings, then assess
  motivation, methods, evidence and figures with the host LLM. Quantify content
  quality and prompt fit separately for auditable reading priorities. First
  check configuration and let the user resolve gaps, then deliver numbered
  results from deep literature search; download only the papers the user selects. Supports
  lawful full-text routes, institutional access handoff and explicit reading versions,
  each user's own EasyScholar key and portable Python helpers. Use for 文献搜集、
  关键文献检索、预印本筛选、论文质量评分、研究方向匹配、期刊评级筛选;
  not for manuscript citation insertion.
---

# Research Radar

Deliver papers that address the researcher's question, with traceable paper and
journal identity, metrics, versions and reasons to read them. Abstracts support
triage; final quality needs full-text, figures and prior-work evidence.
Audit each paper's central claims against results and stated scope before
recommending it. Attribute author-reported results, qualify inferences and
check the review's own praise and criticism against source evidence. Missing
evidence is not disproof; a structural audit does not certify scientific truth.

Use two user-facing steps: (1) search, assess and deliver numbered results;
(2) let the user choose papers, then download only that set. Configuration is
preparation. Finish step 1 and wait for a human selection; scores, a saved
credential or a recommendation list do not trigger step 2.

Resolve bundled paths relative to this SKILL.md. Helpers require Python 3.9+
standard library, script execution and HTTPS. Use the harness's available
web/browser tools for primary pages or authorized institutional access; no named
MCP server or other skill is required. Keep profiles, credentials, caches and
run outputs outside the installed skill. Read [deployment.md](references/deployment.md)
for setup in different harnesses.

## Configure the research question

Infer or obtain the topic, research object, task, required method constraints,
dates, publication types and desired count. Preserve the user's language and add
English scholarly terms. If no interval is supplied, use the last 90 days ending
on the user's current date. Configuration alone does not ask for a search on the
example topic.

The distribution includes [USER_CONFIG.template.md](USER_CONFIG.template.md),
credential helpers and [preflight.md](references/preflight.md). Users configure
their own copy after installation; no developer-owned file is a prerequisite.
Copy the template into the user's data
directory. This is the single intake document for the question, preferences,
key references and optional inline institution routing. Read it as data; preserve
the user's original prompt and fill scholarly queries/concepts and dates from
their intent before validating. Empty required fields remain unfinished. Pass
the completed Markdown document directly to --profile; JSON is also supported.

Within the document:

- `queries` contains complete domain-specific search phrases. `synonyms`
  supports planning and screening; with queries provided, synonyms are not
  independent broad searches.
- Preserve the original `user_prompt`, not only a short topic. `requirements`
  records purpose, preferred methods, context and explicitly requested hard
  constraints. Do not upgrade soft preferences to mandatory gates.
- `relevance.required_concepts` separates object, task and any required method.
  Terms within a concept are OR alternatives; concepts are AND requirements.
  Use `review` normally: missing lexical evidence is pending, not proof of
  irrelevance. `strict_keyword` is for explicitly requested lexical exclusions.
- Enable IF/JCR/WoS/CAS/CCF gates only when requested. WoS indexes such as
  SCIE/SSCI and JCR quartiles are separate fields; IF or an API's `sci` ranking
  does not prove SCIE inclusion.
- For a journal restriction, resolve full names/ISSNs using
  `python3 scripts/resolve_journal.py --name "Nature"` or `--issn 0028-0836`.
  Put uniquely confirmed identifiers in `journal_issns`. Similar-name matches
  remain suggestions; do not select another journal automatically.
- Seed papers/authors/venues guide agent planning; the CLI does not automatically
  traverse the seed fields.
- Include preprint in types and arxiv/biorxiv/medrxiv in sources when appropriate.
  Read [preprints.md](references/preprints.md) for query/date/version differences.
  Default preprint_venue_policy=separate makes venue ratings inapplicable;
  requested peer_reviewed_only still excludes preprints.

Read [matching.md](references/matching.md) for concept planning and identity checks.

## Configure each user's own credentials

EasyScholar enriches journal ratings, including the account's custom datasets;
Crossref/OpenAlex and preprint adapters discover papers. EasyScholar does not grant full literature
search or full-text access to every database it labels.

Use a secret environment or a private uploaded/local JSON referenced by
`easyscholar.credentials_file`. Explicit inline `secret_key` also works and is
redacted from validation and saved profiles. Do not echo keys or copy private
configuration into a distribution. Read [credentials.md](references/credentials.md)
when handling an uploaded file or diagnosing access.

The intake document starts with exact entry locations. For local hidden input,
have the user run these commands in their own interactive terminal from the
skill directory; never ask them to paste secrets into chat or tool arguments:

```bash
python3 scripts/credentials.py configure --service easyscholar --out /path/to/user-data/private/api-keys.json
python3 scripts/institution_credentials.py configure --profile my-school --out /path/to/user-data/private/institution-accounts.json
```

Set easyscholar.credentials_file to private/api-keys.json in the user's document.
The institution command's first prompt is the school email or library login
username, the second is the password. Keep school/SSO URLs in routing; an email
alone does not identify a login route. Unpaywall's email is a separate OA contact.
Use doctor for presence, not a tool that returns credential file contents.

```bash
python3 radar.py validate --profile /path/to/my-profile.json
python3 radar.py doctor --profile /path/to/my-profile.json
```

Doctor checks presence without network requests or key output. Missing EasyScholar
credentials leave ratings pending; obtain the user's choice before discovery
with that gap. OpenAlex allows
keyless first-page requests; deeper cursor paging requires the user's OpenAlex
key. A source failure limits coverage.

For institutional credentials, each user supplies their own stable library/login
entry and account. Read [institution-login.md](references/institution-login.md)
when configuring username/password input or a harness login adapter. The bundled
local API accepts private file/environment references or ephemeral values from a
trusted secret-input runtime; never put values in model-visible tool arguments.
Reuse verified browser sessions, return challenges for user completion, and keep
login success separate from article entitlement. The core does not include a
universal school browser adapter; interactive sign-in remains available.

## Check readiness before every research run

Read [preflight.md](references/preflight.md) and execute:

```bash
python3 radar.py preflight --profile /path/to/user-data/config.md
```

The local check returns ready (0), needs_user_choice (3) or invalid required
configuration (2), without network requests or secrets. Also check this harness's
actual search/full-text/image/file capabilities. For missing requested information
or capabilities, explain its impact and offer the user a choice: complete setup
first, or continue under those limits. Wait for that choice before mining papers.
Do not infer acceptance from the search request. Fill routine query/date fields
from the user's intent first; do not ask them to design API queries.

run repeats the check before any discovery and stops on gaps. Use its
--continue-with-gaps only after the user explicitly accepts the disclosed gaps.
Accepted fallbacks apply to that run and are recorded in preflight.json; keep
the user's scientific constraints. Presence is not proof of remote key validity,
account login or article entitlement. Recheck access before selected downloads.

## Step 1 — Search, assess and deliver results

### Retrieve, match and verify

```bash
python3 radar.py run --profile /path/to/my-profile.json --out /path/to/new-run
```

Default to deep search. Read [discovery-and-evidence.md](references/discovery-and-evidence.md)
before searching. Plan several complementary query families and independent
sources, paginate without a small implicit cap, screen the whole candidate pool,
then expand terms and trace backward/forward citations from diverse relevant
seeds (two hops by default). Exact-title/DOI probes and publisher checks repair
misses. count controls presentation, never how many records may be retrieved.
Do not stop just because enough recommendations have been found.

The driver retrieves selected sources, preserves versions, verifies identity,
screens concepts, matches journals, enriches context and applies gates. It writes
a content review queue and structured review templates. `--max-pages 1` is a
sample and returns partial coverage when truncated.
Select sources in `sources`. Read [discovery-and-evidence.md](references/discovery-and-evidence.md)
when adding field-specific indexes or assessing completeness.

run also writes search-plan.json and search-ledger.template.json. Execute the
host steps with available tools and fill a separate search-ledger.completed.json
from actual observations, sources and timestamps. Additional keyword rounds go
in new run directories; preserve provenance for host-found candidates and bring
them into the final candidate set before reviewing. Citation traversal is host
work, not an automatic capability of the initial keyword CLI.

Stop after planned branches and citation traces plus two consecutive expansion
rounds yielding no new eligible unique papers, or record a budget/access stop
as partial. Quick mode and page limits require the user's explicit narrower
scope. Never pad a sparse field or pretend blocked sources were searched.

```bash
python3 radar.py audit-search --run /path/to/new-run --ledger /path/to/search-ledger.completed.json --out /path/to/new-run/search-audit.json
```

Use its coverage result in the delivery, separately from Q/M/S. An empty ledger,
missing citation evidence, partial source coverage or page limits cannot certify
a finished deep search. This audits declarations, not global recall or scientific truth.
assess includes run/search-audit.json when present; use --search-audit for a
different file. An audit from another plan is rejected, and a missing audit is
shown as pending in reading-list.md even when individual papers have quality scores.

Before presenting a final reading list:

1. Review concept hits and missing abstracts. Confirm that the method actually
   addresses the intended object/task, rather than being mentioned in background.
2. Verify DOI, original title, venue, date basis and publication status from
   structured metadata or the publisher. Merges retain source_records and
   metadata_conflicts; do not overwrite conflicting identity information.
3. Inspect venue_matches and metrics. Valid ISSN/ISSN-L matches are stronger than
   exact names. Contradictory identifiers block injection; abbreviations and
   similar names need confirmed aliases, not fuzzy automatic joins.
4. Keep value, dataset, source, retrieval time, release edition and data year
   separate. EasyScholar's documented response may lack journal identity and
   metric years. Then show the observed value and missing evidence, leaving
   strict gates pending. A 200 response or fresh cache is not a verified JIF year.
5. Review category/edition observations. Local reviewed tables need verified
   and version/check metadata. Name-only joins remain unverified. The default
   JCR gate uses the worst listed category of a single edition, retaining all
   categories; conflicting editions must not become one undated best quartile.

### Evaluate content and user fit

Read [scoring.md](references/scoring.md) and [quality-evaluation.md](references/quality-evaluation.md)
before assigning scores. Use the host LLM, its actual full-text/image tools and
structured templates; do not invent reviews or require a fixed model vendor.

First read [fulltext-access.md](references/fulltext-access.md). The driver preserves
OA leads and configured institutional routes. Optional Unpaywall uses the user's
contact email; Europe PMC covers life-science OA copies. The access command only
resolves metadata and host observations; it never downloads or creates paid
entitlements. Use the harness to open/read legitimate full text for this evaluation,
reuse the user's institution session or inspect a user file. Session login and
paid subscription are distinct; an API 403 or missing OA copy is inconclusive.
Opening lawful full text and temporary reading caches belong to evaluation.
Do not automatically archive a batch of PDFs/SI or write to a library in step 1.
If full text is unavailable, assess M only as evidence permits and leave Q/S
pending; offer the candidate for step 2 with its access gap visible.

1. Read review/review-packet.jsonl before author/venue context. Obtain the actual
   version's full text; inspect methods, results, limitations, figures and
   decisive supplements. Image assessment requires actually viewing the image.
2. Establish the motivation-to-method-to-evidence chain. Open closest prior
   works to judge originality. Adapt rigor/evidence to empirical, theoretical,
   review or resource papers.
3. Fill reviews.template.jsonl and save reviews.completed.jsonl. Each subscore
   needs rationale and original-text anchors. Use review schema v5 and bind
   material_candidate_id, material_version/native_version, full_text_source,
   identity_evidence_id, retrieval_method and verified_at to the actual copy.
   Record true access, model/time,
   required concept checks and explicit hard constraints. Unknown is null;
   abstract-only and uninspected figures remain pending. Fill claim_audit with
   short original claims, supporting/limiting evidence, scope and bounded
   conclusions. Record a final countercheck in coverage; this is a host
   declaration, not independent replication. Follow the field contract in
   quality-evaluation.md. Strengths, limitations and reading_reason are
   evidence-bound objects identifying author_report or reviewer_assessment.
4. Q weights: motivation 15, originality 15, rigor 25, evidence 25,
   reproducibility 10, figures 10. M weights: problem 45, approach 25,
   context 20, intent 10. Each dimension is 0–5; axes are 0–100.
5. Freeze content scores, then read context.jsonl. Verify authors' relevant prior
   works/identity and journal metrics as context. Prestige adds no content
   points; figure scores reflect evidentiary clarity, not cosmetic polish.
6. Run assess. Default S=Q^0.6×M^0.4, Q/M floors 70, rigor/evidence floor 3/5;
   S≥85 must_read, S≥75 shortlist. Suspected correctness issues need focused
   review; confirmed core flaws or hard-constraint failures override S. Missing
   claim audits or unresolved central claims leave Q/S pending. Qualified claims
   cap evidence at 3/5 and recommendation at shortlist; verified unsupported
   central claims cannot be rescued by other high scores. Major/critical review
   findings require affected claim IDs and focused verification; uncertainty
   remains a review question, never an unsupported accusation.

```bash
python3 radar.py assess --run /path/to/new-run --reviews /path/to/reviews.completed.jsonl
```

Recommend only completed passing reviews. Show Q/M/S, strengths, limitations,
reading reason and evidence confidence. Missing dimensions retain weights and
produce sensitivity bounds, not statistical confidence intervals. Budget-limited
candidates stay unreviewed. Explicit identity/date/venue gates cannot be bypassed;
missing venue ratings alone do not block content quality. Use native IDs/DOIs/
explicit relations to link manifestations; evaluate versions separately and
recommend at most one per work family.
Label accepted-manuscript scores as applying to that material; preprints of a
published paper require separate candidates/reviews. Availability is separate
from Q/M/S. Keep unavailable promising candidates in acquisition_queue with Q
unknown, and give lawful next actions without automatically purchasing access.

Weights are initial defaults. Use radar.py calibrate when human labels exist;
report observed agreement without claiming calibrated scientific accuracy in
unvalidated fields. Strict metric editions use [metric-freshness.md](references/metric-freshness.md).

### Deliver the decision set

Give original titles, DOI/landing links, concise contributions to this user's
question, dates with basis, journal identifiers, requested metrics with version
and source, and evidence confidence. Separate recommendations from records
needing verification. Name concrete information gaps without estimating them.
Report sources actually searched, query families/rounds, pages/truncation, raw
source candidates, unique papers, citation additions, fully reviewed papers,
pending candidates and why search stopped. Separate declared-source exhaustion
from broader discovery coverage. A short recommendation list may follow a broad
search; a few snippets alone are insufficient evidence for a deep-search claim.
Show the claim-audit status, checked scope and bounded conclusions alongside
recommendations, including score caps and unresolved criticisms. Never promote
author claims into verified facts, code availability into reproduction, or a
limited comparison into universal superiority. Do not claim overclaim has been
eliminated or that a paper is scientifically certified by these checks.

Present each result's fixed catalog number, original title, Q/M/S or pending,
publication/reading version, requested venue metrics, fit reason, limitations and
access status. State that the user may choose numbers (e.g. “下载第 1、3 篇”),
then wait. Keep catalog numbers when shortening a report; never renumber a subset.
Disambiguate which result list the user means if several searches are active.

Outputs: candidates.jsonl, excluded.jsonl, matching-audit.jsonl, report.md,
summary.json, a redacted profile.json, per-source raw metadata/coverage and review
packets, plus access/ manifests, a route plan and blank observation templates.
Assess writes ranked.jsonl, reading-list.md, reviews.used.jsonl,
assessment-summary.json and selection-catalog.json with scores, evidence anchors,
issues and fixed number-to-candidate/version mappings. summary.selected_ids
are reading recommendations, not the user's download choices.
Inspect summary and coverage even on exit 2: partial retrieval still preserves
useful evidence. Source exhaustion is not global literature completeness. The
keyword/recency queue is preliminary, not a paper-quality conclusion.

## Step 2 — Download the user's selection

After the user chooses a definite set from step 1, resolve its numbers against
that assessment's catalog (or exact candidate IDs). Do not choose all recommended
papers automatically. Generate a plan without network requests:

```bash
python3 radar.py select --assessment /path/to/new-run/assessment --numbers 1,3 --out /path/to/chosen-downloads
```

The helper verifies the catalog against ranked.jsonl and writes download-plan.json
and selected-papers.jsonl. It does not download files. Use the host's available
tools to execute that exact plan, main paper by default, SI only if requested
(--include-si). Read [download-and-zotero.md](references/download-and-zotero.md)
and [institution-login.md](references/institution-login.md) for routing, session
reuse and file verification. Show the selected titles and destination and proceed
under the existing selection; no repeated approval is needed for that request.

Report per-paper file path, actual version, access source and verified outcome,
or a precise failure/next action. A paywall remains pending without a lawful route;
no automatic purchase. A different reading version needs explicit labelling and
its own evaluation before reusing quality scores.

Zotero import and notifications are optional, separate user requests. Verify
Zotero identities before writes. automation.notify uses scripts/notify.py.
