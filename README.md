# Research Radar

English | [简体中文](README.zh-CN.md)

**An Agent Skill for deep literature discovery, evidence-grounded assessment and selected-paper retrieval.**

Install the skill in **Claude Code, Codex or another Agent Skills harness**, edit
one personal Markdown file, and ask the agent to find papers. The agent carries
out the workflow with the harness's search, browser, connector, reading and file
tools. **Using the skill requires no Python, Node.js, package installation or CLI.**

Research Radar assesses **content quality Q** and **fit to your original request M**
separately. Journal ratings provide context and optional filters; methods,
results, claims and figures determine the content review.

## Two stages, controlled by you

| Stage | The agent does | You receive |
|---|---|---|
| 1. Discover and assess | Check your configuration, search complementary sources, expand queries and trace citations, verify identities, read available evidence and review claims | Numbered results with Q/M/S or pending, journal information, fit reasons, limitations, evidence and access status |
| 2. Select and retrieve | Resolve your choices against that exact list and download only the selected papers | Verified files and a per-paper outcome |

The first stage may open lawful full text and temporary reading caches for review.
It does not automatically archive a batch of PDFs. The agent waits for a choice
such as “Download papers 1 and 3.” Supplementary files and library imports require
a separate request.

## Install once

Copy the complete [research-radar/](research-radar/) directory into your harness's
skill location:

| Harness | Personal installation | Project installation | Invoke |
|---|---|---|---|
| Claude Code | ~/.claude/skills/research-radar/ | .claude/skills/research-radar/ | /research-radar |
| Codex | ~/.agents/skills/research-radar/ | .agents/skills/research-radar/ | $research-radar |

Locations follow the [Claude Code documentation](https://code.claude.com/docs/en/skills)
and [Codex documentation](https://learn.chatgpt.com/docs/build-skills), checked
2026-10-15. Use your installed product's requirements for older, managed or cloud
environments. Other hosts can load [SKILL.md](research-radar/SKILL.md) and its
relative resources. See [deployment](research-radar/references/deployment.md).

No fixed MCP server, additional model API key or other skill is required.
The skill orchestrates tools you already have; it does not add capabilities or
permissions to the harness.

## Edit one USER_CONFIG.md

Start with:

> Use Research Radar and help me configure it.

The agent copies [USER_CONFIG.example.md](research-radar/USER_CONFIG.example.md)
to **USER_CONFIG.md in your current research workspace**, without overwriting an
existing file, and shows you the path. Edit its ordinary Markdown tables directly,
or tell the agent the path to another copy. No JSON or query syntax is needed.

| Section | What you can edit |
|---|---|
| Preferences | Output language, reading target, preprints, search budget and result directories |
| Keys and services | Your own EasyScholar key or secret reference, optional OpenAlex key, local metric files and OA contact email |
| Institutional library | School name, actual library/SSO entry points, allowed domains, email/account, private credential reference and browser session |
| Research task | Original question, purpose, dates, soft preferences, hard constraints and seed papers |
| Assessment and downloads | Quality weight/floors, download destination, optional SI and library import preferences |

Your current chat request overrides saved task preferences. The agent derives
scholarly queries and concept groups itself; you do not have to design API requests.

You may enter an API key directly in the local document, or use an environment
variable/host secret reference. **Inline keys and passwords are plaintext and may
be visible to the host/model reading the file.** Prefer secret references or
human browser login for school passwords. Do not commit a filled configuration
to GitHub. This repository ignores USER_CONFIG.md and local research outputs;
the public example stays blank. There is no project account server or upload form.

Before **every search**, the agent checks enabled services and actual capabilities.
If required information is missing, it explains the impact and waits for your
choice to complete setup or accept the named limitations for that run.
A saved password is not proof of login, and login is not proof of access to a paper.

## Ask the agent directly

In Claude Code, use /research-radar; in Codex, use $research-radar, for example:

> Use Research Radar with my USER_CONFIG.md. Search deeply for papers addressing
> my research question within the date range I give. Verify paper and journal
> identities, review the actual full-text evidence where available, and show
> numbered results with quality, fit, limitations and access status.
> Wait for my selection before downloading.

After reviewing the results:

> Download papers 1, 3 and 5 from this list.

The agent performs both stages through the harness. There is no separate research
driver or command for you to run.

## Discovery and evidence

- Choose relevant scholarly sources such as Crossref, OpenAlex, arXiv,
  bioRxiv/medRxiv, field indexes and publisher pages according to available tools.
  Paginate real result sets, expand queries and trace backward/forward citations
  (two hops by default). A reading target is not a retrieval cap.
- Verify DOI/native ID, date basis, journal ISSN/ISSN-L, publication status and
  actual version. Similar journal names do not automatically share ratings.
- Use each user's own EasyScholar data or local metric tables. Preserve source,
  edition and year for IF/JCR/WoS/CAS/CCF/custom ratings. IF does not prove WoS inclusion.
- Read the actual paper and inspect relevant figures. Abstract-only candidates
  stay pending quality review. Access difficulty does not lower content quality.
- Keep search logs, evidence anchors, per-paper reviews and a frozen selection
  catalog using the bundled protocols and templates.

See [discovery](research-radar/references/discovery-and-evidence.md),
[journal metrics](research-radar/references/journal-metrics.md) and
[outputs](research-radar/references/outputs.md).

## Quality and fit, with bounded claims

Default **S = Q^0.6 × M^0.4**, with Q and M on a 0–100 scale.

| Axis | Default dimensions |
|---|---|
| Q | Motivation 15%, originality 15%, rigor 25%, evidence 25%, reproducibility 10%, figure/argument clarity 10% |
| M | Research problem 45%, approach 25%, context 20%, reading intent 10% |

Recommendation requires Q/M ≥ 70, rigor/evidence ≥ 3 out of 5, completed evidence
review and the requested constraints. Prestige, IF and visual polish add no Q
points; preprints are not penalized for lacking journal ratings.

The agent audits central claims, distinguishes author reports from reviewer
judgments and checks both praise and criticism against source evidence.
Unresolved central claims or major findings leave final Q/S pending.
Qualified claims cap scores and recommendation strength; confirmed core evidence
failures cannot be hidden by a high composite score.

These are **instructions and review criteria applied by the host agent**, not
a machine-enforced scoring engine or scientific certification. The rubric is
configurable and has not been validated as a field-wide accuracy/recall benchmark.
See [scoring](research-radar/references/scoring.md) and
[quality evaluation](research-radar/references/quality-evaluation.md).

## Access limits

OA, user files and authorized institutional sessions are possible routes.
EasyScholar does not grant paid full-text access. School login depends on actual
entry points, host browser/secret capabilities, human MFA and the institution's
entitlement. There is no universal school login adapter or automatic purchase.

A host without full-text/image tools can discover candidates but must keep
unread dimensions pending. A host without download/file tools must not claim
to have saved or verified files. Real cross-harness behavior, school logins and
subscription access have not all been tested. See
[full-text access](research-radar/references/fulltext-access.md).

## Repository and maintenance

The installed skill contains Markdown instructions, templates, optional UI
metadata and its MIT license. It contains no executable research pipeline.

Repository-only maintenance uses Node.js 20+ and standard libraries to check
documentation, protect the public configuration example and build deterministic
archives. These commands are **for maintainers**, are excluded from the skill
bundle, and are not required for research use:

```bash
node --test tests/package.test.mjs
node scripts/check-skill.mjs
node scripts/package-skill.mjs
```

The package builder emits ZIP/.skill archives under ignored dist/.
[Acceptance scenarios](tests/acceptance.md) describe behavior to verify in real
harnesses; structural/package checks do not establish scientific accuracy or
end-to-end compatibility. The former program-based workflow and its tests were
removed; historical test counts do not apply to this architecture.

Licensed under [MIT](LICENSE).
