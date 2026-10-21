// Repository maintenance only; no part of this script is installed with the skill.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const PROJECT_ROOT = fileURLToPath(new URL('../', import.meta.url));
export const SKILL_PATH = '.agents/skills/paper-radar';
export const BUNDLE_FILES = Object.freeze(['LICENSE', 'SKILL.md', 'agents/openai.yaml']);
export const ROLE_FILES = Object.freeze(['Guide.toml', 'Scout.toml', 'Reviewer.toml']);
export const DOCUMENT_FILES = Object.freeze([
  'README.md', 'AGENTS.md', 'tests/acceptance.md', 'tests/fixtures/casepack.md',
  `${SKILL_PATH}/SKILL.md`,
]);

// Parse the deliberately small scalar-only frontmatter used by this repository.
// General YAML syntax is checked separately with the skill creator's validator.
function scalar(value) {
  if (value.startsWith('"')) {
    try {
      const parsed = JSON.parse(value);
      if (typeof parsed === 'string') return parsed;
    } catch { /* Report only the field type, never its contents. */ }
    throw new Error('Invalid quoted frontmatter scalar.');
  }
  if (value.startsWith("'")) {
    if (!/^'(?:[^']|'')*'$/.test(value)) throw new Error('Invalid quoted frontmatter scalar.');
    return value.slice(1, -1).replaceAll("''", "'");
  }
  if (!value || /[:#\[\]{}&*!|>]/.test(value)) throw new Error('Unsupported frontmatter scalar.');
  return value;
}

export async function readMetadata(root = PROJECT_ROOT) {
  const skill = await fs.readFile(path.join(root, SKILL_PATH, 'SKILL.md'), 'utf8');
  const header = skill.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1];
  if (!header) throw new Error('Missing skill frontmatter.');
  const fields = new Map(), metadata = new Map();
  let inMetadata = false;
  for (const line of header.split(/\r?\n/)) {
    if (!line.trim() || line.startsWith('#')) continue;
    const entry = line.match(/^( {2})?([a-z][a-z_-]*):(?:[ \t]+(.*))?$/);
    if (!entry) throw new Error('Unsupported skill frontmatter structure.');
    const [, indent, key, value] = entry;
    if (indent && !inMetadata) throw new Error('Nested frontmatter must belong to metadata.');
    if (!indent && key === 'metadata' && value !== undefined) throw new Error('metadata must be a mapping.');
    if (!indent) inMetadata = key === 'metadata';
    const target = indent ? metadata : fields;
    if (target.has(key)) throw new Error('Duplicate skill frontmatter field.');
    target.set(key, !indent && inMetadata && value === undefined ? metadata : scalar(value ?? ''));
  }
  if ([...fields.keys()].some(key => !['name', 'description', 'license', 'metadata'].includes(key)) ||
      [...metadata.keys()].some(key => !['version', 'language'].includes(key))) {
    throw new Error('Unexpected skill frontmatter field.');
  }
  if (fields.get('name') !== 'paper-radar' || fields.get('license') !== 'MIT' ||
      metadata.get('language') !== 'zh-CN' || fields.get('metadata') !== metadata) {
    throw new Error('Skill identity, license or language is invalid.');
  }
  const description = fields.get('description');
  if (typeof description !== 'string' || !description.trim() || description.length > 1024 || /[<>]/.test(description)) {
    throw new Error('Skill description must be a nonempty discovery description.');
  }
  const version = metadata.get('version');
  if (typeof version !== 'string' || !/^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(version)) {
    throw new Error('metadata.version must be a stable major.minor.patch version.');
  }
  return { name: fields.get('name'), version, language: metadata.get('language'), description };
}

export async function readVersion(root = PROJECT_ROOT) {
  return (await readMetadata(root)).version;
}

async function walk(directory, prefix = '') {
  const files = [];
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    if (entry.name === '.DS_Store') continue;
    const relative = path.posix.join(prefix, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Symlinks are not allowed in the skill bundle.');
    if (entry.isDirectory()) files.push(...await walk(path.join(directory, entry.name), relative));
    else if (entry.isFile()) files.push(relative);
    else throw new Error('Unexpected file type in the skill bundle.');
  }
  return files.sort();
}

function proseOnly(document, file) {
  let marker = null, length = 0;
  const prose = [];
  for (const line of document.split(/\r?\n/)) {
    const fence = line.match(/^\s*(`{3,}|~{3,})(.*)$/);
    if (fence) {
      if (!marker) { marker = fence[1][0]; length = fence[1].length; }
      else if (fence[1][0] === marker && fence[1].length >= length && !fence[2].trim()) marker = null;
    } else if (!marker) prose.push(line);
  }
  if (marker) throw new Error(`Unclosed code fence in ${file}.`);
  return prose.join('\n');
}

async function checkLinks(root, file) {
  const prose = proseOnly(await fs.readFile(path.join(root, file), 'utf8'), file);
  const boundary = path.resolve(root, file.startsWith(`${SKILL_PATH}/`) ? SKILL_PATH : '.');
  for (const match of prose.matchAll(/\]\(([^)]+)\)/g)) {
    const target = match[1].trim().replace(/^<|>$/g, '');
    if (/^(?:https?:|mailto:|#)/i.test(target)) continue;
    let resolved;
    try { resolved = path.resolve(root, path.dirname(file), decodeURIComponent(target.split('#')[0])); }
    catch { throw new Error(`Invalid local documentation link in ${file}.`); }
    if (!resolved.startsWith(boundary + path.sep)) throw new Error(`Link leaves its distribution boundary in ${file}.`);
    try {
      const real = await fs.realpath(resolved);
      const realBoundary = await fs.realpath(boundary);
      if (real !== realBoundary && !real.startsWith(realBoundary + path.sep)) {
        throw new Error('Link target is outside its distribution boundary.');
      }
    } catch { throw new Error(`Broken or external local documentation link in ${file}.`); }
  }
}

async function checkInterface(bundleRoot) {
  const text = await fs.readFile(path.join(bundleRoot, 'agents/openai.yaml'), 'utf8');
  const values = new Map();
  for (const line of text.trimEnd().split(/\r?\n/)) {
    if (line === 'interface:') {
      if (values.has('interface')) throw new Error('Duplicate interface block.');
      values.set('interface', true);
      continue;
    }
    const entry = line.match(/^  (display_name|short_description|default_prompt): (".*")$/);
    if (!entry || !values.has('interface') || values.has(entry[1])) throw new Error('Invalid or duplicate interface field.');
    values.set(entry[1], scalar(entry[2]));
  }
  const short = values.get('short_description') ?? '';
  if (!values.get('display_name') || [...short].length < 25 || [...short].length > 64 ||
      !values.get('default_prompt')?.includes('$paper-radar')) {
    throw new Error('Incomplete skill interface metadata.');
  }
}

export async function validateSkill(root = PROJECT_ROOT) {
  const bundleRoot = path.join(root, SKILL_PATH);
  // Check ancestors too: a symlinked .agents/skills can hide the entire real bundle.
  for (const relative of ['.agents', '.agents/skills', SKILL_PATH]) {
    if ((await fs.lstat(path.join(root, relative))).isSymbolicLink()) throw new Error('Skill paths must not be symlinks.');
  }
  const actual = await walk(bundleRoot);
  if (JSON.stringify(actual) !== JSON.stringify([...BUNDLE_FILES].sort())) {
    throw new Error('Skill bundle differs from the public allowlist; review private/unexpected files.');
  }
  const { version } = await readMetadata(root);
  await checkInterface(bundleRoot);
  const rootLicense = await fs.readFile(path.join(root, 'LICENSE'), 'utf8');
  const skillLicense = await fs.readFile(path.join(bundleRoot, 'LICENSE'), 'utf8');
  if (!rootLicense.startsWith('MIT License') || rootLicense !== skillLicense) throw new Error('MIT licenses must match.');
  for (const file of DOCUMENT_FILES) await checkLinks(root, file);
  for (const file of ROLE_FILES) {
    const role = await fs.readFile(path.join(root, '.codex/agents', file), 'utf8');
    if (!/^name = "[a-z_]+"$/m.test(role) || !/^description = ".+"$/m.test(role) ||
        !/^developer_instructions = """\n[\s\S]+\n"""\s*$/m.test(role)) {
      throw new Error(`Invalid role structure in ${file}.`);
    }
  }
  return { version, files: actual.length, documents: DOCUMENT_FILES.length, runtime: 'host-agent' };
}

const invokedPath = process.argv[1] ? await fs.realpath(process.argv[1]).catch(() => null) : null;
if (invokedPath === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await validateSkill(), null, 2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
