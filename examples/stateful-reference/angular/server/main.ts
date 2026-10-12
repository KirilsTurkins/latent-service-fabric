import {bootstrapApplication, provideClientHydration} from '@angular/platform-browser';
import {renderApplication, provideServerRendering} from '@angular/platform-server';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, PAGE, type Page} from '../shared/app.js';
import {currentRead, readScope, type Request, type Context, type Backend} from '../shared/read-plan.js';

let renders = 0;
export async function prepare(request: Request, context: Context) {
  const scope = readScope(request, context);
  return scope ? {url: scope.url} : null;
}
export async function render(request: Request, context: Context, backend: Backend) {
  if (++renders !== 1) throw new Error('fresh-order-draft-renderer-required');
  const scope = readScope(request, context);
  let status = scope ? 503 : 403;
  const page: Page = {heading: scope ? 'Order draft' : 'Current access required', draftId: scope?.draftId,
    error: scope ? 'The current draft read is unavailable.' : 'The current read could not be authorized.',
    routes: scope?.routes ?? {command: '/drafts/denied/edit', query: '/drafts/denied/query', result: '/drafts/denied/result'}};
  if (scope) {
    try { page.draft = currentRead(scope, backend); page.error = undefined; status = 200; }
    catch { if (backend?.outcome === 'failure' && backend.code === 'permission-denied') status = 403; }
  }
  const html = await renderApplication(
    serverContext => bootstrapApplication(App, {providers: [provideZonelessChangeDetection(),
      provideServerRendering(), provideClientHydration(), {provide: PAGE, useValue: page}]}, serverContext),
    {document: '<html lang="en"><head><title>Order draft</title><base href="/"></head><body><lsf-order-draft></lsf-order-draft><script type="module" src="__LSF_CLIENT_ASSET__"></script></body></html>',
      url: 'https://stateful.invalid' + request.path, allowedHosts: ['stateful.invalid']});
  // The shared ingress owns cookies, CSP, cache policy and final publication
  // headers. Neither ordinary rendering nor command recovery issues cookies.
  return {status, headers: [], html};
}
