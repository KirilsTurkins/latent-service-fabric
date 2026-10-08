import {isPlatformBrowser} from '@angular/common';
import {Component, InjectionToken, PLATFORM_ID, TransferState, inject, makeStateKey, signal} from '@angular/core';
import {DraftClient} from './transaction-client.js';

export interface DraftView {
  draftId: string;
  revision: string;
  units: number;
  namespaceView: string;
  keyVersion?: string;
}
export interface Page {
  heading: string;
  draftId?: string;
  draft?: DraftView;
  error?: string;
  routes: {command: string; query: string; result: string};
}
const PAGE_KEY = makeStateKey<Page>('lsf-order-draft-page');
export const PAGE = new InjectionToken<Page>('order-draft-page', {
  providedIn: 'root', factory: () => inject(TransferState).get(PAGE_KEY, {
    heading: 'Order draft unavailable', error: 'The current read could not be authorized.',
    routes: {command: '/draft/edit', query: '/draft/query', result: '/draft/result'},
  }),
});

@Component({
  selector: 'lsf-order-draft', standalone: true,
  template: `<header><h1>{{page.heading}}</h1><p>One draft, one original command.</p></header>
  <main>
    @if (draft(); as value) {
      <section aria-labelledby="draft-heading"><h2 id="draft-heading">Draft {{value.draftId}}</h2>
      <p id="draft-revision">Revision {{value.revision}}</p><p id="draft-units">Units {{value.units}}</p></section>
      <form (submit)="submit($event)">
        <label for="units">Units</label><input id="units" type="number" min="0" max="10000" [value]="chosenUnits()" (input)="chooseUnits($event)" [disabled]="busy()">
        <label><input id="reject-edit" type="checkbox" [checked]="rejectEdit()" (change)="chooseRejection($event)" [disabled]="busy()">Reject this edit</label>
        <button id="submit-draft" type="submit" [disabled]="busy() || originalRetained()">Save draft</button>
      </form>
    }
    <p id="command-status" role="status" aria-live="polite">{{status()}}</p>
    <p id="application-message" role="alert">{{message()}}</p>
    <p id="effect-status">{{effectCount()}} original effects</p>
    <div>
      <button id="recover-draft" type="button" (click)="recover()" [disabled]="busy() || !originalRetained()">Recover original command</button>
      <button id="query-draft" type="button" (click)="refresh()" [disabled]="busy()">Read current draft</button>
      <button id="retry-aborted-draft" type="button" (click)="retryAborted()" [disabled]="busy() || status() !== 'aborted'">Retry proven abort</button>
      <button id="finish-original-draft" type="button" (click)="finishOriginal()" [disabled]="busy() || !terminal()">Start another edit</button>
    </div>
  </main>`,
})
export class App {
  readonly page = inject(PAGE);
  readonly draft = signal<DraftView | undefined>(this.page.draft);
  readonly chosenUnits = signal(this.page.draft?.units ?? 0);
  readonly rejectEdit = signal(false);
  readonly busy = signal(false);
  readonly originalRetained = signal(false);
  readonly status = signal('idle');
  readonly message = signal(this.page.error ?? '');
  readonly effectCount = signal(0);
  private readonly client: DraftClient | undefined;

  constructor() {
    inject(TransferState).set(PAGE_KEY, this.page);
    if (isPlatformBrowser(inject(PLATFORM_ID))) {
      this.client = new DraftClient(this.page.routes);
      this.client.view = this.page.draft;
    }
  }
  terminal() { return this.status() === 'committed' || this.status() === 'rejected'; }
  chooseUnits(event: Event) {
    const value = Number((event.target as HTMLInputElement).value);
    if (Number.isInteger(value) && value >= 0 && value <= 10000) this.chosenUnits.set(value);
  }
  chooseRejection(event: Event) { this.rejectEdit.set((event.target as HTMLInputElement).checked); }
  private update(result: {disposition: string; value?: DraftView | {error: string}; effectIds?: string[]}) {
    if (result.value && 'error' in result.value) this.message.set(result.value.error);
    else if (result.value) { this.draft.set(result.value); this.message.set(''); }
    if (result.disposition !== 'query') {
      this.status.set(result.disposition); this.effectCount.set(result.effectIds?.length ?? 0);
    }
  }
  private async run(action: (client: DraftClient) => Promise<void>) {
    if (!this.client || this.busy()) return;
    this.busy.set(true); this.message.set('');
    try { await action(this.client); }
    catch {
      this.status.set(this.client.status);
      if (this.client.status === 'permission-denied') {
        this.draft.set(undefined); this.message.set('Current access was refused.');
      } else this.message.set('The response is unavailable. Recover the original command before another edit.');
    } finally {
      this.originalRetained.set(this.client.pending !== undefined); this.busy.set(false);
    }
  }
  async submit(event: Event) {
    event.preventDefault();
    const current = this.draft();
    if (!current) return;
    await this.run(async client => {
      // Preserve this screen's business revision. No current reread is allowed
      // to silently refresh an already prepared edit or its original identity.
      client.prepare(current.draftId, current.revision, this.chosenUnits(), this.rejectEdit());
      this.originalRetained.set(true); this.status.set('pending');
      const result = await client.submit(); this.update(result);
      if (result.disposition === 'committed') this.update(await client.query(current.draftId));
    });
  }
  async recover() { await this.run(async client => this.update(await client.recover())); }
  async refresh() {
    const id = this.draft()?.draftId ?? this.page.draftId;
    if (!id) return;
    await this.run(async client => this.update(await client.query(id)));
  }
  async retryAborted() { await this.run(async client => this.update(await client.retryAborted())); }
  finishOriginal() {
    if (!this.client || this.busy() || !this.terminal()) return;
    this.client.finishOriginal(); this.originalRetained.set(false); this.status.set('idle');
  }
}
