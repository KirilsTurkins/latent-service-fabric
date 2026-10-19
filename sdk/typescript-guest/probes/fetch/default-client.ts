// Source-owned control: ordinary globals, with no transport argument or SDK call.
const initializedHeaders = new Headers([['x-client', 'ordinary-global']]);
const initializedResponse = new Response(null, {headers: initializedHeaders});
if (initializedResponse.status !== 200 || initializedResponse.body !== null ||
    initializedResponse.headers.get('x-client') !== 'ordinary-global' ||
    typeof Request !== 'function' || typeof fetch !== 'function') {
  throw new Error('default-fetch-client-initialization');
}

export async function request(url: string): Promise<string> {
  const response = await fetch(new Request(url, {headers: initializedHeaders}));
  const value = await response.json();
  return `${response.status}:${value.message}`;
}
