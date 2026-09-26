// One owned child at a time: candidate measurements, not a production sandbox.
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const mode = process.argv[2];
if (mode === 'render-child') {
  const {render} = await import('./dist/server.js');
  const samples = [];
  for (const name of ['Alice', 'Bob']) {
    const started = performance.now();
    const value = JSON.parse(await render(name));
    samples.push({name, calls: value.calls, htmlBytes: value.html.length,
      millis: performance.now() - started});
  }
  console.log(JSON.stringify({node: process.version, samples, rss: process.memoryUsage().rss}));
} else if (mode === 'spin-child') {
  for (;;) {}
} else if (mode === 'array-buffer-child') {
  const bytes = new Uint8Array(64 * 1024 * 1024);
  bytes.fill(7);
  console.log(JSON.stringify({arrayBufferBytes: bytes.byteLength, ...process.memoryUsage()}));
} else {
  let active = 0;
  let peak = 0;
  async function ownedChild(childMode, deadline = 10000) {
    assert.equal(active, 0);
    const started = performance.now();
    const child = spawn(process.execPath,
      ['--max-old-space-size=32', fileURLToPath(import.meta.url), childMode],
      {cwd: fileURLToPath(new URL('.', import.meta.url)),
        env: {SystemRoot: process.env.SystemRoot || ''},
        stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
    active++;
    peak = Math.max(peak, active);
    let expired = false;
    let overflow = false;
    let stdout = Buffer.alloc(0);
    let diagnosticBytes = 0;
    const timer = setTimeout(() => { expired = true; child.kill('SIGKILL'); }, deadline);
    child.stdout.on('data', data => {
      if (stdout.length + data.length > 8192) { overflow = true; child.kill('SIGKILL'); }
      else stdout = Buffer.concat([stdout, data]);
    });
    child.stderr.on('data', data => {
      diagnosticBytes += data.length;
      if (diagnosticBytes > 2048) { overflow = true; child.kill('SIGKILL'); }
    });
    try {
      const code = await new Promise((resolve, reject) => {
        child.once('error', reject);
        child.once('close', resolve); // Includes process exit and closed stdio.
      });
      assert.equal(overflow, false);
      if (!expired) assert.equal(code, 0);
      return {expired, reaped: true, elapsedMillis: performance.now() - started,
        value: stdout.length ? JSON.parse(stdout.toString('utf8')) : null};
    } finally { clearTimeout(timer); active--; }
  }
  const first = await ownedChild('render-child');
  assert.deepEqual(first.value.samples.map(s => s.calls), [1, 2]);
  const second = await ownedChild('render-child');
  assert.equal(second.value.samples[0].calls, 1);
  const interrupted = await ownedChild('spin-child', 250);
  assert.equal(interrupted.expired, true);
  const memory = await ownedChild('array-buffer-child');
  assert.equal(memory.value.arrayBufferBytes, 64 * 1024 * 1024);
  assert.ok(memory.value.arrayBuffers > 32 * 1024 * 1024);
  assert.equal(active, 0);
  const report = {candidate: 'node-fixed-host', first, second, interrupted, memory,
    oldSpaceLimitMiB: 32, peakChildren: peak, activeChildren: active,
    selected: false, reason: 'No hostile-code process boundary; old-space is not total memory.'};
  console.log(JSON.stringify(report));
}
