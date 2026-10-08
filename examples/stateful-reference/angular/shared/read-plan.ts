import {projection, type DraftView, type Routes} from './transaction-client.js';

export interface Request {method: string; path: string; query?: string | null}
export interface Context {principal: {subject: string; kind: string; tenant?: string | null}}
export type Backend = {outcome: 'response'; status: number; body: string} | {outcome: 'failure'; code: string} | null;
export interface ReadScope {draftId: string; url: string; routes: Routes}
const encoder = new TextEncoder();

// Two reviewed origins resolve to the same actual node's IPv4 listener through
// the installed HTTP provider's static address table. Each destination owns a
// separate credential that is authorized for only its one fresh-query route.
// The caller's provider policy independently permits only its own destination.
const reads: Readonly<Record<string, {origin: string; input: string}>> = Object.freeze({
  alice: {origin: 'http://alice-read.test:19092', input: 'WyJhbGljZSJd'},
  bob: {origin: 'http://bob-read.test:19092', input: 'WyJib2IiXQ'},
});

// lsf-example-begin: authorized-ssr-read
export function readScope(request: Request, context: Context): ReadScope | undefined {
  const principal = context.principal;
  if (principal.kind !== 'user' || principal.tenant !== 'examples' ||
      !Object.prototype.hasOwnProperty.call(reads, principal.subject) ||
      request.path !== '/drafts/' + principal.subject || !['GET', 'HEAD'].includes(request.method) || request.query)
    return undefined;
  const selected = reads[principal.subject];
  const base = '/drafts/' + principal.subject;
  return {draftId: principal.subject, url: selected.origin + base + '/query?input=' + selected.input,
          routes: {command: base + '/edit', query: base + '/query', result: base + '/result'}};
}

export function currentRead(scope: ReadScope, backend: Backend): DraftView {
  if (!backend || backend.outcome !== 'response' || backend.status !== 200 || encoder.encode(backend.body).length > 4096)
    throw new Error('current-read-unavailable');
  const value: unknown = JSON.parse(backend.body);
  if (typeof value !== 'object' || value === null || !('profile' in value) || !('disposition' in value) ||
      !('result' in value) || value.profile !== 'transaction-http-v1' || value.disposition !== 'query')
    throw new Error('current-read-contract');
  const draft = projection(value.result);
  if ('error' in draft || draft.draftId !== scope.draftId) throw new Error('current-read-scope');
  return draft;
}
// lsf-example-end: authorized-ssr-read
