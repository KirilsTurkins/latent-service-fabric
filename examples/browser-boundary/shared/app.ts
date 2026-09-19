import {Component, DOCUMENT, InjectionToken, inject, signal} from '@angular/core';
import {BrowserState, parseHydration} from './hydration.js';

export const STATE = new InjectionToken<BrowserState>('browser-state', {
  providedIn: 'root', factory: () => parseHydration(inject(DOCUMENT).getElementById('browser-state')!.textContent!),
});

@Component({selector: 'lsf-boundary', standalone: true,
  template: '<h1 id="greeting">Hello {{state["displayName"]}}</h1><p id="page">{{state["page"]}}</p><button id="count" (click)="increment()">Count {{count()}}</button><a id="next" href="next.html">Next</a>'})
export class App {
  state = inject(STATE);
  count = signal(0);
  increment() { this.count.update(value => value + 1); }
}
