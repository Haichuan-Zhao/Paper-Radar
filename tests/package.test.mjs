import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { ADAPTER_FILES, BUNDLE_FILES, PROJECT_ROOT, validateSkill } from '../scripts/check-skill.mjs';
import { ARCHIVE_NAMES, packageSkill } from '../scripts/package-skill.mjs';

async function fixture(t) {
  const root = await fs.mkdtemp(path.join(os.tmpdir(), 'paper-radar-package-'));
  t.after(() => fs.rm(root, { recursive: true, force: true }));
  const files = ['README.md', 'README.en.md', 'LICENSE', 'tests/acceptance.md', 'tests/fixtures/casepack.md',
    ...ADAPTER_FILES.map(file => `adapters/${file}`),
    ...BUNDLE_FILES.map(file => `paper-radar/${file}`)];
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
  await fs.mkdir(path.join(root, 'paper-radar-results'));
  await fs.writeFile(path.join(root, 'paper-radar-results', 'report.md'), marker);
  const original = await fs.readFile(path.join(root, 'USER_CONFIG.md'));
  const manifest = await packageSkill({ root });
  assert.equal(manifest.files.length, BUNDLE_FILES.length);
  for (const file of ARCHIVE_NAMES) {
    assert.equal((await fs.readFile(path.join(root, 'dist', file))).includes(Buffer.from(marker)), false);
  }
  assert.deepEqual(await fs.readFile(path.join(root, 'USER_CONFIG.md')), original);
  assert.equal(manifest.files.some(file => /\.(?:py|mjs|js)$/.test(file.path)), false);
});

test('archives are deterministic, equivalent and readable by independent unzip', async t => {
  const root = await fixture(t);
  const first = await packageSkill({ root });
  const archive = await fs.readFile(path.join(root, 'dist', 'paper-radar.zip'));
  const second = await packageSkill({ root, outDir: path.join(root, 'second') });
  assert.equal(first.sha256, second.sha256);
  assert.deepEqual(first, second);
  assert.deepEqual(archive, await fs.readFile(path.join(root, 'second', 'paper-radar.zip')));
  const archivePath = path.join(root, 'dist', 'paper-radar.zip');
  execFileSync('unzip', ['-t', archivePath], { stdio: 'pipe' });
  const listed = execFileSync('unzip', ['-Z1', archivePath], { encoding: 'utf8' }).trim().split('\n');
  assert.deepEqual(listed, [...BUNDLE_FILES].sort().map(file => `paper-radar/${file}`));
  const extracted = path.join(root, 'extracted');
  execFileSync('unzip', ['-q', archivePath, '-d', extracted]);
  for (const file of BUNDLE_FILES) {
    assert.deepEqual(await fs.readFile(path.join(extracted, 'paper-radar', file)),
      await fs.readFile(path.join(root, 'paper-radar', file)));
  }
});

test('native workspaces contain actual hidden skill paths, role bindings and only a blank configuration', async t => {
  const root = await fixture(t);
  const manifest = await packageSkill({ root });
  const sample = await fs.readFile(path.join(root, 'paper-radar', 'USER_CONFIG.example.md'));
  for (const [host, config, skill, archive] of [
    ['codex', '.codex', '.agents/skills', ARCHIVE_NAMES[1]],
    ['claude-code', '.claude', '.claude/skills', ARCHIVE_NAMES[2]],
  ]) {
    const archivePath = path.join(root, 'dist', archive), extracted = path.join(root, host);
    execFileSync('unzip', ['-t', archivePath], { stdio: 'pipe' });
    execFileSync('unzip', ['-q', archivePath, '-d', extracted]);
    assert.deepEqual(execFileSync('unzip', ['-Z1', archivePath], { encoding: 'utf8' }).trim().split('\n'),
      manifest.archives.find(item => item.file === archive).entries);
    assert.deepEqual(await fs.readFile(path.join(extracted, 'Paper-Radar', 'USER_CONFIG.md')), sample);
    for (const file of BUNDLE_FILES) {
      assert.deepEqual(await fs.readFile(path.join(extracted, 'Paper-Radar', skill, 'paper-radar', file)),
        await fs.readFile(path.join(root, 'paper-radar', file)));
    }
    for (const file of ADAPTER_FILES.filter(file => file.startsWith(`${host}/agents/`))) {
      assert.deepEqual(await fs.readFile(path.join(extracted, 'Paper-Radar', config, 'agents', path.basename(file))),
        await fs.readFile(path.join(root, 'adapters', file)));
    }
  }
});

test('Finder metadata is excluded from all installation archives', async t => {
  const root = await fixture(t);
  const marker = 'FINDER_METADATA_NOT_PUBLIC';
  await fs.writeFile(path.join(root, 'paper-radar', '.DS_Store'), marker);
  await fs.writeFile(path.join(root, 'adapters', '.DS_Store'), marker);
  const manifest = await packageSkill({ root });
  for (const file of ARCHIVE_NAMES) {
    assert.equal((await fs.readFile(path.join(root, 'dist', file))).includes(Buffer.from(marker)), false);
  }
  assert.equal(manifest.archives.some(item => item.entries.some(name => name.endsWith('.DS_Store'))), false);
});

test('publishing a key in the example fails before writing output without echoing it', async t => {
  const root = await fixture(t);
  const file = path.join(root, 'paper-radar', 'USER_CONFIG.example.md');
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
  const file = path.join(root, 'paper-radar', 'USER_CONFIG.example.md');
  const original = await fs.readFile(file, 'utf8');
  for (const label of ['学校邮箱或登录账号 / Library email or account', '研究主题 / Topic']) {
    await fs.writeFile(file, original.replace(`| ${label} | |`, `| ${label} | PRIVATE_TEST_VALUE |`));
    await assert.rejects(validateSkill(root), /personal field/);
  }
});

test('unexpected executable or private files in the bundle block packaging', async t => {
  const root = await fixture(t);
  await fs.writeFile(path.join(root, 'paper-radar', 'USER_CONFIG.md'), 'private');
  await assert.rejects(packageSkill({ root }), /allowlist/);
  await fs.unlink(path.join(root, 'paper-radar', 'USER_CONFIG.md'));
  await fs.writeFile(path.join(root, 'paper-radar', 'driver.py'), '# obsolete runtime');
  await assert.rejects(packageSkill({ root }), /allowlist/);
});

test('symlink resources cannot pull outside files into the archive', async t => {
  const root = await fixture(t);
  const file = path.join(root, 'paper-radar', 'assets', 'review-template.md');
  await fs.unlink(file);
  await fs.symlink(path.join(root, 'README.md'), file);
  await assert.rejects(packageSkill({ root }), /Symlinks/);
});

test('broken documentation links block the release', async t => {
  const root = await fixture(t);
  await fs.appendFile(path.join(root, 'README.md'), '\n[失效资源](paper-radar/references/missing.md)\n');
  await assert.rejects(validateSkill(root), /Broken local documentation link in README.md/);
});
