import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { BUNDLE_FILES, PROJECT_ROOT, readVersion, validateSkill } from '../scripts/check-skill.mjs';
import { ARCHIVE_NAME, packageSkill } from '../scripts/package-skill.mjs';

const sha256 = data => createHash('sha256').update(data).digest('hex');

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paper-radar-package-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const files = ['README.md', 'README.en.md', 'LICENSE', 'tests/acceptance.md', 'tests/fixtures/casepack.md',
    ...BUNDLE_FILES.map(file => `paper-radar/${file}`)];
  for (const file of files) {
    await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await fs.copyFile(path.join(PROJECT_ROOT, file), path.join(root, file));
  }
  return root;
}

test('public bundle excludes personal configuration and research data without modifying them', async t => {
  const root = await fixture(t), marker = 'PRIVATE_TEST_MARKER_DO_NOT_PUBLISH';
  await fs.writeFile(path.join(root, 'USER_CONFIG.md'), marker);
  for (const directory of ['user-data', 'paper-radar-results']) {
    await fs.mkdir(path.join(root, directory));
    await fs.writeFile(path.join(root, directory, 'private.txt'), marker);
  }
  const manifest = await packageSkill({ root });
  assert.equal(manifest.files.length, BUNDLE_FILES.length);
  for (const file of [ARCHIVE_NAME, 'manifest.json']) {
    assert.equal((await fs.readFile(path.join(root, 'dist', file))).includes(Buffer.from(marker)), false);
  }
  assert.equal(await fs.readFile(path.join(root, 'USER_CONFIG.md'), 'utf8'), marker);
  assert.equal(manifest.files.some(file => /\.(?:py|mjs|js)$/.test(file.path)), false);
});

test('one deterministic ZIP matches its manifest and extracts to the exact source files', async t => {
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
    assert.deepEqual(data, await fs.readFile(path.join(root, file.path)));
    assert.equal(file.bytes, data.length);
    assert.equal(file.sha256, sha256(data));
  }
  assert.deepEqual((await fs.readdir(path.join(root, 'dist'))).sort(), ['manifest.json', ARCHIVE_NAME].sort());
});

test('VERSION drives release metadata without changing saved research protocols', async t => {
  const root = await fixture(t), first = await packageSkill({ root });
  assert.equal(first.version, await readVersion(root));
  assert.equal(first.tag, `v${first.version}`);
  assert.equal(first.repository, 'https://github.com/Haichuan-Zhao/Paper-Radar');
  const next = `${Number(first.version.split('.')[0]) + 1}.0.0`;
  await fs.writeFile(path.join(root, 'paper-radar', 'VERSION'), next + '\n');
  const second = await packageSkill({ root });
  assert.equal(second.version, next);
  assert.equal(second.tag, `v${next}`);
  assert.notEqual(first.archive.sha256, second.archive.sha256);
  assert.equal(first.protocol, second.protocol);
  assert.equal(first.rubric, second.rubric);
});

test('invalid release versions fail before any output is written', async t => {
  const root = await fixture(t);
  for (const version of ['', 'latest', '01.2.3', '1.2', '1.2.3/../../escape']) {
    await fs.writeFile(path.join(root, 'paper-radar', 'VERSION'), version);
    await assert.rejects(packageSkill({ root }), /VERSION/);
    await assert.rejects(fs.access(path.join(root, 'dist')));
  }
});

test('Finder metadata is excluded from the installation archive', async t => {
  const root = await fixture(t), marker = 'FINDER_METADATA_NOT_PUBLIC';
  await fs.writeFile(path.join(root, 'paper-radar', '.DS_Store'), marker);
  await fs.writeFile(path.join(root, 'paper-radar', 'references', '.DS_Store'), marker);
  const manifest = await packageSkill({ root });
  assert.equal((await fs.readFile(path.join(root, 'dist', ARCHIVE_NAME))).includes(Buffer.from(marker)), false);
  assert.equal(manifest.files.some(file => file.path.endsWith('.DS_Store')), false);
});

test('publishing a key in the example fails before output without echoing it', async t => {
  const root = await fixture(t), file = path.join(root, 'paper-radar', 'USER_CONFIG.example.md');
  const secret = 'SYNTHETIC_SECRET_NEVER_ECHO';
  await fs.writeFile(file, (await fs.readFile(file, 'utf8')).replace('| EasyScholar key | |', `| EasyScholar key | ${secret} |`));
  await assert.rejects(packageSkill({ root }), error => {
    assert.equal(error.message.includes(secret), false);
    return /personal field/.test(error.message);
  });
  await assert.rejects(fs.access(path.join(root, 'dist')));
});

test('school and research details cannot enter the distributed example', async t => {
  const root = await fixture(t), file = path.join(root, 'paper-radar', 'USER_CONFIG.example.md');
  const original = await fs.readFile(file, 'utf8');
  for (const label of ['学校邮箱或登录账号 / Library email or account', '研究主题 / Topic']) {
    await fs.writeFile(file, original.replace(`| ${label} | |`, `| ${label} | PRIVATE_TEST_VALUE |`));
    await assert.rejects(validateSkill(root), /personal field/);
  }
});

test('unexpected executable or private files in the bundle block packaging', async t => {
  const root = await fixture(t);
  for (const file of ['USER_CONFIG.md', 'driver.py']) {
    await fs.writeFile(path.join(root, 'paper-radar', file), 'unexpected input');
    await assert.rejects(packageSkill({ root }), /allowlist/);
    await fs.unlink(path.join(root, 'paper-radar', file));
  }
});

test('symlink resources cannot pull outside files into the archive', async t => {
  const root = await fixture(t), file = path.join(root, 'paper-radar', 'references', 'review.md');
  await fs.unlink(file);
  await fs.symlink(path.join(root, 'README.md'), file);
  await assert.rejects(packageSkill({ root }), /Symlinks/);
});

test('broken local documentation links block the release', async t => {
  const root = await fixture(t);
  await fs.appendFile(path.join(root, 'README.md'), '\n[失效资源](paper-radar/references/missing.md)\n');
  await assert.rejects(validateSkill(root), /Broken local documentation link in README.md/);
});
