const headers = new Headers([['x-client', 'ordinary-global']]);
export const initialized = typeof fetch === 'function' && typeof Request === 'function' &&
  new Response(null, {headers}).headers.get('x-client') === 'ordinary-global';

function diagnostic(stage: string, error: unknown): string {
  const kind = error instanceof TypeError ? 'TypeError' : error instanceof RangeError ? 'RangeError' :
    error instanceof Error ? 'Error' : 'other';
  return `diagnostic:${stage}:${kind}`;
}

function construct(url: string): Request { return new Request(url, {headers}); }

export function requestReady(url: string): string {
  try {
    const input = construct(url);
    if (input.signal.aborted || input.bodyUsed || input.headers.get('x-client') !== 'ordinary-global') {
      throw new Error('fetch-runtime-request-state');
    }
    return 'request-ready';
  } catch (error) { return diagnostic('request', error); }
}

export async function request(url: string): Promise<string> {
  let stage = 'request';
  try {
    const input = construct(url);
    stage = 'fetch';
    const response = await fetch(input);
    stage = 'body-before';
    if (response.bodyUsed) throw new Error('fetch-runtime-body-prematurely-used');
    stage = 'body-json';
    const value = await response.json();
    stage = 'body-after';
    if (!response.bodyUsed) throw new Error('fetch-runtime-body-not-consumed');
    stage = 'body-repeat';
    let refused = false;
    try { await response.json(); } catch { refused = true; }
    if (!refused) throw new Error('fetch-runtime-body-reused');
    stage = 'serialize';
    return `${response.status}:${JSON.stringify(value)}:used`;
  } catch (error) { return diagnostic(stage, error); }
}
