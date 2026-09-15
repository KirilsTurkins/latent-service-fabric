import { bootstrapApplication, provideClientHydration } from '@angular/platform-browser';
import { provideZonelessChangeDetection } from '@angular/core';
import { App } from './app.js';
await bootstrapApplication(App, {providers: [provideZonelessChangeDetection(), provideClientHydration()]});
(globalThis as any).lsfHydrated = true;
