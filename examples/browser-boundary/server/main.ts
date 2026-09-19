import {bootstrapApplication, provideClientHydration, withNoHttpTransferCache} from '@angular/platform-browser';
import {renderApplication, provideServerRendering} from '@angular/platform-server';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, STATE} from '../shared/app.js';
import {projectHydration, serializeHydration} from '../shared/hydration.js';

export async function render(request: {path: string}, context: {principal: {subject: string}}) {
  if (!['/', '/next'].includes(request.path)) throw new Error('browser-fixture-route');
  const server = {displayName: context.principal.subject, page: request.path === '/' ? 'Home' : 'Next',
    secret: 'lsf-server-secret-fixture-235', credential: 'Bearer lsf-credential-fixture-235',
    serverOnly: {connection: 'lsf-private-connection-fixture-235'}};
  const projected = projectHydration(server, ['displayName', 'page']);
  const state = serializeHydration(projected);
  const html = await renderApplication(
    serverContext => bootstrapApplication(App, {providers: [provideZonelessChangeDetection(),
      provideServerRendering(), provideClientHydration(withNoHttpTransferCache()),
      {provide: STATE, useValue: projected}]}, serverContext),
    {document: '<!doctype html><html><head><meta charset="utf-8"></head><body><lsf-boundary></lsf-boundary>' +
      '<script id="browser-state" type="application/json">' + state + '</script>' +
      '<script type="module" src="__LSF_CLIENT_ASSET__"></script></body></html>',
    url: 'https://renderer.invalid' + request.path, allowedHosts: ['renderer.invalid']});
  return {status: 200, headers: [], html};
}
