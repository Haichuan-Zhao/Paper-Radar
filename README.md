# Research Radar

English | [简体中文](README.zh-CN.md)

**Find papers that matter to your research, assess the evidence, and download the ones you choose.**

Research Radar is a portable Agent Skill for discovering journal articles and preprints,
checking paper and journal identities, and building an evidence-grounded reading list.
It uses the host agent's LLM to assess **paper quality (Q)** and **fit to your original
request (M)** separately. Journal metrics provide context; the paper's methods,
results, figures and limitations determine its content assessment.

The workflow has two steps: **search and assess first; download only after you select papers.**

- **Deep discovery:** complementary queries across Crossref, OpenAlex, arXiv,
  bioRxiv and medRxiv, with pagination and an auditable search ledger.
- **Identity checks:** DOI/native identifiers, publication versions, dates,
  ISSN/ISSN-L and ambiguous journal names.
- **Your own journal data:** EasyScholar keys and local CSV/JSON metric tables,
  retaining source, edition and year for IF, JCR, WoS, CAS, CCF and custom ratings.
- **Evidence-based review:** source anchors for claims, strengths, limitations,
  quality scores and reading recommendations, with checks against overclaiming.
- **User-controlled access:** open-access routes, user-provided files and
  optional institutional browser handoff using each user's own configuration.

Licensed under [MIT](LICENSE). The Python helpers require **Python 3.9+**, the
standard library and HTTPS. Full-text reading, image inspection and institutional
browser actions require suitable tools in the host agent.

## How the two steps work

| Step | What happens | What you receive |
|---|---|---|
| 1. Discover and assess | Check configuration, expand the research question into queries, retrieve and verify candidates, read available evidence and review claims | A numbered reading list with Q/M/S, metric provenance, reasons to read, limitations and access status |
| 2. Select and download | You choose numbers from that list; the agent resolves the frozen paper/version mapping and retrieves only those papers | Validated selected files and a per-paper download outcome |

Step 1 may open lawful full text and use temporary reading caches to support review.
It does not automatically archive a batch of PDFs. When evidence is unavailable,
Q/S stay pending and the paper remains in the review or access queue.
Supplementary information and Zotero import require an explicit request.

## Installation

Clone or download this repository and install the **entire
[research-radar/](research-radar/)** directory using your harness's skill mechanism.
The entry point is [SKILL.md](research-radar/SKILL.md). Hosts without automatic skill
discovery can read that file and execute the bundled CLI using its absolute path.

No additional model API key, fixed MCP server or other skill is required. Actual
script, network, PDF, image and browser capabilities depend on the harness.
See [deployment and portability](research-radar/references/deployment.md) for the
capability requirements and installation boundaries.

## One document for your configuration

Copy [USER_CONFIG.template.md](research-radar/USER_CONFIG.template.md) into your own
data directory, for example `user-data/config.md`. Keep the installed template blank.
Fill in your research question, original prompt, reading purpose, dates and constraints;
the agent can help derive scholarly queries and concept groups from your wording.
Keep preferences distinct from mandatory exclusions.

This document also contains references to your own keys and optional school access.
There is no project server or upload form. Store credentials locally or use the
host's secret environment; do not paste them into chat or commit them to GitHub.

Run these commands in **your own interactive terminal**, from the installed skill
directory, replacing `/path/to/user-data` with your data directory:

```bash
python3 scripts/credentials.py configure --service easyscholar --out /path/to/user-data/private/api-keys.json
python3 scripts/institution_credentials.py configure --profile my-school --out /path/to/user-data/private/institution-accounts.json
```

| Information | Where to configure it |
|---|---|
| EasyScholar key | Enter it at the hidden terminal prompt; set `easyscholar.credentials_file` in your document to `"private/api-keys.json"` |
| Library email or account and password | Use the institution helper's prompts; enter the account type your school actually uses |
| School and login entry points | Fill `fulltext_access.institution.routing`, including school name, library URL, SSO URL and allowed domains; enable institutional access when ready |
| Optional OpenAlex key or local rating tables | Use the corresponding credential reference or `venue_metrics_files` fields in the same document |

The credential helpers save **local plaintext files** with POSIX mode `600`.
Host-managed secret environments are an alternative. A school email alone does not
identify a login route or prove subscription entitlement. Unpaywall's contact email
is a separate service setting. Configuration paths are relative to the document's
directory; JSON profiles are also supported.

See [credentials](research-radar/references/credentials.md) and
[institutional access](research-radar/references/institution-login.md) for the exact
formats, login adapter contract and human MFA/captcha handoff.

## Quick start

Ask the host agent to use Research Radar with your configuration document, for example:

> Use Research Radar with my config.md. Search deeply for papers addressing my
> research question, verify identities and journal information, then assess the
> available full-text evidence. Show numbered results with quality, fit, limitations
> and access status. Wait for my paper selection before downloading.

The commands below run **from the skill directory**. Use a new output directory for
each run and replace all example paths with your own.

```bash
python3 radar.py validate --profile /path/to/user-data/config.md
python3 radar.py preflight --profile /path/to/user-data/config.md
python3 radar.py run --profile /path/to/user-data/config.md --out /path/to/user-data/new-run
```

Every `run` checks configuration before discovery. Missing enabled keys, account
information or other required settings cause exit code `3`: the agent explains the
gaps and lets you complete the configuration or explicitly accept the limitations.
Only after you choose to continue may it add `--continue-with-gaps`. The decision is
recorded in the run's `preflight.json` without rewriting your original configuration.
Local credential presence, remote validity, login and paper entitlement are separate
states. See the [preflight protocol](research-radar/references/preflight.md).

`run` creates candidate records, a search plan/ledger template and review packets.
The host executes query expansion, citation tracing and gap searches, records its
actual work, and reads full text and figures. Built-in keyword adapters do not
automatically perform the citation traversal. The default deep plan includes two
citation hops; `count` sets the desired reading-list size, not a retrieval cap.
Pagination, budgets and unavailable sources must remain visible in coverage reports.
See [discovery and evidence](research-radar/references/discovery-and-evidence.md).

After the host completes evidence-grounded reviews:

```bash
python3 radar.py assess --run /path/to/user-data/new-run --reviews /path/to/reviews.completed.jsonl
```

The assessment produces `reading-list.md` and `selection-catalog.json` in the run's
`assessment/` directory by default. Read the list, then select papers, for example:

> Download papers 1, 3 and 5 from this reading list.

The host creates a version-bound plan:

```bash
python3 radar.py select --assessment /path/to/user-data/new-run/assessment --numbers 1,3,5 --out /path/to/user-data/chosen-downloads
```

`select` writes `download-plan.json` and `selected-papers.jsonl`; it makes no network
requests. The host then performs and validates the actual downloads using lawful
access tools. See [download and Zotero](research-radar/references/download-and-zotero.md).

## Quality, fit and overclaim control

The default priority score is **S = Q^0.6 × M^0.4**. Both Q and M use a 0–100 scale.
Recommendation gates require Q ≥ 70, M ≥ 70, and rigor/evidence ≥ 3 out of 5,
alongside the claim and evidence checks.

| Score | Default dimensions and weights |
|---|---|
| Content quality Q | Motivation 15%, originality 15%, rigor 25%, evidence 25%, reproducibility 10%, figure quality 10% |
| Prompt fit M | Research problem 45%, approach 25%, context 20%, reading intent 10% |

Author reputation, journal prestige, IF and visual polish do not directly add Q
points. Preprints are assessed on their content without a penalty for lacking IF.
Abstracts support triage; a final quality review requires actual full-text and
relevant figure/table inspection. Missing evidence remains unknown rather than zero.

Review schema **v5 / content-v4** requires a central-claim audit with source anchors,
supporting and limiting evidence, scope and bounded conclusions. Review statements
distinguish author reports from reviewer judgments. Unresolved central claims block
final Q/S; qualified claims cap scores and recommendations. Confirmed core failures
cannot be hidden by a high composite score. Suspected flaws require focused checks
before they can be reported as confirmed. Older reviews need a new template and audit.

The checks validate structure, evidence declarations and scoring gates. They do not
prove scientific correctness, semantic entailment, successful reproduction or the
absence of overclaiming. The initial weights remain configurable and have **not**
been validated as a field-wide accuracy or recall benchmark.

Read the [scoring specification](research-radar/references/scoring.md),
[quality review protocol](research-radar/references/quality-evaluation.md) and
[matching protocol](research-radar/references/matching.md) for the full contracts.

## Access and current limits

- Full-text routes include known OA links, optional Unpaywall/Europe PMC lookup,
  user-provided files and authorized institutional sessions. Availability is recorded
  separately from quality. See [full-text access](research-radar/references/fulltext-access.md).
- EasyScholar enriches journal information; it does not grant paid database access.
  WoS indexes and JCR quartiles are distinct fields and cannot be inferred from IF.
- Institutional credential helpers and adapter contracts are provided. Actual page
  interaction and session verification require a host browser adapter or human login.
  Real school logins and subscription access have not been validated by this project.
- A script-only host can retrieve metadata and prepare review queues. Full-text
  judgment and visual assessment depend on the host's actual reading tools.
- Deep search records source limits and stop reasons; it cannot guarantee exhaustive
  coverage or independently verified scientific judgments.

## Development and packaging

```text
research-radar/       Skill entry point, Python helpers, configuration template, references and tests
scripts/             Deterministic packaging and independent release validation
.github/workflows/   Offline tests and package checks
README.md            English introduction
README.zh-CN.md       Chinese introduction
LICENSE              MIT license
```

From the repository root:

```bash
python3 -m unittest discover -s research-radar/tests
python3 scripts/check_release.py
```

The release check builds `dist/research-radar.zip` and `dist/research-radar.skill`,
extracts and exercises the packaged CLI, and checks the allowlist, hashes,
reproducibility and documentation links. Archives contain the skill and its MIT
license; tests and developer tooling stay in the source repository. `dist/` is
rebuildable and excluded from Git, along with private user data, credentials and runs.

Tests use offline fixtures and do not need real API keys or school accounts. The
GitHub Actions workflow runs tests and release checks across Python 3.9, 3.12 and 3.14.
These checks do not establish live service availability or installation in every harness.
Optional notifications and Zotero import run only when explicitly requested.

Contributions should include reproducible examples without secrets and distinguish
offline checks from live validation. See [LICENSE](LICENSE) for the MIT terms.
