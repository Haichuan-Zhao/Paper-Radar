# Paper-Radar

**Discover and assess papers around your research question.**

[简体中文](README.md) · **English** · [MIT](LICENSE)

One portable skill executed by Codex, Claude Code, and other Agent Skills hosts:
**search → verify → read and assess → follow up → numbered results → selected downloads**.
RADAR.md preserves progress and recovery. Research use needs no Python, Node, or extra model API.

## Install and configure

Download the [latest stable skill](https://github.com/Haichuan-Zhao/Paper-Radar/releases/latest/download/paper-radar.zip)
or browse [versions and release notes](https://github.com/Haichuan-Zhao/Paper-Radar/releases).
Extract it and place the complete paper-radar/ folder in one host location:

| Host | Personal | Project |
|---|---|---|
| Codex | ~/.agents/skills/paper-radar/ | .agents/skills/paper-radar/ |
| Claude Code | ~/.claude/skills/paper-radar/ | .claude/skills/paper-radar/ |

Ask your agent to follow the [install/update guide](paper-radar/references/install-update.md),
or copy it manually. Other Agent Skills hosts use the same folder. Local and cloud
behavior follows current [Codex](https://learn.chatgpt.com/docs/build-skills) and
[Claude Code](https://code.claude.com/docs/en/skills) documentation.

Keep one USER_CONFIG.md in your research workspace. The agent creates it from the
[public example](paper-radar/USER_CONFIG.example.md). The main settings are:

- Question, dates, constraints, reading intent, and budget; the current chat can supply them.
- Your own EasyScholar key/secret reference or lawful local metric table.
- If enabled, the institution, real library/SSO entry points, account, and browser session.

Keep configuration, papers, and results **outside the installed skill**. Updates replace only the skill.
Inline credentials are plaintext and may be visible to the host/model; prefer secret references
or human browser login. Before every search, relevant gaps require a choice to complete setup
or accept the named limitations for that run.

## Use

Invoke $paper-radar in Codex or /paper-radar in Claude Code:

> Use paper-radar with USER_CONFIG.md. Search deeply for my research question,
> verify paper and journal identity, and assess quality and fit from actual full text.
> Follow up on gaps. Save RADAR.md, deliver a fixed numbered list, then wait for my download selection.

Use native subagents when actually available and authorized; otherwise label sequential self-checks.
No extra host role files are required. Defaults are six substantive rounds and a reading target
of ten; the target does not cap discovery. Unfinished work is delivered as partial coverage.
Select papers from a catalog revision, or specify RADAR.md to pause/resume.

Q measures content quality, M fit to the original request; default S=Q^0.6×M^0.4.
Evidence, rigor, central claims, and hard constraints gate recommendations before ranking.
Prestige, IF, and attractive styling add no points. Missing full text or decisive evidence leaves
final Q/S pending. Major criticism needs verification too. Preprints have explicit status;
EasyScholar supplies ratings rather than subscription access, and login does not prove entitlement.

## Update an installed copy

Ask the agent:

> Update paper-radar to the latest stable release. Identify my actual installation and local edits,
> verify the release using the update guide, preserve USER_CONFIG.md, secrets, papers and research
> records, then report the installed version.

The skill's [VERSION](paper-radar/VERSION) identifies releases. Each release provides one ZIP and
a per-file hash manifest. Check local changes and back up before replacing the confirmed skill;
add missing configuration fields without replacing values. Keep a rollback copy outside skill scan paths.
**git pull updates a source clone, not a skill previously copied into a host.**
GitHub Source code ZIP downloads have no Git history; download a new stable package instead.
See [migration rules](paper-radar/references/install-update.md) for unversioned installs, old host
workspace packages, and local customizations. Ordinary searches do not auto-update the skill.

## Maintenance and validation

The repository maintains one [skill](paper-radar/), without committed archives or host-specific copies.
Bump VERSION, push main, then use Actions → Run workflow. CI validates and creates v<version>
with one portable ZIP and manifest; existing versions are not overwritten. See
[manual workflow runs](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow).
Maintainers use Node.js 20+ standard libraries; these scripts are excluded from installed skills:

```sh
node --test tests/package.test.mjs
node scripts/package-skill.mjs
```

[Acceptance scenarios](tests/acceptance.md) and [synthetic cases](tests/fixtures/casepack.md)
state what was tested. Distribution tests establish neither scientific accuracy nor universal
host compatibility; live keys and institutional access depend on the real environment.
The task loop, responsibility handoffs, and recovery approach draw on [Auto-Loop](https://github.com/Haichuan-Zhao/Auto-Loop).
