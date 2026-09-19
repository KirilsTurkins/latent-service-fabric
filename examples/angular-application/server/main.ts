import {bootstrapApplication, provideClientHydration} from '@angular/platform-browser';
import {renderApplication, provideServerRendering} from '@angular/platform-server';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, NAME} from '../shared/app.js';
// Marker proves that the browser graph never contains server-only inputs.
const SERVER_ONLY = 'lsf-private-server-fixture-234';
let calls = 0;
export async function render(request: {path: string}, context: {principal: {subject: string}}) {
  calls++;
  if (calls !== 1 || SERVER_ONLY.charCodeAt(calls) !== 115) throw new Error('fresh-server-state-required');
  const name = request.path === '/large-hydration' ? 'x'.repeat(40000) : context.principal.subject;
  const html = await renderApplication(
    serverContext => bootstrapApplication(App, {providers: [provideZonelessChangeDetection(),
      provideServerRendering(), provideClientHydration(), {provide: NAME, useValue: name}]}, serverContext),
    {document: '<html><head><base href="/"></head><body><lsf-demo></lsf-demo><script>globalThis.serverHeading=document.getElementById("greeting")</script><script type="module" src="__LSF_CLIENT_ASSET__"></script></body></html>',
      url: 'https://renderer.invalid/', allowedHosts: ['renderer.invalid']});
  return {status: 200, headers: [], html};
}
