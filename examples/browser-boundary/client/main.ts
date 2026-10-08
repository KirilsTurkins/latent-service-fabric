import {bootstrapApplication, provideClientHydration, withNoHttpTransferCache} from '@angular/platform-browser';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, PUBLIC_APPLICATION} from '../shared/app.js';
import {consumeBootstrapToken, publicGreeting} from './application.js';

// This is a synthetic bootstrap datum, not an authentication mechanism. The
// build-time meta policy protects resources before this client code can run.
(globalThis as any).boundaryTokenRemoved = consumeBootstrapToken();

const original = document.getElementById('greeting');
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideClientHydration(withNoHttpTransferCache()),
  {provide: PUBLIC_APPLICATION, useValue: publicGreeting}]});
(globalThis as any).boundaryHydrated = original === document.getElementById('greeting');
