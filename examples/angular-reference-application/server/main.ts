import {bootstrapApplication, provideClientHydration} from '@angular/platform-browser';
import {renderApplication, provideServerRendering} from '@angular/platform-server';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, PAGE, Page} from '../shared/app.js';

interface Request {path: string}
interface Context {principal: {subject: string; kind: string}}
type Backend = {outcome: 'response'; status: number; body: string} | {outcome: 'failure'; code: string} | null;

const SERVER_ONLY = 'lsf-private-angular-reference-v1';
let calls = 0;
// Fixture account data is display text, separate from authenticated identifiers.
const displayNames: Readonly<Record<string, string>> = Object.freeze({alice: 'Alice<unsafe>', bob: 'Bob'});

// lsf-example-begin: dependency
export async function prepare(request: Request) {
  if (request.path === '/data') return {url: 'http://127.0.0.1:19090/message'};
  if (request.path === '/slow') return {url: 'http://127.0.0.1:19090/slow'};
  if (request.path === '/denied') return {url: 'http://127.0.0.1:19091/message'};
  return null;
}
// lsf-example-end: dependency

function publicMessage(backend: Backend): {message: string; outcome: string} {
  if (!backend) return {message: '', outcome: 'not-requested'};
  if (backend.outcome === 'failure') return {message: 'The scoped provider call was refused or interrupted.', outcome: backend.code};
  if (backend.status !== 200) return {message: 'The backend returned a declared error.', outcome: 'upstream-status'};
  try {
    const data: unknown = JSON.parse(backend.body);
    if (typeof data === 'object' && data !== null && 'message' in data &&
        typeof data.message === 'string' && data.message.length <= 256) {
      return {message: data.message, outcome: 'allowed'};
    }
  } catch {}
  return {message: 'The backend response was not in the public data contract.', outcome: 'upstream-contract'};
}

export async function render(request: Request, context: Context, backend: Backend) {
  if (++calls !== 1 || SERVER_ONLY.charCodeAt(calls) !== 115) throw new Error('fresh-reference-store-required');
  const account = request.path === '/account';
  const authenticated = context.principal.kind === 'user';
  const failed = request.path === '/failure';
  const result = publicMessage(backend);
  const status = failed ? 422 : account && !authenticated ? 403 : result.outcome === 'permission-denied' ? 403 : 200;
  const page: Page = {
    subject: account && authenticated ? (displayNames[context.principal.subject] ?? context.principal.subject) : 'visitor',
    heading: failed ? 'Reference request rejected' : account && !authenticated ? 'Sign in required' : 'Hello from Angular',
    message: failed ? 'This is a declared application failure, not a runtime trap.' : result.message,
    outcome: failed ? 'application-error' : account ? authenticated ? 'authenticated' : 'denied' : result.outcome,
    view: request.path === '/about' ? 'about' : 'main',
  };
  const html = await renderApplication(
    serverContext => bootstrapApplication(App, {providers: [provideZonelessChangeDetection(),
      provideServerRendering(), provideClientHydration(), {provide: PAGE, useValue: page}]}, serverContext),
    {document: '<html lang="en"><head><title>LSF Angular reference</title><base href="/"></head><body><lsf-reference></lsf-reference><script type="module" src="__LSF_CLIENT_ASSET__"></script></body></html>',
      url: 'https://reference.invalid' + request.path, allowedHosts: ['reference.invalid']});
  return {status, headers: [], html};
}
