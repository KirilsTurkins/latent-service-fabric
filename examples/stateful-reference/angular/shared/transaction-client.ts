// lsf-example-begin: recovery-client
export interface DraftView {
  draftId: string;
  revision: string;
  units: number;
  namespaceView: string;
  keyVersion?: string;
}
export type Disposition = 'query' | 'in-progress' | 'recovery-required' | 'committed' | 'rejected' | 'aborted' | 'effect';
export interface EffectStatus {effectId: string; disposition: string; dispatchAttempt: number}
export interface Reply {
  status: number;
  disposition: Disposition;
  value?: DraftView | {error: string};
  effectIds: string[];
}
export interface Routes {command: string; query: string; result: string}
interface AbortFence {
  'command-id': string;
  'attempt-id': string;
  'transaction-id': string;
  'owner-fence': string;
}
interface Envelope {
  profile: string;
  disposition: Disposition;
  'command-id'?: string;
  'attempt-id'?: string;
  'state-view'?: string;
  'effect-ids'?: string[];
  'abort-fence'?: AbortFence;
  result?: {'media-type': string; 'body-base64': string};
  effect?: unknown;
}
interface Original {key: string; body: string; draftId: string; ifMatch?: string}
type RequestOptions = Omit<RequestInit, 'headers'> & {headers?: Record<string, string>};
type FetchReply = {status: number; envelope: Envelope; authorityEpoch: number};
type ResponseKind = 'command' | 'query' | 'recovery';

const VALUE_MEDIA = 'application/vnd.latent.wit-values.v1+json';
const PROFILE = 'transaction-http-v1';
const MAX_RESPONSE = 192 * 1024;
const MAX_U64 = (1n << 64n) - 1n;
const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', {fatal: true});

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function boundedId(value: unknown): string {
  if (typeof value !== 'string' || !/^[a-z0-9][a-z0-9-]{0,31}$/.test(value)) throw new Error('invalid-draft');
  return value;
}
function revision(value: unknown): string {
  if (typeof value !== 'string' || !/^(0|[1-9][0-9]{0,19})$/.test(value) || BigInt(value) > MAX_U64)
    throw new Error('invalid-business-revision');
  return value;
}
function binary(bytes: unknown, kind: 'NV' | 'SV'): string {
  if (!Array.isArray(bytes) || bytes.length !== 67 || bytes[0] !== kind.charCodeAt(0) || bytes[1] !== 86 || bytes[2] !== 2 || bytes.some(value => !Number.isInteger(value) || value < 0 || value > 255))
    throw new Error('invalid-state-observation');
  return btoa(String.fromCharCode(...bytes));
}
function unbase64(value: unknown): Uint8Array {
  if (typeof value !== 'string' || value.length > 4 * Math.ceil(MAX_RESPONSE / 3) || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))
    throw new Error('invalid-response-base64');
  const raw = atob(value);
  if (btoa(raw) !== value || raw.length > MAX_RESPONSE) throw new Error('invalid-response-base64');
  return Uint8Array.from(raw, byte => byte.charCodeAt(0));
}
function lossless(text: string): unknown {
  if (encoder.encode(text).length > MAX_RESPONSE) throw new Error('response-byte-limit');
  // Preserve the one typed revision before JSON can narrow a u64 to Number.
  // This also works in the maintained closed renderer's JavaScript engine,
  // without depending on a browser's newer JSON reviver source extension.
  let cursor = 0, copied = 0, revisions = 0;
  const parts: string[] = [];
  while (cursor < text.length) {
    if (text[cursor] !== '"') { cursor++; continue; }
    const start = cursor++;
    while (cursor < text.length) {
      if (text[cursor] === '\\') { cursor += 2; continue; }
      if (text[cursor++] === '"') break;
    }
    const key: unknown = JSON.parse(text.slice(start, cursor));
    let next = cursor;
    while (/\s/.test(text[next] ?? '') && next < text.length) next++;
    if (key !== 'revision' || text[next] !== ':') continue;
    next++;
    while (/\s/.test(text[next] ?? '') && next < text.length) next++;
    if (++revisions !== 1) throw new Error('duplicate-business-revision');
    // The native wire codec already emits u64 values as decimal strings.
    // Only normalize a numeric spelling before the JSON parser can round it.
    if (text[next] === '"') continue;
    let end = next;
    while (/[0-9.eE+-]/.test(text[end] ?? '') && end < text.length) end++;
    const exact = revision(text.slice(next, end));
    parts.push(text.slice(copied, next), JSON.stringify(exact));
    copied = end; cursor = end;
  }
  parts.push(text.slice(copied));
  return JSON.parse(parts.join(''));
}
export function projection(result: unknown): DraftView | {error: string} {
  if (!record(result) || result['media-type'] !== VALUE_MEDIA) throw new Error('unsupported-application-result');
  const values = lossless(decoder.decode(unbase64(result['body-base64'])));
  if (!Array.isArray(values) || values.length !== 1 || !record(values[0])) throw new Error('invalid-application-result');
  const outcome = values[0];
  if (Object.keys(outcome).length !== 1) throw new Error('invalid-application-result');
  if ('err' in outcome) {
    const allowed = ['invalid-draft', 'invalid-units', 'stale-edit', 'rejected', 'malformed-state', 'revision-overflow'];
    if (typeof outcome['err'] !== 'string' || !allowed.includes(outcome['err'])) throw new Error('unknown-business-rejection');
    return {error: outcome['err']};
  }
  const value = outcome['ok'];
  if (!record(value) || Object.keys(value).sort().join(',') !== 'draft-id,key-version,namespace-view,revision,units')
    throw new Error('invalid-draft-projection');
  const draftId = boundedId(value['draft-id']);
  const exactRevision = revision(value['revision']);
  const units = value['units'];
  if (typeof units !== 'number' || !Number.isInteger(units) || units < 0 || units > 10000) throw new Error('invalid-draft-units');
  const namespaceView = binary(value['namespace-view'], 'NV');
  const optional = value['key-version'];
  if (!record(optional) || Object.keys(optional).length !== 1) throw new Error('invalid-key-observation');
  let keyVersion: string | undefined;
  if ('none' in optional && optional['none'] === null) keyVersion = undefined;
  else if ('some' in optional) keyVersion = binary(optional['some'], 'SV');
  else throw new Error('invalid-key-observation');
  return {draftId, revision: exactRevision, units, namespaceView, keyVersion};
}
export function requireQueryView(draft: DraftView, hostView: unknown): void {
  if (hostView !== draft.namespaceView) throw new Error('inconsistent-query-view');
}
async function limitedBody(response: Response): Promise<string> {
  if (!response.body) return '';
  const reader = response.body.getReader();
  const bytes = new Uint8Array(MAX_RESPONSE); let count = 0; let emptyChunks = 0;
  try {
    for (;;) {
      const {done, value} = await reader.read();
      if (done) break;
      if (value.length === 0) {
        if (++emptyChunks > 1024) throw new Error('response-fragment-limit');
        continue;
      }
      if (value.length > MAX_RESPONSE - count) throw new Error('response-byte-limit');
      bytes.set(value, count); count += value.length;
    }
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  return decoder.decode(bytes.subarray(0, count));
}
function envelope(value: unknown): Envelope {
  if (!record(value) || value['profile'] !== PROFILE) throw new Error('unsupported-transaction-response');
  if (typeof value['disposition'] !== 'string' || !['query', 'in-progress', 'recovery-required', 'committed', 'rejected', 'aborted', 'effect'].includes(value['disposition']))
    throw new Error('unknown-transaction-disposition');
  for (const key of ['command-id']) {
    if (value[key] != null && (typeof value[key] !== 'string' || !/^[0-9a-f]{64}$/.test(value[key])))
      throw new Error('invalid-command-identity');
  }
  if (value['attempt-id'] != null && (typeof value['attempt-id'] !== 'string' || !/^(?:[1-9]|1[0-6])$/.test(value['attempt-id'])))
    throw new Error('invalid-attempt-identity');
  const effects = value['effect-ids'];
  if (effects != null && (!Array.isArray(effects) || effects.length > 2 || new Set(effects).size !== effects.length ||
      effects.some(id => typeof id !== 'string' || !id || id.length > 256))) throw new Error('invalid-effect-identities');
  if (value['state-view'] != null && (typeof value['state-view'] !== 'string' || unbase64(value['state-view']).length !== 67))
    throw new Error('invalid-minimum-view');
  return value as unknown as Envelope;
}

export class DraftClient {
  readonly routes: Routes;
  private readonly fetcher: typeof fetch;
  private readonly csrfHeaders: () => Record<string, string>;
  pending?: Readonly<Original>;
  view?: DraftView;
  status = 'idle';
  minimumView?: string;
  private last?: Envelope;
  private authorityEpoch = 0;

  constructor(routes: Routes, {fetcher = globalThis.fetch?.bind(globalThis), csrfHeaders = () => ({}), origin = globalThis.location?.origin, initialView}: {
    fetcher?: typeof fetch; csrfHeaders?: () => Record<string, string>; origin?: string; initialView?: DraftView;
  } = {}) {
    if (typeof origin !== 'string' || new URL(origin).origin !== origin || typeof fetcher !== 'function')
      throw new Error('invalid-application-origin');
    const route = (mode: keyof Routes): string => {
      const url = new URL(routes[mode], origin);
      if (url.origin !== origin || url.username || url.password || url.search || url.hash) throw new Error('invalid-application-route');
      return url.toString();
    };
    this.routes = {command: route('command'), query: route('query'), result: route('result')};
    this.fetcher = fetcher; this.csrfHeaders = csrfHeaders;
    this.view = initialView; this.minimumView = initialView?.namespaceView;
  }
  prepare(draftId: string, expectedRevision: string, units: number, reject = false, ifMatch?: string): string {
    if (this.pending) throw new Error('original-command-still-retained');
    boundedId(draftId); revision(expectedRevision);
    if (!Number.isInteger(units) || units < 0 || units > 10000 || typeof reject !== 'boolean') throw new Error('invalid-draft-edit');
    if (ifMatch !== undefined && ifMatch !== '"absent"' && !/^"[A-Za-z0-9+/]+={0,2}"$/.test(ifMatch)) throw new Error('invalid-original-precondition');
    const body = JSON.stringify([{'draft-id': draftId, 'expected-revision': expectedRevision, units, reject}]);
    const key = globalThis.crypto.randomUUID();
    this.pending = Object.freeze({key, body, draftId, ifMatch}); this.status = 'prepared';
    return key;
  }
  private async request(url: string, options: RequestOptions): Promise<FetchReply> {
    const authorityEpoch = this.authorityEpoch;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const headers = new Headers(this.csrfHeaders());
      for (const [name, value] of Object.entries(options.headers ?? {})) headers.set(name, value);
      const response = await this.fetcher(url, {...options, headers, credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal});
      if (response.status === 401 || response.status === 403) {
        this.authorityEpoch++;
        this.view = undefined; this.minimumView = undefined; this.last = undefined; this.status = 'permission-denied';
        controller.abort();
        throw new Error('permission-denied');
      }
      if (authorityEpoch !== this.authorityEpoch) { controller.abort(); throw new Error('permission-denied'); }
      const text = await limitedBody(response);
      if (authorityEpoch !== this.authorityEpoch) throw new Error('permission-denied');
      return {status: response.status, envelope: envelope(text ? lossless(text) : undefined), authorityEpoch};
    } finally { clearTimeout(timer); }
  }
  private apply(reply: FetchReply, requestedDraft: string, kind: ResponseKind, previousMinimum: string | undefined): Reply {
    if (reply.authorityEpoch !== this.authorityEpoch) throw new Error('permission-denied');
    const {status, envelope: response} = reply;
    if (response.disposition === 'effect' || (response.disposition === 'query') !== (kind === 'query'))
      throw new Error('unexpected-transaction-response');
    const allowedStatus: Record<Exclude<Disposition, 'effect'>, number[]> = {
      query: [200, 422], 'in-progress': [202], 'recovery-required': [503],
      committed: [200], rejected: [422], aborted: [409],
    };
    if (!allowedStatus[response.disposition].includes(status)) throw new Error('inconsistent-transaction-status');
    const value = response.result ? projection(response.result) : undefined;
    if (value && !('error' in value) && value.draftId !== requestedDraft) throw new Error('foreign-draft-response');
    if (kind === 'query') {
      if (previousMinimum !== this.minimumView) throw new Error('stale-query-response');
      if (value && !('error' in value)) {
        requireQueryView(value, response['state-view']);
        this.view = value; this.minimumView = value.namespaceView;
      }
    } else {
      if (!response['command-id']) throw new Error('missing-command-identity');
      if (this.last?.['command-id'] && response['command-id'] !== this.last['command-id']) throw new Error('foreign-command-response');
      if (this.last && ['committed', 'rejected'].includes(this.last.disposition) &&
          response.disposition !== this.last.disposition) throw new Error('terminal-command-regression');
      this.status = response.disposition;
      this.last = response;
      if (kind === 'command' && previousMinimum === this.minimumView) {
        if (value && !('error' in value)) this.view = value;
        if (response.disposition === 'committed' && response['state-view']) this.minimumView = response['state-view'];
      } else if (kind === 'recovery' && response.disposition === 'committed') {
        this.minimumView ??= response['state-view'];
      }
    }
    return {status, disposition: response.disposition, value, effectIds: response['effect-ids'] ?? []};
  }
  private applyCommand(reply: FetchReply, original: Readonly<Original>, kind: 'command' | 'recovery',
    previousMinimum: string | undefined): Reply {
    if (this.pending !== original) throw new Error('original-command-changed');
    return this.apply(reply, original.draftId, kind, previousMinimum);
  }
  async submit(): Promise<Reply> {
    if (!this.pending || this.status !== 'prepared') throw new Error('command-must-be-explicitly-prepared');
    const original = this.pending;
    const {key, body, ifMatch} = original;
    const previousMinimum = this.minimumView;
    this.status = 'pending';
    try {
      return this.applyCommand(await this.request(this.routes.command, {method: 'POST', body,
        headers: {'content-type': VALUE_MEDIA, 'idempotency-key': key, ...(ifMatch ? {'if-match': ifMatch} : {})}}),
        original, 'command', previousMinimum);
    } catch (error) {
      if (this.pending === original && this.status !== 'permission-denied' && !['committed', 'rejected'].includes(this.status)) this.status = 'uncertain';
      throw error;
    }
  }
  async recover(): Promise<Reply> {
    if (!this.pending) throw new Error('no-original-command');
    const original = this.pending;
    const reply = await this.request(this.routes.result, {method: 'GET', headers: {'idempotency-key': original.key}});
    return this.applyCommand(reply, original, 'recovery', undefined);
  }
  async query(draftId: string): Promise<Reply> {
    boundedId(draftId);
    const input = encoder.encode(JSON.stringify([draftId]));
    const query = btoa(String.fromCharCode(...input)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
    const previousMinimum = this.minimumView;
    const reply = await this.request(this.routes.query + '?input=' + query, {method: 'GET',
      headers: previousMinimum ? {'if-state-view': previousMinimum} : {}});
    // A receipt-only failure is not a fresh draft. Keep any original command
    // for recovery and make the unavailable read visible to the application.
    if (reply.envelope.disposition !== 'query' || !reply.envelope.result ||
        (reply.status !== 200 && reply.status !== 422)) throw new Error('query-unavailable');
    return this.apply(reply, draftId, 'query', previousMinimum);
  }
  async effectStatus(effectId: string): Promise<EffectStatus> {
    if (!this.pending || !/^[0-9a-f]{64}$/.test(effectId) || !this.last?.['effect-ids']?.includes(effectId))
      throw new Error('original-command-effect-required');
    const original = this.pending;
    const reply = await this.request(this.routes.result, {method: 'GET',
      headers: {'idempotency-key': original.key, 'effect-id': effectId}});
    if (this.pending !== original) throw new Error('original-command-changed');
    if (reply.authorityEpoch !== this.authorityEpoch) throw new Error('permission-denied');
    const effect = reply.envelope.effect;
    const allowed = ['pending', 'dispatching', 'provider-acknowledged', 'known-failure', 'uncertain',
      'expired', 'policy-blocked', 'administratively-terminated', 'retry-scheduled', 'dead-lettered'];
    if (reply.status !== 200 || reply.envelope.disposition !== 'effect' || !record(effect) ||
        Object.keys(effect).sort().join(',') !== 'dispatch-attempt,disposition,effect-id' ||
        effect['effect-id'] !== effectId || typeof effect['disposition'] !== 'string' ||
        !allowed.includes(effect['disposition']) || typeof effect['dispatch-attempt'] !== 'number' ||
        !Number.isInteger(effect['dispatch-attempt']) || effect['dispatch-attempt'] < 0 || effect['dispatch-attempt'] > 0xffffffff)
      throw new Error('invalid-effect-status');
    return {effectId, disposition: effect['disposition'], dispatchAttempt: effect['dispatch-attempt']};
  }
  private abortProof(): Record<string, unknown> {
    if (!this.pending || this.status !== 'aborted' || this.last?.disposition !== 'aborted' || !this.last['abort-fence']) throw new Error('affirmative-original-abort-proof-required');
    const proof = this.last['abort-fence'];
    if (!record(proof) || Object.keys(proof).sort().join(',') !== 'attempt-id,command-id,owner-fence,transaction-id' ||
        proof['command-id'] !== this.last['command-id'] || proof['attempt-id'] !== this.last['attempt-id'] ||
        typeof proof['transaction-id'] !== 'string' || !/^[0-9a-f]{64}$/.test(proof['transaction-id']) || unbase64(proof['owner-fence']).length !== 32)
      throw new Error('foreign-abort-proof');
    return proof;
  }
  canRetryAborted(): boolean {
    try { this.abortProof(); return true; } catch { return false; }
  }
  canFinishOriginal(): boolean {
    if (!this.last) return false;
    return ['committed', 'rejected'].includes(this.last.disposition) || this.canRetryAborted();
  }
  async retryAborted(): Promise<Reply> {
    const proof = this.abortProof();
    const encoded = btoa(String.fromCharCode(...encoder.encode(JSON.stringify(proof))));
    const retryKey = globalThis.crypto.randomUUID();
    const original = this.pending;
    if (!original) throw new Error('no-original-command');
    const previousMinimum = this.minimumView;
    this.status = 'pending';
    try {
      return this.applyCommand(await this.request(this.routes.command, {method: 'POST', body: original.body,
        headers: {'content-type': VALUE_MEDIA, 'idempotency-key': original.key, 'command-retry-key': retryKey,
          'command-abort-fence': encoded, ...(original.ifMatch ? {'if-match': original.ifMatch} : {})}}),
        original, 'command', previousMinimum);
    } catch (error) { if (this.pending === original && this.status !== 'permission-denied' && !['committed', 'rejected'].includes(this.status)) this.status = 'uncertain'; throw error; }
  }
  finishOriginal(): void {
    if (!this.canFinishOriginal()) throw new Error('original-command-not-terminal');
    this.pending = undefined; this.last = undefined; this.status = 'idle';
  }
}
// lsf-example-end: recovery-client
