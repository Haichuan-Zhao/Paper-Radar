import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import {
  BUNDLE_FILES, DOCUMENT_FILES, PROJECT_ROOT, ROLE_FILES, SKILL_PATH,
  readVersion, validateSkill,
} from '../scripts/check-skill.mjs';
import { ARCHIVE_NAME, packageSkill } from '../scripts/package-skill.mjs';

const sha256 = data => createHash('sha256').update(data).digest('hex');
const skillFile = root => path.join(root, SKILL_PATH, 'SKILL.md');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paper-radar-package-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const files = new Set([
    ...DOCUMENT_FILES, 'LICENSE', 'scripts/check-skill.mjs', 'scripts/package-skill.mjs',
    'tests/package.test.mjs', ...ROLE_FILES.map(file => `.codex/agents/${file}`),
    ...BUNDLE_FILES.map(file => `${SKILL_PATH}/${file}`),
  ]);
  for (const file of files) {
    await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await fs.copyFile(path.join(PROJECT_ROOT, file), path.join(root, file));
  }
  return root;
}

async function noOutput(root) {
  await assert.rejects(fs.access(path.join(root, 'dist')));
}

test('distribution contains only the standalone skill and leaves private project data intact', async t => {
  const root = await fixture(t), marker = 'PRIVATE_TEST_MARKER_DO_NOT_PUBLISH';
  for (const file of ['USER_CONFIG.md', 'RADAR.md', 'search-notes.md', 'user-data/private.txt', 'paper-radar-results/private.txt']) {
    await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await fs.writeFile(path.join(root, file), marker);
  }
  const manifest = await packageSkill({ root });
  assert.deepEqual(manifest.files.map(file => file.path), [
    'paper-radar/LICENSE', 'paper-radar/SKILL.md', 'paper-radar/agents/openai.yaml',
  ]);
  for (const file of [ARCHIVE_NAME, 'manifest.json']) {
    assert.equal((await fs.readFile(path.join(root, 'dist', file))).includes(Buffer.from(marker)), false);
  }
  for (const file of ['USER_CONFIG.md', 'RADAR.md', 'search-notes.md', 'user-data/private.txt', 'paper-radar-results/private.txt']) {
    assert.equal(await fs.readFile(path.join(root, file), 'utf8'), marker);
  }
});

test('deterministic ZIP extracts to the exact source skill despite its new repository path', async t => {
  const root = await fixture(t), first = await packageSkill({ root });
  const archivePath = path.join(root, 'dist', ARCHIVE_NAME), archive = await fs.readFile(archivePath);
  const second = await packageSkill({ root, outDir: path.join(root, 'second') });
  assert.deepEqual(first, second);
  assert.deepEqual(archive, await fs.readFile(path.join(root, 'second', ARCHIVE_NAME)));
  execFileSync('unzip', ['-t', archivePath], { stdio: 'pipe' });
  const listed = execFileSync('unzip', ['-Z1', archivePath], { encoding: 'utf8' }).trim().split('\n');
  assert.deepEqual(listed, [...BUNDLE_FILES].sort().map(file => `paper-radar/${file}`));
  assert.deepEqual(first.archive, { file: ARCHIVE_NAME, bytes: archive.length, sha256: sha256(archive) });
  assert.deepEqual(JSON.parse(await fs.readFile(path.join(root, 'dist', 'manifest.json'), 'utf8')), first);
  assert.deepEqual(first.files.map(file => file.path), listed);
  const extracted = path.join(root, 'extracted');
  execFileSync('unzip', ['-q', archivePath, '-d', extracted]);
  for (const file of first.files) {
    const data = await fs.readFile(path.join(extracted, file.path));
    const source = path.join(root, SKILL_PATH, file.path.slice('paper-radar/'.length));
    assert.deepEqual(data, await fs.readFile(source));
    assert.equal(file.bytes, data.length);
    assert.equal(file.sha256, sha256(data));
  }
  assert.deepEqual((await fs.readdir(path.join(root, 'dist'))).sort(), ['manifest.json', ARCHIVE_NAME].sort());
});

test('metadata.version alone drives releases without changing historical research protocols', async t => {
  const root = await fixture(t), first = await packageSkill({ root });
  assert.equal(first.version, await readVersion(root));
  assert.equal(first.tag, `v${first.version}`);
  assert.equal(first.repository, 'https://github.com/Haichuan-Zhao/Paper-Radar');
  const next = `${Number(first.version.split('.')[0]) + 1}.0.0`;
  const original = await fs.readFile(skillFile(root), 'utf8');
  await fs.writeFile(skillFile(root), original.replace(/^  version: ".*"$/m, `  version: "${next}"`));
  const second = await packageSkill({ root });
  assert.equal(second.version, next);
  assert.equal(second.tag, `v${next}`);
  assert.notEqual(first.archive.sha256, second.archive.sha256);
  assert.equal(second.protocol, 'paper-radar-v2');
  assert.equal(second.rubric, 'paper-content-v2');
  assert.equal(first.protocol, second.protocol);
  assert.equal(first.rubric, second.rubric);
});

test('invalid metadata versions fail before writing any archive', async t => {
  const root = await fixture(t), original = await fs.readFile(skillFile(root), 'utf8');
  for (const version of ['', 'latest', '01.2.3', '1.2', '1.2.3/../../escape', '1.2.3-rc.1']) {
    await fs.writeFile(skillFile(root), original.replace(/^  version: ".*"$/m, `  version: "${version}"`));
    await assert.rejects(packageSkill({ root }), /metadata.version/);
    await noOutput(root);
  }
});

test('legacy VERSION files and a version mentioned in prose cannot override metadata', async t => {
  const root = await fixture(t), version = await readVersion(root);
  await fs.mkdir(path.join(root, 'paper-radar'));
  await fs.writeFile(path.join(root, 'paper-radar/VERSION'), '99.0.0\n');
  await fs.appendFile(skillFile(root), '\nExample only:\n  version: "88.0.0"\n');
  const manifest = await packageSkill({ root });
  assert.equal(manifest.version, version);
  assert.equal(manifest.files.some(file => file.path.endsWith('/VERSION')), false);
});

test('duplicate or misplaced metadata is rejected rather than choosing a release arbitrarily', async t => {
  const root = await fixture(t), original = await fs.readFile(skillFile(root), 'utf8');
  for (const content of [
    original.replace('metadata:\n', 'metadata:\n  version: "9.9.9"\n'),
    original.replace('metadata:\n', ''),
    original.replace('metadata:\n', 'metadata: "not-a-map"\n'),
  ]) {
    await fs.writeFile(skillFile(root), content);
    await assert.rejects(packageSkill({ root }), /frontmatter|metadata|Nested/);
    await noOutput(root);
  }
});

test('Finder metadata is excluded from the installation archive', async t => {
  const root = await fixture(t), marker = 'FINDER_METADATA_NOT_PUBLIC';
  await fs.writeFile(path.join(root, SKILL_PATH, '.DS_Store'), marker);
  await fs.writeFile(path.join(root, SKILL_PATH, 'agents/.DS_Store'), marker);
  const manifest = await packageSkill({ root });
  assert.equal((await fs.readFile(path.join(root, 'dist', ARCHIVE_NAME))).includes(Buffer.from(marker)), false);
  assert.equal(manifest.files.some(file => file.path.endsWith('.DS_Store')), false);
});

test('private files, old resources and executables inside the skill block packaging', async t => {
  const root = await fixture(t), secret = 'SYNTHETIC_SECRET_NEVER_ECHO';
  for (const file of ['USER_CONFIG.md', 'VERSION', 'driver.py']) {
    await fs.writeFile(path.join(root, SKILL_PATH, file), secret);
    await assert.rejects(packageSkill({ root }), error => {
      assert.equal(error.message.includes(secret), false);
      return /allowlist/.test(error.message);
    });
    await noOutput(root);
    await fs.unlink(path.join(root, SKILL_PATH, file));
  }
});

test('symlink resources cannot pull outside files into the archive', async t => {
  const root = await fixture(t), file = path.join(root, SKILL_PATH, 'agents/openai.yaml');
  await fs.unlink(file);
  await fs.symlink(path.join(root, 'README.md'), file);
  await assert.rejects(packageSkill({ root }), /Symlinks/);
  await noOutput(root);
});

test('symlinked skill ancestors are rejected before reading bundle resources', async t => {
  const root = await fixture(t);
  await fs.rename(path.join(root, '.agents'), path.join(root, 'relocated-agents'));
  await fs.symlink(path.join(root, 'relocated-agents'), path.join(root, '.agents'));
  await assert.rejects(packageSkill({ root }), /symlinks/);
  await noOutput(root);
});

test('broken local documentation links block the release', async t => {
  const root = await fixture(t);
  await fs.appendFile(path.join(root, 'README.md'), '\n[Missing resource](missing.md)\n');
  await assert.rejects(validateSkill(root), /local documentation link in README.md/);
});

test('installed instructions cannot depend on a file outside the skill', async t => {
  const root = await fixture(t);
  await fs.appendFile(skillFile(root), '\n[Hidden dependency](../../../README.md)\n');
  await assert.rejects(packageSkill({ root }), /distribution boundary/);
  await noOutput(root);
});

test('code examples do not create false links but unfinished fences fail validation', async t => {
  const root = await fixture(t), readme = path.join(root, 'README.md');
  await fs.appendFile(readme, '\n```text\n[Example](missing.md)\n```\n');
  await validateSkill(root);
  await fs.appendFile(readme, '\n```text\nunfinished\n');
  await assert.rejects(validateSkill(root), /Unclosed code fence/);
});

test('a divergent skill license blocks distribution', async t => {
  const root = await fixture(t);
  await fs.appendFile(path.join(root, SKILL_PATH, 'LICENSE'), 'changed\n');
  await assert.rejects(packageSkill({ root }), /licenses must match/);
  await noOutput(root);
});

test('invalid interface metadata fails without exposing its content', async t => {
  const root = await fixture(t), file = path.join(root, SKILL_PATH, 'agents/openai.yaml');
  const original = await fs.readFile(file, 'utf8');
  for (const content of [
    original.replace('$paper-radar', 'paper-radar'),
    original.replace(/short_description: ".*"/, 'short_description: "short"'),
    original + '  default_prompt: "duplicate"\n',
    original.replace('display_name: "', 'display_name: "invalid "quote '),
  ]) {
    await fs.writeFile(file, content);
    await assert.rejects(packageSkill({ root }), /interface|scalar/);
    await noOutput(root);
  }
});

test('CLI entry points run through an aliased checkout and report the release tag', async t => {
  const root = await fixture(t), alias = `${root}-alias`;
  await fs.symlink(root, alias);
  t.after(() => fs.unlink(alias));
  const report = JSON.parse(execFileSync(process.execPath, [path.join(alias, 'scripts/check-skill.mjs')], { encoding: 'utf8' }));
  assert.equal(report.version, await readVersion(root));
  const outputFile = path.join(root, 'github-output.txt');
  const result = JSON.parse(execFileSync(process.execPath, [path.join(alias, 'scripts/package-skill.mjs')], {
    encoding: 'utf8', env: { ...process.env, GITHUB_OUTPUT: outputFile },
  }));
  assert.equal(result.version, report.version);
  assert.equal(result.files, 3);
  assert.equal(await fs.readFile(outputFile, 'utf8'), `tag=v${result.version}\n`);
  const archive = await fs.readFile(path.join(root, 'dist', ARCHIVE_NAME));
  assert.equal(result.archive.sha256, sha256(archive));
});
