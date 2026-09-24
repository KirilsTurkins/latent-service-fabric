/** Evaluate before application modules, including during engine snapshotting. */
const denied = (name: string) => () => { throw new Error(`typescript-guest:ambient-api-denied:${name}`); };
const globals = globalThis as unknown as Record<string, unknown>;
for (const name of [
  'fetch', 'Date', 'setTimeout', 'setInterval', 'clearTimeout', 'clearInterval',
  'WebSocket', 'Worker', 'SharedWorker', 'XMLHttpRequest', 'EventSource',
]) {
  Object.defineProperty(globals, name, { value: denied(name), writable: false, configurable: false });
}
for (const name of ['crypto', 'performance', 'process', 'require', 'window', 'document', 'navigator', 'console']) {
  Object.defineProperty(globals, name, {
    get: denied(name), configurable: false,
  });
}
Object.defineProperty(Math, 'random', { value: denied('Math.random'), writable: false, configurable: false });
