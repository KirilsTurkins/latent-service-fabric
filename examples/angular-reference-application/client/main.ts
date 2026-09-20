// lsf-example-begin: hydrate
import {bootstrapApplication, provideClientHydration} from '@angular/platform-browser';
import {provideZonelessChangeDetection} from '@angular/core';
import {App} from '../shared/app.js';

const application = await bootstrapApplication(App, {
  providers: [provideZonelessChangeDetection(), provideClientHydration()],
});
await application.whenStable();
document.documentElement.dataset['referenceHydrated'] = 'true';
// lsf-example-end: hydrate
