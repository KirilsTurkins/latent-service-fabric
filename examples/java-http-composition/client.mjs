// Canonical WIT JSON uses decimal strings for full-width integer values.
export class JavaDomainHttpClient {
  constructor(origin) { this.origin = origin; }
  async call(path, method, arguments_) {
    const response = await fetch(this.origin + path, {
      method,
      headers: method === 'POST' ? { 'content-type': 'application/vnd.latent.wit-values.v1+json' } : {},
      body: method === 'POST' ? JSON.stringify(arguments_) : undefined,
    });
    const text = await response.text();
    return { status: response.status, value: response.ok || response.status === 422 ? JSON.parse(text) : text };
  }
  status() { return this.call('/api/status', 'GET', []); }
  echo(value) { return this.call('/api/echo', 'POST', [value]); }
  text(value) { return this.call('/api/text', 'POST', [value]); }
  items(value) { return this.call('/api/items', 'POST', [value]); }
}
