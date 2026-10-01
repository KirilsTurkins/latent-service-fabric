import * as raw from 'latent:state/key-value@0.2.0';
import { Owner, drop } from './owner.js';
import { borrowCommand } from './state-internal.js';
import { enumCall, type Result } from './result.js';
export type { CommandInfo, Entry, PageInfo, StateError, Value, Version, VersionedValue, ViewIdentity } from 'latent:state/key-value@0.2.0';
const errors: readonly raw.StateError[] = ['permission-denied', 'invalid-key', 'invalid-value', 'invalid-limit',
  'invalid-cursor', 'stale-input', 'conflict', 'read-budget-exhausted', 'write-budget-exhausted', 'handle-closed',
  'wrong-activation', 'wrong-mode', 'unsupported-version', 'cancelled', 'unavailable'];
function invoke<T>(operation: () => T): Result<T, raw.StateError> { return enumCall(operation, errors); }
interface ViewGuard { guard<T>(operation: () => T): T; pageClosed(page: Page): void; }

/** Acquires the activation's existing command; no constructor, commit or retry. */
export class Command implements ViewGuard {
  #pages = new Set<Page>();
  private constructor(private readonly owner: Owner<raw.Transaction, 'state-command'>) {}
  static acquire(): Result<Command, raw.StateError> {
    return invoke(() => new Command(new Owner(raw.acquireCommand(), drop)));
  }
  guard<T>(operation: () => T): T { return this.owner.borrow(() => operation()); }
  info(): Result<raw.CommandInfo, raw.StateError> { return invoke(() => this.owner.borrow(raw.info)); }
  get(key: Uint8Array): Result<raw.VersionedValue | undefined, raw.StateError> {
    return invoke(() => this.owner.borrow(value => raw.get(value, key)));
  }
  put(key: Uint8Array, value: raw.Value): Result<void, raw.StateError> {
    return invoke(() => this.owner.borrow(owner => raw.put(owner, key, value)));
  }
  delete(key: Uint8Array): Result<void, raw.StateError> {
    return invoke(() => this.owner.borrow(owner => raw.delete(owner, key)));
  }
  scan(prefix: Uint8Array, limit: number, cursor?: Uint8Array): Result<Page, raw.StateError> {
    return invoke(() => this.owner.borrow(owner => {
      const page = new Page(new Owner(raw.scan(owner, prefix, limit, cursor), drop), this);
      this.#pages.add(page);
      return page;
    }));
  }
  /** @internal The optional intent facade borrows this same canonical owner. */
  [borrowCommand]<T>(operation: (transaction: raw.Transaction) => T): T { return this.owner.borrow(operation); }
  pageClosed(page: Page): void { this.#pages.delete(page); }
  close(): void {
    if (this.#pages.size !== 0) throw new Error('state-pages-open');
    this.owner.close(); // Drop releases access only; the host owns accepted work.
  }
}

/** Fresh read-only access exposes no mutation or intent operation. */
export class Query implements ViewGuard {
  #pages = new Set<Page>();
  private constructor(private readonly owner: Owner<raw.QueryView, 'state-query'>) {}
  static acquire(): Result<Query, raw.StateError> {
    return invoke(() => new Query(new Owner(raw.acquireQuery(), drop)));
  }
  guard<T>(operation: () => T): T { return this.owner.borrow(() => operation()); }
  info(): Result<raw.ViewIdentity, raw.StateError> { return invoke(() => this.owner.borrow(raw.queryInfo)); }
  get(key: Uint8Array): Result<raw.VersionedValue | undefined, raw.StateError> {
    return invoke(() => this.owner.borrow(owner => raw.getQuery(owner, key)));
  }
  scan(prefix: Uint8Array, limit: number, cursor?: Uint8Array): Result<Page, raw.StateError> {
    return invoke(() => this.owner.borrow(owner => {
      const page = new Page(new Owner(raw.scanQuery(owner, prefix, limit, cursor), drop), this);
      this.#pages.add(page);
      return page;
    }));
  }
  pageClosed(page: Page): void { this.#pages.delete(page); }
  close(): void {
    if (this.#pages.size !== 0) throw new Error('state-pages-open');
    this.owner.close();
  }
}

/** One entry per suspended host call, charged to the original live view. */
export class Page {
  #closed = false;
  constructor(private readonly owner: Owner<raw.Page, 'state-page'>, private readonly view: ViewGuard) {}
  info(): Result<raw.PageInfo, raw.StateError> {
    return invoke(() => this.view.guard(() => this.owner.borrow(raw.describePage)));
  }
  next(): Result<raw.Entry | undefined, raw.StateError> {
    return invoke(() => this.view.guard(() => this.owner.borrow(raw.pageNext)));
  }
  close(): void {
    if (this.#closed) return;
    this.owner.close();
    this.#closed = true;
    this.view.pageClosed(this);
  }
}
