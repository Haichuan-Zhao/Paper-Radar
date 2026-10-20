// Deterministic, dependency-free ZIP packaging for maintainers; no research runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { ADAPTER_FILES, BUNDLE_FILES, PROJECT_ROOT, validateSkill } from './check-skill.mjs';

export const ARCHIVE_NAMES = Object.freeze(['paper-radar.zip', 'Paper-Radar-Codex.zip', 'Paper-Radar-Claude-Code.zip']);

const crcTable = Array.from({ length: 256 }, (_, value) => {
  for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  return value >>> 0;
});
function crc32(data) {
  let value = 0xffffffff;
  for (const byte of data) value = crcTable[(value ^ byte) & 255] ^ (value >>> 8);
  return (value ^ 0xffffffff) >>> 0;
}
function makeZip(entries) {
  const local = [], central = [];
  let offset = 0;
  const date = ((2026 - 1980) << 9) | (1 << 5) | 1;
  for (const { name, data } of entries) {
    const filename = Buffer.from(name, 'utf8'), crc = crc32(data);
    const header = Buffer.alloc(30);
    header.writeUInt32LE(0x04034b50, 0);
    header.writeUInt16LE(20, 4);
    header.writeUInt16LE(0x800, 6); // UTF-8 filenames, stored entries.
    header.writeUInt16LE(date, 12);
    header.writeUInt32LE(crc, 14);
    header.writeUInt32LE(data.length, 18);
    header.writeUInt32LE(data.length, 22);
    header.writeUInt16LE(filename.length, 26);
    local.push(header, filename, data);

    const directory = Buffer.alloc(46);
    directory.writeUInt32LE(0x02014b50, 0);
    directory.writeUInt16LE(0x314, 4); // Unix, ZIP 2.0.
    directory.writeUInt16LE(20, 6);
    directory.writeUInt16LE(0x800, 8);
    directory.writeUInt16LE(date, 14);
    directory.writeUInt32LE(crc, 16);
    directory.writeUInt32LE(data.length, 20);
    directory.writeUInt32LE(data.length, 24);
    directory.writeUInt16LE(filename.length, 28);
    directory.writeUInt32LE((0o100644 << 16) >>> 0, 38);
    directory.writeUInt32LE(offset, 42);
    central.push(directory, filename);
    offset += header.length + filename.length + data.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}
const sha256 = data => createHash('sha256').update(data).digest('hex');

export async function packageSkill({ root = PROJECT_ROOT, outDir = path.join(root, 'dist') } = {}) {
  await validateSkill(root);
  const entries = [];
  for (const file of [...BUNDLE_FILES].sort()) {
    entries.push({ name: `paper-radar/${file}`, data: await fs.readFile(path.join(root, 'paper-radar', file)) });
  }
  const bundles = [{ file: ARCHIVE_NAMES[0], entries }];
  const read = file => fs.readFile(path.join(root, file));
  for (const [host, folder, skillDirectory, file] of [
    ['codex', '.codex', '.agents/skills', ARCHIVE_NAMES[1]],
    ['claude-code', '.claude', '.claude/skills', ARCHIVE_NAMES[2]],
  ]) {
    const workspace = [
      { name: 'Paper-Radar/README.md', data: await read('adapters/WORKSPACE.md') },
      { name: 'Paper-Radar/LICENSE', data: await read('LICENSE') },
      { name: 'Paper-Radar/USER_CONFIG.md', data: await read('paper-radar/USER_CONFIG.example.md') },
      ...entries.map(entry => ({ name: `Paper-Radar/${skillDirectory}/${entry.name}`, data: entry.data })),
    ];
    for (const source of ADAPTER_FILES.filter(source => source.startsWith(`${host}/agents/`))) {
      workspace.push({ name: `Paper-Radar/${folder}/agents/${path.basename(source)}`, data: await read(`adapters/${source}`) });
    }
    bundles.push({ file, entries: workspace.sort((a, b) => a.name < b.name ? -1 : a.name > b.name ? 1 : 0) });
  }
  for (const bundle of bundles) bundle.archive = makeZip(bundle.entries);
  const manifest = {
    skill: 'paper-radar', protocol: 'paper-radar-v2', runtime: 'host-agent', sha256: sha256(bundles[0].archive),
    files: entries.map(({ name, data }) => ({ path: name, bytes: data.length, sha256: sha256(data) })),
    archives: bundles.map(({ file, entries, archive }) => ({ file, bytes: archive.length, sha256: sha256(archive), entries: entries.map(entry => entry.name) })),
  };
  await fs.mkdir(outDir, { recursive: true });
  for (const { file, archive } of bundles) await fs.writeFile(path.join(outDir, file), archive);
  await fs.writeFile(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  return manifest;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let temporary;
  try {
    const mode = process.argv[2];
    if (process.argv.length > 3 || (mode && !['--check', '--publish'].includes(mode))) throw new Error('Use no argument, --publish or --check.');
    const outDir = mode === '--check' ? temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'paper-radar-release-'))
      : path.join(PROJECT_ROOT, mode === '--publish' ? 'packages' : 'dist');
    const manifest = await packageSkill({ outDir });
    if (mode === '--check') {
      for (const file of [...ARCHIVE_NAMES, 'manifest.json']) {
        if (!(await fs.readFile(path.join(outDir, file))).equals(await fs.readFile(path.join(PROJECT_ROOT, 'packages', file)))) {
          throw new Error('Published packages are stale. Rebuild with --publish and review the result.');
        }
      }
    }
    console.log(JSON.stringify({ files: manifest.files.length, runtime: manifest.runtime, archives: manifest.archives.map(({ file, sha256 }) => ({ file, sha256 })), checked: mode === '--check' }, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
  finally { if (temporary) await fs.rm(temporary, { recursive: true, force: true }); }
}
