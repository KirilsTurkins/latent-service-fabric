export const APPLICATION_RESPONSE_BYTES = 256;
export const APPLICATION_TIMEOUT_MILLIS = 3000;

export async function publicGreeting(signal: AbortSignal): Promise<string> {
  if (signal.aborted) throw new Error('application-aborted');
  const origin = globalThis.location.origin;
  const endpoint = new URL('/api/greeting', origin);
  if (!['http:', 'https:'].includes(endpoint.protocol)) throw new Error('application-origin');
  const deadline = performance.now() + APPLICATION_TIMEOUT_MILLIS;
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal.addEventListener('abort', abort, {once: true});
  const timer = setTimeout(abort, Math.max(0, deadline - performance.now()));
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const response = await fetch(endpoint, {
      method: 'POST', body: '{"name":"Browser"}',
      headers: {'content-type': 'application/json'},
      mode: 'same-origin', credentials: 'omit', cache: 'no-store',
      redirect: 'error', referrerPolicy: 'same-origin', signal: controller.signal,
    });
    if (response.status !== 200 || response.redirected || !response.body ||
        !/^application\/json(?:;\s*charset=utf-8)?$/i.test(response.headers.get('content-type') ?? '') ||
        response.headers.has('content-encoding')) throw new Error('application-response');
    const length = response.headers.get('content-length');
    if (length !== null && (!/^(0|[1-9][0-9]{0,2})$/.test(length) ||
        Number(length) > APPLICATION_RESPONSE_BYTES)) throw new Error('application-response-limit');
    const bytes = new Uint8Array(APPLICATION_RESPONSE_BYTES);
    let size = 0;
    reader = response.body.getReader();
    while (true) {
      if (performance.now() >= deadline) throw new Error('application-deadline');
      const chunk = await reader.read();
      if (chunk.done) break;
      if (chunk.value.byteLength > bytes.length - size) throw new Error('application-response-limit');
      bytes.set(chunk.value, size);
      size += chunk.value.byteLength;
    }
    if (signal.aborted || controller.signal.aborted || performance.now() >= deadline) throw new Error('application-aborted');
    if (length !== null && Number(length) !== size) throw new Error('application-response-length');
    const result: unknown = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes.subarray(0, size)));
    if (result === null || typeof result !== 'object' || Array.isArray(result) ||
        Object.keys(result).join(',') !== 'greeting' || !('greeting' in result) ||
        typeof result.greeting !== 'string' || result.greeting.length > 128) throw new Error('application-shape');
    return result.greeting;
  } finally {
    clearTimeout(timer);
    signal.removeEventListener('abort', abort);
    controller.abort();
    if (reader) {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  }
}
