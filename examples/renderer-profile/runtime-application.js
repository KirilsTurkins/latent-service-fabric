// Conformance application for the fixed production adapter. Adversarial paths
// are fixture application behavior, never extra exports or node host APIs.
import {render as angularRender} from '../server.js';

let lastContext;
export function prepare() {
  return null;
}

export async function render(request, context) {
  if (request.path === '/spin') { for (;;) {} }
  if (request.path === '/promise-storm') {
    const repeat = () => Promise.resolve().then(repeat);
    await repeat();
  }
  if (request.path === '/exception') throw new Error('fixture-renderer-exception');
  if (request.path === '/invalid-result') return false;
  if (request.path === '/allocate') {
    const retained = [];
    for (let i = 0; i < 1024; i++) {
      const bytes = new Uint8Array(4 * 1024 * 1024);
      bytes.fill(7);
      retained.push(bytes);
    }
    throw new Error('fixture-allocation-unexpectedly-completed');
  }
  if (request.path === '/delayed-timer') setTimeout(() => {}, 1);
  if (request.path === '/interval') setInterval(() => {}, 0);
  if (request.path === '/timer-limit') {
    for (let i = 0; i < 257; i++) setTimeout(() => {}, 0);
  }
  if (request.path === '/microtask-limit') {
    for (let i = 0; i < 4097; i++) queueMicrotask(() => {});
  }
  if (request.path === '/maximum-document') {
    return {status: 200, headers: [], html: 'x'.repeat(128 * 1024)};
  }
  if (request.path === '/output-limit') {
    return {status: 200, headers: [], html: 'x'.repeat(128 * 1024 + 1)};
  }
  if (request.path === '/frame-limit') {
    return {status: 200, headers: [], html: 'x'.repeat(1024 * 1024)};
  }
  if (request.path === '/ambient-fetch') await fetch('https://renderer.invalid/');
  if (request.path === '/replace-timer') globalThis.setTimeout = () => 1;
  if (lastContext !== undefined) throw new Error('fixture-context-leaked');
  lastContext = context;
  const callbacks = [];
  await new Promise(resolve => setTimeout(() => { callbacks.push('timer'); resolve(); }, 0));
  await new Promise(resolve => queueMicrotask(() => { callbacks.push('microtask'); resolve(); }));
  const cookies = request.headers.filter(h => h.name.toLowerCase() === 'cookie');
  const state = {
    principal: context.principal, activation: context.activationId,
    root: context.rootActivationId, parent: context.parentActivationId,
    trace: context.trace, deadline: context.deadlineUnixMillis,
    cookies, callbacks, path: request.path,
  };
  const result = JSON.parse(await angularRender(JSON.stringify(state)));
  return {
    status: 200,
    headers: [{name: 'x-renderer-calls', value: Array.from(new TextEncoder().encode(String(result.calls)))}],
    html: result.html,
  };
}
