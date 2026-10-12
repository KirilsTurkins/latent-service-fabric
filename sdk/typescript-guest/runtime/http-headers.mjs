// Standard header values at the typed HTTP boundary. Construction grants no I/O.
const token = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;
const maximumEntries = 128;
const maximumBytes = 32768;

function byteString(value) {
  if (typeof value === 'symbol') throw new TypeError('header-value-is-not-a-ByteString');
  const text = String(value);
  for (let index = 0; index < text.length; index++) {
    if (text.charCodeAt(index) > 255) throw new TypeError('header-value-is-not-a-ByteString');
  }
  return text;
}

function name(value) {
  const text = byteString(value);
  if (!token.test(text)) throw new TypeError('invalid-header-name');
  return text.toLowerCase();
}

function content(value) {
  const text = byteString(value).replace(/^[\t ]+|[\t ]+$/g, '');
  if (/[\0\r\n]/.test(text)) throw new TypeError('invalid-header-value');
  return text;
}

export class Headers {
  #list = [];
  #immutable = false;

  constructor(initial = undefined) {
    if (initial === undefined) return;
    if (initial === null) throw new TypeError('invalid-headers-initializer');
    if (typeof initial[Symbol.iterator] === 'function') {
      let count = 0;
      for (const entry of initial) {
        if (++count > maximumEntries) throw new TypeError('header-entry-limit');
        if (entry === null || typeof entry[Symbol.iterator] !== 'function') {
          throw new TypeError('header-entry-must-be-a-pair');
        }
        const pair = [];
        for (const item of entry) {
          if (pair.length === 2) throw new TypeError('header-entry-must-be-a-pair');
          pair.push(item);
        }
        if (pair.length !== 2) throw new TypeError('header-entry-must-be-a-pair');
        this.append(pair[0], pair[1]);
      }
    } else if (typeof initial === 'object' || typeof initial === 'function') {
      const keys = Object.keys(initial);
      if (keys.length > maximumEntries) throw new TypeError('header-entry-limit');
      for (const key of keys) this.append(key, initial[key]);
    } else {
      throw new TypeError('invalid-headers-initializer');
    }
  }

  #writable() {
    if (this.#immutable) throw new TypeError('immutable-response-headers');
  }

  #replace(entries) {
    let bytes = 0;
    for (const [key, value] of entries) bytes += key.length + value.length;
    if (entries.length > maximumEntries || bytes > maximumBytes) {
      throw new TypeError('header-profile-limit');
    }
    this.#list = entries;
  }

  append(key, value) {
    this.#writable();
    this.#replace([...this.#list, [name(key), content(value)]]);
  }

  delete(key) {
    this.#writable();
    const normalized = name(key);
    this.#list = this.#list.filter(entry => entry[0] !== normalized);
  }

  get(key) {
    const normalized = name(key);
    const values = this.#list.filter(entry => entry[0] === normalized).map(entry => entry[1]);
    return values.length ? values.join(', ') : null;
  }

  getSetCookie() {
    return this.#list.filter(entry => entry[0] === 'set-cookie').map(entry => entry[1]);
  }

  has(key) {
    const normalized = name(key);
    return this.#list.some(entry => entry[0] === normalized);
  }

  set(key, value) {
    this.#writable();
    const normalized = name(key);
    const normalizedValue = content(value);
    const first = this.#list.findIndex(entry => entry[0] === normalized);
    const next = [];
    for (let index = 0; index < this.#list.length; index++) {
      const entry = this.#list[index];
      if (entry[0] !== normalized) next.push(entry);
      else if (index === first) next.push([normalized, normalizedValue]);
    }
    if (first === -1) next.push([normalized, normalizedValue]);
    this.#replace(next);
  }

  #sorted() {
    const keys = [...new Set(this.#list.map(entry => entry[0]))].sort();
    const result = [];
    for (const key of keys) {
      if (key === 'set-cookie') {
        for (const value of this.getSetCookie()) result.push([key, value]);
      } else result.push([key, this.get(key)]);
    }
    return result;
  }

  *entries() {
    let index = 0;
    while (true) {
      const entries = this.#sorted();
      if (index >= entries.length) return;
      yield entries[index++];
    }
  }

  *keys() { for (const [key] of this.entries()) yield key; }
  *values() { for (const [, value] of this.entries()) yield value; }
  [Symbol.iterator]() { return this.entries(); }

  forEach(callback, receiver = undefined) {
    if (typeof callback !== 'function') throw new TypeError('header-callback-required');
    for (const [key, value] of this.entries()) callback.call(receiver, value, key, this);
  }

  get [Symbol.toStringTag]() { return 'Headers'; }

  static fromTyped(entries) {
    const result = new Headers(entries.map(entry => [entry.name, entry.value]));
    result.#immutable = true;
    return result;
  }

  static typed(value) {
    if (!(value instanceof Headers)) throw new TypeError('headers-required');
    return value.#list.map(([name, value]) => ({name, value}));
  }

  static clone(value) {
    if (!(value instanceof Headers)) throw new TypeError('headers-required');
    const result = new Headers(value);
    result.#immutable = value.#immutable;
    return result;
  }
}
