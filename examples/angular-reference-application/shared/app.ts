import {isPlatformBrowser} from '@angular/common';
import {Component, DestroyRef, InjectionToken, PLATFORM_ID, TransferState, inject, makeStateKey, signal} from '@angular/core';
import {REFERENCE_VERSION} from './version.js';

export interface Page {
  subject: string;
  heading: string;
  message: string;
  outcome: string;
  view: 'main' | 'about';
}

const PAGE_KEY = makeStateKey<Page>('lsf-reference-page');
export const PAGE = new InjectionToken<Page>('reference-page', {
  providedIn: 'root',
  factory: () => inject(TransferState).get(PAGE_KEY, {
    subject: 'visitor', heading: 'Missing server state', message: '', outcome: 'missing', view: 'main',
  }),
});

@Component({
  selector: 'lsf-reference', standalone: true,
  template: `<header><p id="revision">{{version}}</p><nav aria-label="Reference views">
    <a id="home-link" href="/" (click)="navigate($event, 'main')">Home</a>
    <a id="about-link" href="/about" (click)="navigate($event, 'about')">About</a>
  </nav></header>
  <main>
    <h1 id="greeting">{{page.heading}}</h1>
    <p id="subject">{{page.subject}}</p>
    @if (view() === 'about') {
      <section id="about-view"><h2>One shared node</h2><p>Navigation reuses this hydrated Angular application.</p></section>
    } @else {
      <section id="main-view"><p id="outcome">{{page.outcome}}</p><p id="message">{{page.message}}</p></section>
    }
    <button id="count" type="button" (click)="increment()">Count {{count()}}</button>
  </main>`,
})
export class App {
  readonly page = inject(PAGE);
  readonly version = REFERENCE_VERSION;
  readonly view = signal(this.page.view);
  readonly count = signal(0);

  constructor() {
    inject(TransferState).set(PAGE_KEY, this.page);
    if (isPlatformBrowser(inject(PLATFORM_ID))) {
      const onPopState = () => this.view.set(globalThis.location.pathname === '/about' ? 'about' : 'main');
      globalThis.addEventListener('popstate', onPopState);
      inject(DestroyRef).onDestroy(() => globalThis.removeEventListener('popstate', onPopState));
    }
  }

  navigate(event: MouseEvent, view: 'main' | 'about') {
    if (event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    this.view.set(view);
    globalThis.history.pushState(null, '', view === 'about' ? '/about' : '/');
  }

  increment() {
    this.count.update(value => value + 1);
  }
}
