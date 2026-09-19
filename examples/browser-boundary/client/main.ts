import {bootstrapApplication, provideClientHydration, withNoHttpTransferCache} from '@angular/platform-browser';
import {provideZonelessChangeDetection} from '@angular/core';
import {App} from '../shared/app.js';

const original = document.getElementById('greeting');
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideClientHydration(withNoHttpTransferCache())]});
(globalThis as any).boundaryHydrated = original === document.getElementById('greeting');
