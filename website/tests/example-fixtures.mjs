import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {digest} from '../plugins/examples/io.mjs';

export const syntaxes = {
  rust: ['rs', 'let value = "<script>alert(1)</script>";'],
  typescript: ['ts', 'const value = "<script>alert(1)</script>";'],
  go: ['go', 'value := "<script>alert(1)</script>"'],
  c: ['c', 'const char *value = "<script>alert(1)</script>";'],
  java: ['java', 'String value = "<script>alert(1)</script>";'],
  csharp: ['cs', 'var value = "<script>alert(1)</script>";'],
};
export function fixture(t, languages = Object.keys(syntaxes)) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'lsf-examples-'));
  t.after(() => fs.rmSync(root, {recursive: true, force: true}));
  const write = (relative, value) => {
    const destination = path.join(root, relative);
    fs.mkdirSync(path.dirname(destination), {recursive: true});
    fs.writeFileSync(destination, typeof value === 'object' && !Buffer.isBuffer(value) ? JSON.stringify(value, null, 2) + '\n' : value);
  };
  const read = relative => fs.readFileSync(path.join(root, relative), 'utf8');
  const git = (...args) => execFileSync('git', args, {cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe']}).trim();
  git('init', '--quiet'); git('config', 'user.name', 'Example test fixture'); git('config', 'user.email', 'fixture@example.invalid');
  const commit = () => { git('add', '.'); git('commit', '--quiet', '-m', 'test fixture'); return git('rev-parse', 'HEAD'); };
  const scenario = {schema: 1, id: 'client/specimen', title: 'Synthetic source extraction fixture',
    audience: 'client-developer', target: 'client', variants: languages.map(language => ({
      language, kind: 'synthetic', source: `sdk/fixture/example.${syntaxes[language][0]}`,
      regions: ['invoke', 'private'], validation: {target: 'tools/fixture.py', instructions: 'docs/fixture.md', evidence: null},
    }))};
  const requests = [{example: scenario.id, region: 'invoke'}];
  const registration = 'examples/guides/specimen/example.json';
  write('examples/guides/registry.json', {schema: 1, scenarios: [registration]});
  write('tools/fixture.py', '# validation owner fixture; never executed\nraise Exception("DO NOT EXECUTE")\n');
  write('docs/fixture.md', '# Fixture owner instructions\n');
  for (const variant of scenario.variants) {
    write(variant.source, `// Synthetic syntax fixture only; not an SDK client\n// lsf-example-begin: invoke\n  ${syntaxes[variant.language][1]}\n  // α 😀 \\path \`\`\` {import('node:fs')}\n// lsf-example-end: invoke\n// lsf-example-begin: private\n// UNREFERENCED_SENTINEL_DO_NOT_PUBLISH\n// lsf-example-end: private\n`);
  }
  const save = () => write(registration, scenario);
  save();
  const initialRevision = commit();
  const identity = () => ({documentVersion: 'development', documentationRevision: git('rev-parse', 'HEAD'), sourceRevision: git('rev-parse', 'HEAD')});
  function evidence(overrides = {}) {
    const variant = scenario.variants[0]; variant.kind = 'maintained';
    const record = {schema: 1, scenario: scenario.id, language: variant.language, sourceRevision: initialRevision,
      sourceSha256: digest(read(variant.source)), validationSha256: digest(read(variant.validation.target)),
      level: 'real-node', execution: 'real-node', passed: true, toolchain: 'synthetic-toolchain-v1', run: 'synthetic-run-1', scope: 'Synthetic evidence matching fixture, not actual qualification', ...overrides};
    const location = 'examples/guides/evidence/specimen.json';
    write(location, record);
    variant.validation.evidence = {path: location, sha256: digest(read(location))}; save();
    return record;
  }
  return {root, write, read, git, commit, scenario, requests, registration, save, identity, initialRevision, evidence};
}
