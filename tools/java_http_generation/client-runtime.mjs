// Generated clients validate canonical WIT values. The node remains the authority.
const encoder = new TextEncoder();
const limits = { bytes: 1048576, stringBytes: 262144, nodes: 16384, items: 4096, depth: 32 };
function requireValue(condition) { if (!condition) throw new TypeError('invalid or over-limit typed WIT value'); }
function plain(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.getPrototypeOf(value) === Object.prototype; }
function keys(value, expected) { return plain(value) && Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key)); }
function text(value) {
  requireValue(typeof value === 'string' && value.isWellFormed() && encoder.encode(value).length <= limits.stringBytes);
}
function validate(type, value, state, depth = 0) {
  requireValue(depth <= limits.depth && ++state.nodes <= limits.nodes);
  const child = (type, value) => validate(type, value, state, depth + 1);
  if (type === null) { requireValue(value === null); return; }
  if (typeof type === 'string') {
    if (type === 'bool') { requireValue(typeof value === 'boolean'); return; }
    if (['string', 'char', 'u64', 's64', 'f32', 'f64'].includes(type)) {
      text(value);
      if (type === 'char') requireValue([...value].length === 1);
      if (type === 'u64' || type === 's64') {
        requireValue((type === 'u64' ? /^(0|[1-9][0-9]*)$/ : /^(0|-?[1-9][0-9]*)$/).test(value));
        const integer = BigInt(value);
        requireValue(type === 'u64' ? integer >= 0n && integer <= 18446744073709551615n : integer >= -9223372036854775808n && integer <= 9223372036854775807n);
      }
      if (type === 'f32' || type === 'f64') {
        requireValue(['nan', 'inf', '-inf'].includes(value) || /^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$/.test(value) && Number.isFinite(Number(value)) && (type === 'f64' || Number.isFinite(Math.fround(Number(value)))));
      }
      return;
    }
    requireValue(/^[us](8|16|32)$/.test(type) && Number.isInteger(value));
    const width = Number(type.slice(1)), signed = type[0] === 's';
    requireValue(value >= (signed ? -(2 ** (width - 1)) : 0) && value < 2 ** (signed ? width - 1 : width));
    return;
  }
  const [kind, body] = Object.entries(type)[0];
  if (kind === 'list' || kind === 'tuple' || kind === 'flags') {
    requireValue(Array.isArray(value) && value.length <= limits.items);
    if (kind === 'list') value.forEach(item => child(body, item));
    if (kind === 'tuple') { requireValue(value.length === body.length); value.forEach((item, index) => child(body[index], item)); }
    if (kind === 'flags') { requireValue(new Set(value).size === value.length); value.forEach(item => { text(item); requireValue(body.includes(item)); }); }
  } else if (kind === 'record') {
    requireValue(keys(value, body.map(field => field.name)));
    body.forEach(field => child(field.type, value[field.name]));
  } else if (kind === 'enum') { text(value); requireValue(body.includes(value)); }
  else if (kind === 'variant') {
    requireValue(plain(value) && typeof value.case === 'string');
    const branch = body.find(branch => branch.name === value.case);
    requireValue(branch !== undefined && keys(value, branch.type === null ? ['case'] : ['case', 'value']));
    if (branch.type !== null) child(branch.type, value.value);
  } else if (kind === 'option' || kind === 'result') {
    requireValue(plain(value) && Object.keys(value).length === 1);
    const tag = Object.keys(value)[0];
    requireValue(kind === 'option' ? ['none', 'some'].includes(tag) : ['ok', 'err'].includes(tag));
    child(kind === 'option' ? (tag === 'none' ? null : body) : body[tag], value[tag]);
  } else throw new TypeError('unsupported public WIT shape');
}
async function boundedBody(response) {
  if (!response.body) return '';
  const reader = response.body.getReader(), chunks = [];
  let size = 0;
  try {
    for (;;) {
      const {value, done} = await reader.read();
      if (done) break;
      size += value.byteLength;
      requireValue(size <= limits.bytes);
      chunks.push(value);
    }
  } finally { await reader.cancel(); }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder('utf-8', {fatal: true}).decode(bytes);
}
export class JavaHttpClient {
  constructor(origin) {
    const url = new URL(origin);
    requireValue(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password && !url.search && !url.hash && url.pathname === '/');
    this.origin = url.origin;
  }
  async call(name, arguments_, options = {}) {
    const route = schema.routes.find(route => route.clientName === name);
    requireValue(route !== undefined && Array.isArray(arguments_) && arguments_.length === route.signature.params.length);
    const state = {nodes: 1};
    arguments_.forEach((argument, index) => validate(route.signature.params[index].type, argument, state));
    const payload = JSON.stringify(arguments_);
    requireValue(encoder.encode(payload).length <= limits.bytes);
    const response = await fetch(this.origin + route.path, {
      method: route.method, credentials: 'omit', redirect: 'error', signal: options.signal,
      headers: route.method === 'POST' ? {'content-type': 'application/vnd.latent.wit-values.v1+json', origin: this.origin} : {},
      body: route.method === 'POST' ? payload : undefined,
    });
    const body = await boundedBody(response);
    if (response.status !== 200 && response.status !== 422) return {status: response.status, value: body};
    const value = JSON.parse(body), result = route.signature.result;
    requireValue(Array.isArray(value) && value.length === (result === null ? 0 : 1));
    if (result !== null) validate(result, value[0], {nodes: 1});
    return {status: response.status, value};
  }
// @METHODS@
}
