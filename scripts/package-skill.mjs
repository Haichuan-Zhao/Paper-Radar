// Deterministic, dependency-free ZIP packaging for maintainers; no research runtime.
import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { BUNDLE_FILES, PROJECT_ROOT, SKILL_PATH, validateSkill } from './check-skill.mjs';

export const ARCHIVE_NAME = 'paper-radar.zip';

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
  const { version } = await validateSkill(root);
  const entries = [];
  for (const file of [...BUNDLE_FILES].sort()) {
    entries.push({ name: `paper-radar/${file}`, data: await fs.readFile(path.join(root, SKILL_PATH, file)) });
  }
  const archive = makeZip(entries);
  const manifest = {
    skill: 'paper-radar', version, tag: `v${version}`,
    repository: 'https://github.com/Haichuan-Zhao/Paper-Radar',
    protocol: 'paper-radar-v2', rubric: 'paper-content-v2', runtime: 'host-agent',
    archive: { file: ARCHIVE_NAME, bytes: archive.length, sha256: sha256(archive) },
    files: entries.map(({ name, data }) => ({ path: name, bytes: data.length, sha256: sha256(data) })),
  };
  await fs.mkdir(outDir, { recursive: true });
  await fs.writeFile(path.join(outDir, ARCHIVE_NAME), archive);
  await fs.writeFile(path.join(outDir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
  return manifest;
}

const invokedPath = process.argv[1] ? await fs.realpath(process.argv[1]).catch(() => null) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  try {
    if (process.argv.length > 2) throw new Error('Usage: node scripts/package-skill.mjs');
    const manifest = await packageSkill();
    if (process.env.GITHUB_OUTPUT) await fs.appendFile(process.env.GITHUB_OUTPUT, `tag=${manifest.tag}\n`);
    console.log(JSON.stringify({ version: manifest.version, files: manifest.files.length, archive: manifest.archive }, null, 2));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
