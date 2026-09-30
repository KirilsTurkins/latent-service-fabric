import {bootstrapApplication, provideClientHydration, withNoHttpTransferCache} from '@angular/platform-browser';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, PUBLIC_APPLICATION} from '../shared/app.js';
import {publicGreeting} from './application.js';

// This is a synthetic bootstrap datum, not an authentication mechanism. The
// build-time meta policy protects resources before this client code can run.
const visible = new URL(globalThis.location.href);
if (visible.searchParams.has('synthetic-token')) {
  visible.searchParams.delete('synthetic-token');
  globalThis.history.replaceState(null, '', visible.pathname + visible.search + visible.hash);
  (globalThis as any).boundaryTokenRemoved = true;
}

const original = document.getElementById('greeting');
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideClientHydration(withNoHttpTransferCache()),
  {provide: PUBLIC_APPLICATION, useValue: publicGreeting}]});
(globalThis as any).boundaryHydrated = original === document.getElementById('greeting');
