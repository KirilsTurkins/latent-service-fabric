import {Component, DestroyRef, DOCUMENT, InjectionToken, inject, signal} from '@angular/core';
import {BrowserState, parseHydration} from './hydration.js';

export const STATE = new InjectionToken<BrowserState>('browser-state', {
  providedIn: 'root', factory: () => parseHydration(inject(DOCUMENT).getElementById('browser-state')!.textContent!),
});
export const PUBLIC_APPLICATION = new InjectionToken<(signal: AbortSignal) => Promise<string>>('public-application', {
  providedIn: 'root', factory: () => async () => { throw new Error('browser-only-application'); },
});

@Component({selector: 'lsf-boundary', standalone: true,
  template: '<h1 id="greeting">Hello {{state["displayName"]}}</h1><p id="page">{{state["page"]}}</p><button id="count" (click)="increment()">Count {{count()}}</button><button id="public-greeting" [disabled]="busy()" (click)="greet()">Call public application</button><p id="public-result">{{result()}}</p><a id="next" href="next.html">Next</a>'})
export class App {
  state = inject(STATE);
  count = signal(0);
  busy = signal(false);
  result = signal('Not requested');
  private application = inject(PUBLIC_APPLICATION);
  private pending: AbortController | null = null;
  constructor() { inject(DestroyRef).onDestroy(() => this.pending?.abort()); }
  increment() { this.count.update(value => value + 1); }
  async greet() {
    if (this.pending) return;
    const controller = new AbortController();
    this.pending = controller;
    this.busy.set(true);
    try { this.result.set(await this.application(controller.signal)); }
    catch { this.result.set('Application request failed'); }
    finally { this.pending = null; this.busy.set(false); }
  }
}
