import {Component, InjectionToken, TransferState, inject, makeStateKey, signal} from '@angular/core';
const KEY = makeStateKey<string>('lsf-name');
export const NAME = new InjectionToken<string>('name', {
  providedIn: 'root', factory: () => inject(TransferState).get(KEY, 'missing'),
});
@Component({selector: 'lsf-demo', standalone: true,
  template: '<h1 id="greeting">Hello {{name}}</h1><button id="count" (click)="increment()">Count {{count()}}</button>'})
export class App {
  name = inject(NAME);
  count = signal(0);
  constructor() { inject(TransferState).set(KEY, this.name); }
  increment() { this.count.update(value => value + 1); }
}
