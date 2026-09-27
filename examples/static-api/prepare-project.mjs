// Copy a freshly initialized TypeScript greeting project into an editable API
// project. This prepares source only; it starts no node and grants no authority.
import {cp, lstat, mkdir, readFile, writeFile} from 'node:fs/promises';
import {resolve, join, dirname} from 'node:path';
import {fileURLToPath} from 'node:url';

const [input, output, ...extra] = process.argv.slice(2);
if (!input || !output || extra.length) throw new Error('usage: node prepare-project.mjs GREETING_PROJECT NEW_API_PROJECT');
const source = resolve(input), destination = resolve(output);
if (destination === source || dirname(source) !== dirname(destination)) throw new Error('choose a new sibling project directory');
const example = dirname(fileURLToPath(import.meta.url));
const descriptor = JSON.parse(await readFile(join(source, 'latent.project.json'), 'utf8'));
const owner = JSON.parse(await readFile(join(source, 'app/capsule-project.json'), 'utf8'));
if (descriptor.language !== 'typescript' || descriptor.schemaVersion !== 'latent.dev.project.v1'
  || owner.world !== 'examples:greeting/service@1.0.0' || descriptor.inputRoots.join(',') !== 'app,tests') {
  throw new Error('initialize an unchanged TypeScript greeting template first');
}
await mkdir(destination, {mode: 0o700});
let files = 0, bytes = 0;
await cp(join(source, 'app'), join(destination, 'app'), {
  recursive: true, errorOnExist: true, force: false,
  filter: async path => {
    const info = await lstat(path);
    if (info.isSymbolicLink() || (!info.isDirectory() && !info.isFile())) throw new Error('project entries must be regular files or directories');
    if (info.isFile()) {files++; bytes += info.size;}
    if (files > 8192 || bytes > 64 * 1024 * 1024) throw new Error('project copy exceeds the example limit');
    return true;
  },
});
await mkdir(join(destination, 'tests'), {mode: 0o700});
for (const name of ['main.ts', 'status.ts']) await writeFile(join(destination, 'app/src', name), await readFile(join(example, 'capsule', name)));
await writeFile(join(destination, 'app/wit/world.wit'), await readFile(join(example, 'capsule/world.wit')));
for (const [target, vendor] of [['http', 'http-v2'], ['web', 'web'], ['context', 'context']]) {
  const directory = join(destination, 'app/wit/deps', target);
  await mkdir(directory, {recursive: true});
  await writeFile(join(directory, 'package.wit'), await readFile(join(destination, 'app/vendor/lsf/wit/platform', vendor, 'package.wit')));
}
owner.name = descriptor.name = 'status-api';
owner.service = descriptor.service = 'examples/status-api';
owner.world = 'examples:static-api/service@1.0.0';
owner.limits.outboundRequests = 1;
const cases = [];
for (const [id, path, method, status, error] of [
  ['unknown-api', '/api/missing', 'get', 404, 'not-found'],
  ['method-denied', '/api/status', 'post', 405, 'method-not-allowed'],
]) {
  const input = [{profile: 'buffered-v1', method, scheme: 'https', authority: 'site.example', path,
    query: {none: null}, headers: [], 'media-type': {none: null}, 'body-base64': ''}];
  const headers = [{name: 'cache-control', value: [...Buffer.from('no-store')]}];
  if (status === 405) headers.push({name: 'allow', value: [...Buffer.from('GET, HEAD')]});
  const expected = [{profile: 'buffered-v1', status, headers, 'media-type': {some: 'application/json'},
    'representation-length': {none: null}, 'body-base64': Buffer.from(JSON.stringify({error})).toString('base64')}];
  for (const [suffix, value] of [['input', input], ['expected', expected]]) {
    await writeFile(join(destination, 'tests', `${id}-${suffix}.json`), JSON.stringify(value));
  }
  cases.push({id, service: descriptor.service, contract: 'latent:web/application@0.1.0', function: 'handle',
    input: `tests/${id}-input.json`, mediaType: 'application/vnd.latent.wit-values.v1+json',
    expect: {category: 'success', payload: `tests/${id}-expected.json`}, requires: [], fixtures: [],
    timeoutMillis: 5000, nodeTimeoutMillis: 120000, required: true});
}
await writeFile(join(destination, 'tests/scenarios.json'), JSON.stringify({schemaVersion: 'latent.dev.scenarios.v1', scenarios: cases}, null, 2) + '\n');
await writeFile(join(destination, 'app/capsule-project.json'), JSON.stringify(owner, null, 2) + '\n');
await writeFile(join(destination, 'latent.project.json'), JSON.stringify(descriptor, null, 2) + '\n');
await writeFile(join(destination, '.gitignore'), '.latent/\noutput/\n*.log\n');
console.log('Created the API project. Review its fixed HTTPS upstream, then trust and build it with latent-dev.');
