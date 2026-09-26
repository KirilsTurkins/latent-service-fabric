/** Explicit affine ownership, not authorization. No GC finalizers or retry. */
export class Owner<T, Kind extends string> {
  declare private readonly kind: Kind;
  #value: T | undefined;
  #busy = false;
  constructor(value: T, private readonly destroy: (value: T) => void) { this.#value = value; }
  borrow<R>(operation: (value: T) => R): R {
    if (this.#value === undefined || this.#busy) throw new Error('owner-closed-or-busy');
    this.#busy = true;
    try { return operation(this.#value); } finally { this.#busy = false; }
  }
  consume<R>(operation: (value: T) => R): R {
    if (this.#value === undefined || this.#busy) throw new Error('owner-closed-or-busy');
    const value = this.#value;
    this.#value = undefined; // Consumption is final even for an uncertain effect.
    return operation(value);
  }
  close(): void {
    if (this.#busy) throw new Error('owner-borrowed');
    if (this.#value !== undefined) this.consume(this.destroy);
  }
}

/** The maintained generator's canonical resource destructor, invoked explicitly. */
export function drop(value: object): void {
  const symbol = (Symbol as unknown as { dispose?: symbol }).dispose || Symbol.for('dispose');
  const destroy: unknown = (value as Record<symbol, unknown>)[symbol];
  if (typeof destroy !== 'function') throw new Error('generated-resource-destructor-missing');
  destroy.call(value);
}

/** A finite lexical group. Store destruction also reclaims owners after traps. */
export class Scope {
  #closed = false;
  #owners: { close(): void }[] = [];
  own<T extends { close(): void }>(owner: T): T {
    if (this.#closed || this.#owners.length >= 256) {
      owner.close();
      throw new Error('owner-scope-exhausted-or-closed');
    }
    this.#owners.push(owner);
    return owner;
  }
  close(): void {
    if (this.#closed) return;
    this.#closed = true;
    let failed = false;
    let failure: unknown;
    for (let i = this.#owners.length - 1; i >= 0; i -= 1) {
      try { this.#owners[i].close(); }
      catch (error) { if (!failed) { failed = true; failure = error; } }
    }
    this.#owners = [];
    if (failed) throw failure;
  }
}
