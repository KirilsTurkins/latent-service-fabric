/** Internal typed wire boundary. Never installed as a node capability transport. */
export type Option<T> = { readonly tag: 'none' } | { readonly tag: 'some'; readonly val: T };
export type Result<T, E> = { readonly tag: 'ok'; readonly val: T } | { readonly tag: 'err'; readonly val: E };
export type Shape = {
  readonly kind: string;
  readonly type?: Shape;
  readonly types?: readonly Shape[];
  readonly fields?: readonly (readonly [string, Shape])[];
  readonly identity?: string;
  readonly name?: string;
};
export type Broker = { call(name: string, argumentsJson: string): string; drop(kind: string, token: number): void };
const MAX_FRAME_BYTES = 1024 * 1024;
const MAX_VALUES = 131072;
const MAX_RESOURCES = 256;
const resourceKey = Symbol('guest-resource-construction');
const resourceData = new WeakMap<Resource, { scope: Scope; kind: string; token: number; drop: () => void; live: boolean }>();

export class BoundaryError extends Error {
  constructor(reason: string) { super(`typescript-guest:${reason}`); this.name = 'BoundaryError'; }
}
function requireValue(condition: unknown, reason: string): asserts condition {
  if (!condition) throw new BoundaryError(reason);
}
function camel(name: string): string { return name.replace(/-([a-z0-9])/g, (_, char: string) => char.toUpperCase()); }

/** An actual host resource owner. User code cannot manufacture a valid owner. */
export class Resource<Identity extends string = string> {
  declare private readonly identity: Identity;
  constructor(key: symbol) { requireValue(key === resourceKey, 'resource-construction-denied'); }
  dispose(): void {
    const data = resourceData.get(this);
    requireValue(data, 'foreign-resource');
    if (!data.live) return;
    data.scope.release(this);
  }
}

/** Owns exactly one invocation, not a deployment or a shared execution cell. */
export class Scope {
  #state: 'unstarted' | 'active' | 'closed' = 'unstarted';
  #owners = new Set<Resource>();
  #tokens = new Set<string>();
  #secrets = new Set<Uint8Array>();
  #calls = 0;
  begin(): void {
    requireValue(this.#state === 'unstarted', 'guest-instance-reuse-denied');
    this.#state = 'active';
  }
  check(): void { requireValue(this.#state === 'active', 'operation-outside-activation'); }
  own(kind: string, token: number, drop: () => void): Resource {
    this.check();
    requireValue(Number.isInteger(token) && token > 0 && token <= 0xffffffff, 'invalid-resource-token');
    const key = `${kind}:${token}`;
    requireValue(!this.#tokens.has(key) && this.#owners.size < MAX_RESOURCES, 'resource-identity-or-limit');
    const owner = new Resource(resourceKey);
    resourceData.set(owner, { scope: this, kind, token, drop, live: true });
    this.#owners.add(owner);
    this.#tokens.add(key);
    return owner;
  }
  token(owner: unknown, kind: string): number {
    this.check();
    requireValue(owner instanceof Resource, 'resource-owner-required');
    const data = resourceData.get(owner);
    requireValue(data && data.scope === this && data.kind === kind && data.live, 'resource-ownership-mismatch');
    return data.token;
  }
  transfer(owner: Resource): void {
    const data = resourceData.get(owner);
    requireValue(data && data.scope === this && data.live, 'resource-already-consumed');
    data.live = false;
    this.#owners.delete(owner);
    this.#tokens.delete(`${data.kind}:${data.token}`);
  }
  release(owner: Resource): void {
    this.check();
    const data = resourceData.get(owner);
    requireValue(data && data.scope === this && data.live, 'resource-already-consumed');
    this.transfer(owner); // A destructor is never retried, even if it traps.
    data.drop();
  }
  secret(bytes: Uint8Array): () => void {
    this.check();
    this.#secrets.add(bytes);
    return () => { bytes.fill(0); this.#secrets.delete(bytes); };
  }
  enterCall(): void { this.check(); this.#calls += 1; }
  leaveCall(): void { this.#calls -= 1; }
  close(): void {
    this.check();
    let failure: unknown;
    for (const owner of [...this.#owners]) {
      try { this.release(owner); } catch (error) { failure ??= error; }
    }
    for (const bytes of this.#secrets) bytes.fill(0);
    this.#secrets.clear();
    this.#state = 'closed';
    if (failure) throw failure;
    requireValue(this.#calls === 0, 'unfinished-capability-operation');
  }
}

function utf8Length(text: string): number {
  let size = 0;
  for (let i = 0; i < text.length; i += 1) {
    const value = text.charCodeAt(i);
    if (value >= 0xd800 && value <= 0xdbff) {
      const low = text.charCodeAt(++i);
      requireValue(low >= 0xdc00 && low <= 0xdfff, 'unpaired-surrogate');
      size += 4;
    } else {
      requireValue(value < 0xdc00 || value > 0xdfff, 'unpaired-surrogate');
      size += value < 128 ? 1 : value < 2048 ? 2 : 3;
    }
    requireValue(size <= MAX_FRAME_BYTES, 'wire-byte-limit');
  }
  return size;
}
function record(value: unknown, keys: readonly string[]): Record<string, unknown> {
  requireValue(value !== null && typeof value === 'object' && !Array.isArray(value), 'record-required');
  const prototype = Object.getPrototypeOf(value);
  requireValue(prototype === Object.prototype || prototype === null, 'plain-record-required');
  const actual = Reflect.ownKeys(value);
  requireValue(actual.length === keys.length && actual.every(key => typeof key === 'string' && keys.includes(key)), 'record-fields');
  for (const key of keys) requireValue(Object.getOwnPropertyDescriptor(value, key)?.get === undefined
    && Object.getOwnPropertyDescriptor(value, key)?.set === undefined, 'record-accessor');
  return value as Record<string, unknown>;
}

class Walker {
  #values = 0;
  readonly moves = new Set<Resource>();
  readonly borrows = new Set<Resource>();
  constructor(readonly scope: Scope, readonly broker?: Broker) {}
  visit(shape: Shape, value: unknown, decoding: boolean, depth = 0): unknown {
    requireValue(depth <= 64 && ++this.#values <= MAX_VALUES, 'wire-value-limit');
    const next = (type: Shape, item: unknown): unknown => this.visit(type, item, decoding, depth + 1);
    const kind = shape.kind;
    if (kind === 'unit') {
      requireValue(value === (decoding ? null : undefined), 'unit-required');
      return decoding ? undefined : null;
    }
    if (kind === 'bool') { requireValue(typeof value === 'boolean', 'boolean-required'); return value; }
    if (kind === 'string' || kind === 'char') {
      requireValue(typeof value === 'string', 'string-required');
      utf8Length(value);
      if (kind === 'char') requireValue([...value].length === 1, 'unicode-scalar-required');
      return value;
    }
    if (/^[us](8|16|32|64)$/.test(kind)) {
      const width = Number(kind.slice(1));
      const signed = kind[0] === 's';
      const maximum = (1n << BigInt(width - (signed ? 1 : 0))) - 1n;
      const minimum = signed ? -(maximum + 1n) : 0n;
      if (width === 64) {
        if (decoding) {
          requireValue(typeof value === 'string' && /^(0|-?[1-9][0-9]*)$/.test(value) && value.length <= 20, 'decimal-integer-required');
          const integer = BigInt(value);
          requireValue(integer >= minimum && integer <= maximum, 'integer-range');
          return integer;
        }
        requireValue(typeof value === 'bigint' && value >= minimum && value <= maximum, 'bigint-range');
        return value.toString();
      }
      requireValue(typeof value === 'number' && Number.isInteger(value) && !Object.is(value, -0)
        && value >= Number(minimum) && value <= Number(maximum), 'integer-range');
      return value;
    }
    if (kind === 'f32' || kind === 'f64') {
      if (decoding && typeof value === 'string') {
        const special: Record<string, number> = { nan: NaN, inf: Infinity, '-inf': -Infinity, '-0': -0 };
        requireValue(Object.hasOwn(special, value), 'float-tag');
        return special[value];
      }
      requireValue(typeof value === 'number' && (!decoding || Number.isFinite(value)), 'float-required');
      const number = kind === 'f32' ? Math.fround(value) : value;
      if (decoding) return number;
      return Number.isNaN(number) ? 'nan' : number === Infinity ? 'inf' : number === -Infinity ? '-inf' : Object.is(number, -0) ? '-0' : number;
    }
    if (kind === 'list') {
      const element = shape.type!;
      const isBytes = element.kind === 'u8';
      requireValue(decoding ? Array.isArray(value) : isBytes ? value instanceof Uint8Array : Array.isArray(value), 'list-required');
      const values = value as readonly unknown[];
      requireValue(values.length <= MAX_VALUES, 'list-limit');
      const output = Array.from(values, item => next(element, item));
      return decoding && isBytes ? Uint8Array.from(output as number[]) : output;
    }
    if (kind === 'tuple') {
      requireValue(Array.isArray(value) && value.length === shape.types!.length, 'tuple-arity');
      return shape.types!.map((type, i) => next(type, value[i]));
    }
    if (kind === 'record') {
      const fields = shape.fields!;
      const object = record(value, fields.map(([name]) => camel(name)));
      return Object.fromEntries(fields.map(([name, type]) => [camel(name), next(type, object[camel(name)])]));
    }
    if (kind === 'enum') {
      requireValue(typeof value === 'string' && shape.fields!.some(([name]) => name === value), 'enum-case');
      return value;
    }
    if (kind === 'flags') {
      requireValue(decoding ? Array.isArray(value) : value instanceof Set, 'flags-required');
      const flags = [...(value as string[] | Set<string>)];
      const names = shape.fields!.map(([name]) => name);
      requireValue(flags.length <= names.length && new Set(flags).size === flags.length && flags.every(flag => names.includes(flag)), 'flags-cases');
      return decoding ? new Set(flags) : names.filter(flag => flags.includes(flag));
    }
    if (kind === 'option' || kind === 'result' || kind === 'variant') {
      requireValue(value && typeof value === 'object' && typeof (value as { tag?: unknown }).tag === 'string', 'tag-required');
      const tag = (value as { tag: string }).tag;
      let type: Shape | undefined;
      if (kind === 'option') type = tag === 'none' ? { kind: 'unit' } : tag === 'some' ? shape.type : undefined;
      else if (kind === 'result') type = tag === 'ok' ? shape.types![0] : tag === 'err' ? shape.types![1] : undefined;
      else type = shape.fields!.find(([name]) => name === tag)?.[1];
      requireValue(type, 'unknown-case');
      // Unit result arms retain an explicit val in TypeScript; zero-payload
      // variant arms and option:none have only their tag.
      const payload = kind === 'result' || type.kind !== 'unit';
      const object = record(value, payload ? ['tag', 'val'] : ['tag']);
      return payload ? { tag, val: next(type, object.val) } : { tag };
    }
    if (kind === 'own' || kind === 'borrow' || kind === 'resource') {
      const identity = kind === 'resource' ? shape.identity! : shape.type!.identity!;
      if (decoding) {
        requireValue(kind !== 'borrow' && this.broker, 'borrowed-result-not-supported');
        requireValue(typeof value === 'number', 'resource-token-required');
        return this.scope.own(identity, value, () => this.broker!.drop(identity, value));
      }
      const token = this.scope.token(value, identity);
      const owner = value as Resource;
      if (kind === 'borrow') {
        requireValue(!this.moves.has(owner), 'resource-borrow-after-move');
        this.borrows.add(owner);
      } else {
        requireValue(!this.moves.has(owner) && !this.borrows.has(owner), 'duplicate-resource-transfer');
        this.moves.add(owner);
      }
      return token;
    }
    throw new BoundaryError(`unsupported-shape-${kind}`);
  }
}

export function stringify(value: unknown): string {
  const text = JSON.stringify(value);
  requireValue(typeof text === 'string', 'wire-json-required');
  utf8Length(text);
  return text;
}
export function parse(text: string): unknown {
  requireValue(typeof text === 'string', 'wire-frame-required');
  utf8Length(text);
  return JSON.parse(text);
}

export function encode(shape: Shape, value: unknown, scope: Scope): string {
  const walker = new Walker(scope);
  const output = stringify(walker.visit(shape, value, false));
  requireValue(walker.moves.size === 0, 'resource-export-not-supported');
  return output;
}
export function decode(shape: Shape, text: string, scope: Scope): unknown {
  return new Walker(scope).visit(shape, parse(text), true);
}

/** Call precisely once. WIT errors are values; traps are not translated. */
export function call(scope: Scope, broker: Broker, name: string,
                     parameters: readonly Shape[], result: Shape, args: readonly unknown[]): unknown {
  scope.enterCall();
  try {
    requireValue(args.length === parameters.length, 'argument-count');
    const walker = new Walker(scope, broker);
    const encoded = parameters.map((type, i) => walker.visit(type, args[i], false));
    const input = stringify(encoded);
    for (const owner of walker.moves) scope.transfer(owner);
    const output = broker.call(name, input);
    return new Walker(scope, broker).visit(result, parse(output), true);
  } finally { scope.leaveCall(); }
}
