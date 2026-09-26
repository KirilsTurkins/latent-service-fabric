import {bootstrapApplication, provideClientHydration, withNoHttpTransferCache} from '@angular/platform-browser';
import {provideZonelessChangeDetection} from '@angular/core';
import {App, PUBLIC_APPLICATION} from '../shared/app.js';
import {publicGreeting} from './application.js';

const original = document.getElementById('greeting');
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideClientHydration(withNoHttpTransferCache()),
  {provide: PUBLIC_APPLICATION, useValue: publicGreeting}]});
(globalThis as any).boundaryHydrated = original === document.getElementById('greeting');
