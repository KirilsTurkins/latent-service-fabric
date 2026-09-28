// This public example reports availability only. It is not a user-session
// authenticator or a transparent proxy for confidential upstream responses.
type Request = {
  profile: 'buffered-v1'; method: string; path: string; query?: string;
  headers: {name: string; value: Uint8Array}[]; bodyBase64: string;
};
type Result = {tag: 'ok'; val: {status: number}} | {tag: 'err'; val: {tag: string}};
type Response = {
  profile: 'buffered-v1'; status: number; headers: {name: string; value: Uint8Array}[];
  mediaType: string; representationLength?: bigint; bodyBase64: string;
};

const messages = {
  available: '{"status":"available"}',
  missing: '{"error":"not-found"}',
  method: '{"error":"method-not-allowed"}',
  input: '{"error":"unexpected-input"}',
  forbidden: '{"error":"forbidden"}',
  upstream: '{"error":"upstream-unavailable"}',
  timeout: '{"error":"upstream-timeout"}',
  busy: '{"error":"temporarily-busy"}',
};

// Only the fixed ASCII messages above enter this encoder; no remote bytes are
// returned to the browser. This keeps the component independent of DOM/Node APIs.
function base64(value: string): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  let encoded = '';
  for (let index = 0; index < value.length; index += 3) {
    const a = value.charCodeAt(index), b = value.charCodeAt(index + 1) || 0;
    const c = value.charCodeAt(index + 2) || 0;
    encoded += alphabet[a >> 2] + alphabet[((a & 3) << 4) | (b >> 4)]
      + (index + 1 < value.length ? alphabet[((b & 15) << 2) | (c >> 6)] : '=')
      + (index + 2 < value.length ? alphabet[c & 63] : '=');
  }
  return encoded;
}

function reply(request: Request, status: number, message: keyof typeof messages): Response {
  const body = messages[message];
  const headers = [{name: 'cache-control', value: Uint8Array.from([110, 111, 45, 115, 116, 111, 114, 101])}];
  if (status === 405) headers.push({name: 'allow', value: Uint8Array.from([71, 69, 84, 44, 32, 72, 69, 65, 68])});
  return {profile: 'buffered-v1', status, headers, mediaType: 'application/json',
    representationLength: request.method === 'head' ? BigInt(body.length) : undefined,
    bodyBase64: request.method === 'head' ? '' : base64(body)};
}

export function handle(request: Request, upstream: () => Result): Response {
  // The prefix route owns every /api request; an unknown API path never reaches
  // the broader static SPA fallback. Unsupported methods perform no outbound call.
  if (request.path !== '/api/status') return reply(request, 404, 'missing');
  if (!['get', 'head'].includes(request.method)) return reply(request, 405, 'method');
  if (request.query !== undefined || request.bodyBase64 !== '') return reply(request, 400, 'input');
  if (request.headers.some(({name}) => /^(?:authorization|proxy-authorization|forwarded|x-forwarded-.*|x-lsf-.*|x-(?:customer|tenant|target|upstream)(?:-.*)?)$/i.test(name))) {
    return reply(request, 403, 'forbidden');
  }
  // Exactly one host operation. In particular, 'uncertain' does not enter a
  // retry loop and a redirect response never chooses another destination.
  const result = upstream();
  if (result.tag === 'ok') return result.val.status === 200
    ? reply(request, 200, 'available') : reply(request, 502, 'upstream');
  if (result.val.tag === 'deadline-exceeded' || result.val.tag === 'cancelled') return reply(request, 504, 'timeout');
  if (result.val.tag === 'budget-exhausted') return reply(request, 503, 'busy');
  return reply(request, 502, 'upstream');
}
