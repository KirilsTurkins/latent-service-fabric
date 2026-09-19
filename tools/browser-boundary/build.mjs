import {createRequire} from 'node:module';
import {fileURLToPath, pathToFileURL} from 'node:url';
import path from 'node:path';
import {mkdir, readFile, writeFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import assert from 'node:assert/strict';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const [toolsArgument, outputArgument] = process.argv.slice(2);
assert.equal(process.version, 'v24.19.0');
const toolchain = path.resolve(toolsArgument);
const output = path.resolve(outputArgument);
const source = path.join(root, 'examples/browser-boundary');
const tool = createRequire(path.join(toolchain, 'package.json'));
assert.equal(tool('@angular/core/package.json').version, '22.1.6');
await mkdir(output, {recursive: true});
const environment = Object.fromEntries(['PATH', 'HOME', 'TMPDIR', 'TEMP', 'TMP', 'SystemRoot', 'WINDIR']
  .filter(name => process.env[name]).map(name => [name, process.env[name]]));
function run(arguments_) {
  execFileSync(process.execPath, arguments_, {cwd: root, env: environment, timeout: 120000,
    maxBuffer: 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
}
const recipe = path.join(root, 'tools/angular_build/bundle.mjs');
run([recipe, toolchain, source, output, 'configure']);
run([path.join(toolchain, 'node_modules/@angular/compiler-cli/bundles/src/bin/ngc.js'), '-p', path.join(output, 'tsconfig.json')]);
run([recipe, toolchain, source, output, 'bundle']);
await writeFile(path.join(output, 'package.json'), '{"type":"module"}\n');
const {render} = await import(pathToFileURL(path.join(output, 'server.js')));
const displayName = '</ScRiPt><script>globalThis.breakout=true</script><img src=x onerror=globalThis.breakout=true>&\u2028\u2029';
const client = await readFile(path.join(output, 'client.js'));
const identities = {clientSha256: createHash('sha256').update(client).digest('hex')};
for (const [route, name] of [['/', 'home.html'], ['/next', 'next.html']]) {
  const {html} = await render({path: route}, {principal: {subject: displayName}});
  assert.ok(Buffer.byteLength(html) <= 131072);
  for (const marker of ['lsf-server-secret-fixture-235', 'lsf-credential-fixture-235', 'lsf-private-connection-fixture-235']) {
    assert.ok(!html.includes(marker));
    assert.ok(!client.includes(Buffer.from(marker)));
  }
  assert.ok(html.includes('ngh='));
  const data = html.match(/<script id="browser-state" type="application\/json">([^<]*)<\/script>/);
  assert.ok(data);
  assert.equal(JSON.parse(data[1]).displayName, displayName);
  await writeFile(path.join(output, name), html);
  identities[name] = createHash('sha256').update(html).digest('hex');
}
await writeFile(path.join(output, 'build-receipt.json'), JSON.stringify({angular: '22.1.6', node: process.version,
  execution: 'controlled-node-ssr-not-component-execution', ...identities}));
console.log(JSON.stringify({angular: '22.1.6', built: true, transferredSecrets: false, sourceSeparated: true}));
