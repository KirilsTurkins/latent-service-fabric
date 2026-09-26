import { bootstrapApplication, provideClientHydration } from '@angular/platform-browser';
import { renderApplication, provideServerRendering } from '@angular/platform-server';
import { provideZonelessChangeDetection } from '@angular/core';
import { App, NAME } from './app.js';
let calls = 0;
export async function render(name: string): Promise<string> {
  calls++;
  const html = await renderApplication(context => bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideServerRendering(), provideClientHydration(), {provide: NAME, useValue: name}]}, context), {
    document: '<html><head><base href="/"></head><body><lsf-demo></lsf-demo><script>globalThis.serverHeading=document.getElementById("greeting")</script><script type="module" src="/client.js"></script></body></html>',
    url: 'https://renderer.invalid/', allowedHosts: ['renderer.invalid'],
  });
  return JSON.stringify({html, calls});
}
