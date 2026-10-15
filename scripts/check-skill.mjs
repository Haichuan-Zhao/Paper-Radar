// Repository maintenance only; this file is not part of the installed skill.
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const PROJECT_ROOT = fileURLToPath(new URL('../', import.meta.url));
export const BUNDLE_FILES = Object.freeze([
  'LICENSE',
  'SKILL.md',
  'USER_CONFIG.example.md',
  'agents/openai.yaml',
  'assets/reading-list-template.md',
  'assets/review-template.md',
  'references/deployment.md',
  'references/discovery-and-evidence.md',
  'references/download-and-zotero.md',
  'references/fulltext-access.md',
  'references/journal-metrics.md',
  'references/matching.md',
  'references/outputs.md',
  'references/preflight.md',
  'references/quality-evaluation.md',
  'references/scoring.md',
  'references/sources.md',
]);

// Personal fields in the distributed example must remain empty. Never print values.
const PRIVATE_FIELDS = [
  'EasyScholar key',
  'EasyScholar 自定义数据集偏好 / Custom rating datasets',
  'OpenAlex key（可选）/ Optional key',
  '其他文献连接器 / Other scholarly connectors',
  '本地期刊评级表路径（可选）/ Local journal metric files',
  'OA 查询联系邮箱（可选）/ OA lookup contact email',
  '学校名称 / Institution',
  '图书馆资源入口 / Library URL',
  '校外访问或 SSO 入口 / Remote access or SSO URL',
  '允许的图书馆与 SSO 域名 / Allowed domains',
  '学校邮箱或登录账号 / Library email or account',
  '密码 secret 引用或环境变量名 / Password secret reference or env name',
  '密码（可选本地明文，不建议）/ Optional plaintext password',
  '已登录的浏览器或会话说明 / Existing browser session',
  '研究主题 / Topic',
  '完整原始需求 / Original request',
  '阅读目的 / Reading purpose',
  '起始日期 / Start date',
  '结束日期 / End date',
  '方法偏好（软偏好）/ Preferred methods',
  '应用条件 / Context',
  '必须满足的条件 / Hard constraints',
  '种子论文、作者或 DOI / Seeds',
  '限定期刊及 ISSN（可选）/ Journal restrictions',
  'IF/JCR/WoS/CAS/CCF 要求（可选）/ Metric requirements',
  '其他评价要求 / Other review preferences',
];

async function walk(directory, prefix = '') {
  const files = [];
  for (const entry of await fs.readdir(directory, { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name);
    if (entry.isSymbolicLink()) throw new Error('Symlinks are not allowed in the skill bundle.');
    if (entry.isDirectory()) files.push(...await walk(path.join(directory, entry.name), relative));
    else if (entry.isFile()) files.push(relative);
    else throw new Error('Unexpected file type in the skill bundle.');
  }
  return files.sort();
}

function checkPublicConfig(text) {
  const rows = new Map();
  for (const line of text.split('\n')) {
    if (!line.startsWith('|')) continue;
    const cells = line.split('|').slice(1, -1).map(cell => cell.trim());
    if (cells.length !== 2) throw new Error('Public configuration must use two-column tables.');
    if (rows.has(cells[0]) && !['配置项 / Setting', '---'].includes(cells[0])) {
      throw new Error('Duplicate field in public configuration.');
    }
    rows.set(cells[0], cells[1]);
  }
  for (const field of PRIVATE_FIELDS) {
    if (!rows.has(field) || rows.get(field) !== '') {
      throw new Error('The public configuration has a missing or populated personal field; values withheld.');
    }
  }
  const references = [
    ['EasyScholar secret 引用或环境变量名 / Secret reference or env name', 'EASYSCHOLAR_SECRET_KEY'],
    ['OpenAlex secret 引用或环境变量名 / Secret reference or env name', 'OPENALEX_API_KEY'],
  ];
  for (const [field, value] of references) {
    if (rows.get(field) !== value) throw new Error('Public secret references must retain the generic environment names.');
  }
}

async function checkLinks(root, file) {
  const text = (await fs.readFile(path.join(root, file), 'utf8')).replace(/^```[^\n]*\n[\s\S]*?^```\s*$/gm, '');
  for (const match of text.matchAll(/\]\(([^)]+)\)/g)) {
    const target = match[1].trim().replace(/^<|>$/g, '');
    if (/^(?:https?:|mailto:|#)/i.test(target)) continue;
    const resolved = path.resolve(root, path.dirname(file), decodeURI(target.split('#')[0]));
    if (!resolved.startsWith(path.resolve(root) + path.sep)) throw new Error(`Link leaves the project in ${file}.`);
    try { await fs.stat(resolved); }
    catch { throw new Error(`Broken local documentation link in ${file}.`); }
  }
}

export async function validateSkill(root = PROJECT_ROOT) {
  const bundleRoot = path.join(root, 'research-radar');
  if ((await fs.lstat(bundleRoot)).isSymbolicLink()) throw new Error('Skill directory must not be a symlink.');
  const actual = await walk(bundleRoot);
  if (JSON.stringify(actual) !== JSON.stringify([...BUNDLE_FILES].sort())) {
    throw new Error('Skill bundle differs from the public allowlist; remove private/unexpected files or review the allowlist.');
  }
  const skill = await fs.readFile(path.join(bundleRoot, 'SKILL.md'), 'utf8');
  const header = skill.match(/^---\r?\n([\s\S]*?)\r?\n---(?:\r?\n|$)/)?.[1];
  if (!header || !/^name: research-radar$/m.test(header) || !/^description:\s*\S/m.test(header)) {
    throw new Error('Missing skill name or description in frontmatter.');
  }
  checkPublicConfig(await fs.readFile(path.join(bundleRoot, 'USER_CONFIG.example.md'), 'utf8'));
  const rootLicense = await fs.readFile(path.join(root, 'LICENSE'), 'utf8');
  const skillLicense = await fs.readFile(path.join(bundleRoot, 'LICENSE'), 'utf8');
  if (!rootLicense.startsWith('MIT License') || rootLicense !== skillLicense) throw new Error('MIT licenses must match.');
  const documents = ['README.md', 'README.zh-CN.md', 'tests/acceptance.md',
    ...BUNDLE_FILES.filter(file => file.endsWith('.md')).map(file => `research-radar/${file}`)];
  for (const file of documents) await checkLinks(root, file);
  return { files: actual.length, documents: documents.length, runtime: 'host-agent' };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { console.log(JSON.stringify(await validateSkill(), null, 2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
