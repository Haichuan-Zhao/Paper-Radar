import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { BUNDLE_FILES, PROJECT_ROOT, validateSkill } from '../scripts/check-skill.mjs';
import { packageSkill } from '../scripts/package-skill.mjs';

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'research-radar-package-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const files = ['README.md', 'README.zh-CN.md', 'LICENSE', 'tests/acceptance.md',
    ...BUNDLE_FILES.map(file => `research-radar/${file}`)];
  for (const file of files) {
    await fs.mkdir(path.dirname(path.join(root, file)), { recursive: true });
    await fs.copyFile(path.join(PROJECT_ROOT, file), path.join(root, file));
  }
  return root;
}

test('public bundle validates and root personal configuration is never packaged', async t => {
  const root = await fixture(t);
  const marker = 'PRIVATE_TEST_MARKER_DO_NOT_PUBLISH';
  await fs.writeFile(path.join(root, 'USER_CONFIG.md'), marker);
  await fs.mkdir(path.join(root, 'user-data'));
  await fs.writeFile(path.join(root, 'user-data', 'credentials.json'), marker);
  await fs.mkdir(path.join(root, 'research-radar-results'));
  await fs.writeFile(path.join(root, 'research-radar-results', 'report.md'), marker);
  const original = await fs.readFile(path.join(root, 'USER_CONFIG.md'));
  const manifest = await packageSkill({ root });
  const archive = await fs.readFile(path.join(root, 'dist', 'research-radar.zip'));
  assert.equal(manifest.files.length, BUNDLE_FILES.length);
  assert.equal(archive.includes(Buffer.from(marker)), false);
  assert.deepEqual(await fs.readFile(path.join(root, 'USER_CONFIG.md')), original);
  assert.equal(manifest.files.some(file => /\.(?:py|mjs|js)$/.test(file.path)), false);
});

test('archives are deterministic, equivalent and readable by independent unzip', async t => {
  const root = await fixture(t);
  const first = await packageSkill({ root });
  const archive = await fs.readFile(path.join(root, 'dist', 'research-radar.zip'));
  const second = await packageSkill({ root, outDir: path.join(root, 'second') });
  assert.equal(first.sha256, second.sha256);
  assert.deepEqual(archive, await fs.readFile(path.join(root, 'second', 'research-radar.skill')));
  const archivePath = path.join(root, 'dist', 'research-radar.zip');
  execFileSync('unzip', ['-t', archivePath], { stdio: 'pipe' });
  const listed = execFileSync('unzip', ['-Z1', archivePath], { encoding: 'utf8' }).trim().split('\n');
  assert.deepEqual(listed, [...BUNDLE_FILES].sort().map(file => `research-radar/${file}`));
  const extracted = path.join(root, 'extracted');
  execFileSync('unzip', ['-q', archivePath, '-d', extracted]);
  for (const file of BUNDLE_FILES) {
    assert.deepEqual(await fs.readFile(path.join(extracted, 'research-radar', file)),
      await fs.readFile(path.join(root, 'research-radar', file)));
  }
});

test('publishing a key in the example fails before writing output without echoing it', async t => {
  const root = await fixture(t);
  const file = path.join(root, 'research-radar', 'USER_CONFIG.example.md');
  const secret = 'SYNTHETIC_SECRET_NEVER_ECHO';
  await fs.writeFile(file, (await fs.readFile(file, 'utf8')).replace('| EasyScholar key | |', `| EasyScholar key | ${secret} |`));
  await assert.rejects(packageSkill({ root }), error => {
    assert.equal(error.message.includes(secret), false);
    return /personal field/.test(error.message);
  });
  await assert.rejects(fs.access(path.join(root, 'dist')));
});

test('school and research details cannot silently enter the distributed example', async t => {
  const root = await fixture(t);
  const file = path.join(root, 'research-radar', 'USER_CONFIG.example.md');
  const original = await fs.readFile(file, 'utf8');
  for (const label of ['学校邮箱或登录账号 / Library email or account', '研究主题 / Topic']) {
    await fs.writeFile(file, original.replace(`| ${label} | |`, `| ${label} | PRIVATE_TEST_VALUE |`));
    await assert.rejects(validateSkill(root), /personal field/);
  }
});

test('unexpected executable or private files in the bundle block packaging', async t => {
  const root = await fixture(t);
  await fs.writeFile(path.join(root, 'research-radar', 'USER_CONFIG.md'), 'private');
  await assert.rejects(packageSkill({ root }), /allowlist/);
  await fs.unlink(path.join(root, 'research-radar', 'USER_CONFIG.md'));
  await fs.writeFile(path.join(root, 'research-radar', 'driver.py'), '# obsolete runtime');
  await assert.rejects(packageSkill({ root }), /allowlist/);
});

test('symlink resources cannot pull outside files into the archive', async t => {
  const root = await fixture(t);
  const file = path.join(root, 'research-radar', 'assets', 'review-template.md');
  await fs.unlink(file);
  await fs.symlink(path.join(root, 'README.md'), file);
  await assert.rejects(packageSkill({ root }), /Symlinks/);
});

test('broken Chinese documentation links block the release', async t => {
  const root = await fixture(t);
  await fs.appendFile(path.join(root, 'README.zh-CN.md'), '\n[失效资源](research-radar/references/missing.md)\n');
  await assert.rejects(validateSkill(root), /Broken local documentation link in README.zh-CN.md/);
});
