export const MAX_HYDRATION_BYTES = 32768;
export const MAX_HYDRATION_FIELDS = 64;
export type BrowserValue = string | number | boolean | null;
export type BrowserState = Readonly<Record<string, BrowserValue>>;

function record(value: unknown): asserts value is Record<string, unknown> {
  if (!value || typeof value !== 'object' ||
      ![Object.prototype, null].includes(Object.getPrototypeOf(value))) {
    throw new Error('hydration-record');
  }
}

function key(value: string): void {
  if (!/^[a-zA-Z][a-zA-Z0-9_-]{0,63}$/.test(value) ||
      ['constructor', 'prototype', 'toJSON'].includes(value)) {
    throw new Error('hydration-field');
  }
}

function scalar(value: unknown): asserts value is BrowserValue {
  if (value === null || typeof value === 'boolean' ||
      typeof value === 'number' && Number.isFinite(value) && !Object.is(value, -0) ||
      typeof value === 'string' && value.length <= 8192) return;
  throw new Error('hydration-scalar');
}

function bytes(value: string): number {
  let size = 0;
  for (const point of value) {
    const code = point.codePointAt(0)!;
    size += code < 128 ? 1 : code < 2048 ? 2 : code < 65536 ? 3 : 4;
  }
  return size;
}

function escaped(value: BrowserValue): string {
  return JSON.stringify(value).replace(/[<>&\u2028\u2029]/g, point =>
    '\\u' + point.charCodeAt(0).toString(16).padStart(4, '0'));
}

export function projectHydration(source: unknown, fields: readonly string[]): BrowserState {
  record(source);
  if (!Array.isArray(fields) || fields.length > MAX_HYDRATION_FIELDS || new Set(fields).size !== fields.length) {
    throw new Error('hydration-fields');
  }
  const projected: Record<string, BrowserValue> = Object.create(null);
  for (const field of fields) {
    key(field);
    const descriptor = Object.getOwnPropertyDescriptor(source, field);
    if (!descriptor || !Object.hasOwn(descriptor, 'value')) throw new Error('hydration-accessor');
    scalar(descriptor.value);
    projected[field] = descriptor.value;
  }
  serializeHydration(projected);
  return Object.freeze(projected);
}

export function serializeHydration(value: unknown): string {
  record(value);
  const names = Object.getOwnPropertyNames(value).sort();
  if (names.length > MAX_HYDRATION_FIELDS || Object.getOwnPropertySymbols(value).length) {
    throw new Error('hydration-fields');
  }
  const pieces: string[] = [];
  let size = 2;
  for (const name of names) {
    key(name);
    const descriptor = Object.getOwnPropertyDescriptor(value, name)!;
    if (!Object.hasOwn(descriptor, 'value')) throw new Error('hydration-accessor');
    scalar(descriptor.value);
    const entry = JSON.stringify(name) + ':' + escaped(descriptor.value);
    size += bytes(entry) + (pieces.length ? 1 : 0);
    if (size > MAX_HYDRATION_BYTES) throw new Error('hydration-size');
    pieces.push(entry);
  }
  return '{' + pieces.join(',') + '}';
}

export function parseHydration(value: string): BrowserState {
  if (typeof value !== 'string' || value.length > MAX_HYDRATION_BYTES || bytes(value) > MAX_HYDRATION_BYTES) {
    throw new Error('hydration-size');
  }
  const parsed: unknown = JSON.parse(value);
  if (serializeHydration(parsed) !== value) throw new Error('hydration-noncanonical');
  record(parsed);
  return projectHydration(parsed, Object.keys(parsed));
}
