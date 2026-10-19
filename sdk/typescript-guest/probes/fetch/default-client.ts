// Source-owned control: ordinary globals, with no transport argument or SDK call.
const initializedHeaders = new Headers([['x-client', 'ordinary-global']]);
const initializedRequest = new Request('https://fixture.invalid/not-dispatched', {
  headers: initializedHeaders,
});
if (initializedRequest.headers.get('x-client') !== 'ordinary-global') {
  throw new Error('default-fetch-client-initialization');
}

export async function request(url: string): Promise<string> {
  const response = await fetch(new Request(url, {headers: initializedHeaders}));
  const value = await response.json();
  return `${response.status}:${value.message}`;
}
