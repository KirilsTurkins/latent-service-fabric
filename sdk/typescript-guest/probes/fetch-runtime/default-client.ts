const headers = new Headers([['x-client', 'ordinary-global']]);
export const initialized = typeof fetch === 'function' && typeof Request === 'function' &&
  new Response(null, {headers}).headers.get('x-client') === 'ordinary-global';

export async function request(url: string): Promise<string> {
  const response = await fetch(new Request(url, {headers}));
  if (response.bodyUsed) throw new Error('fetch-runtime-body-prematurely-used');
  const value = await response.json();
  if (!response.bodyUsed) throw new Error('fetch-runtime-body-not-consumed');
  let refused = false;
  try { await response.json(); } catch { refused = true; }
  if (!refused) throw new Error('fetch-runtime-body-reused');
  return `${response.status}:${JSON.stringify(value)}:used`;
}
