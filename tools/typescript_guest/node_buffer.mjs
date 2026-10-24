// Compiler-owned lsf-node-buffer-v1. Pure guest storage, not a native buffer.
// Allocations, including copies, remain subject to the original guest heap cap.
export const kMaxLength = 1024 * 1024;
export const kStringMaxLength = 4 * 1024 * 1024;
export const constants = Object.freeze({ MAX_LENGTH: kMaxLength, MAX_STRING_LENGTH: kStringMaxLength });
const brands = new WeakSet();
const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
const unknown = name => { throw Object.assign(new TypeError('node-buffer-unsupported:' + name), {code: 'ERR_BUFFER_UNSUPPORTED'}); };
function range(name) { throw Object.assign(new RangeError('node-buffer-range:' + name), {code: 'ERR_OUT_OF_RANGE'}); }
function type(name) { throw Object.assign(new TypeError('node-buffer-type:' + name), {code: 'ERR_INVALID_ARG_TYPE'}); }
function size(value) {
  if (typeof value !== 'number') type('size');
  if (!Number.isFinite(value) || value < 0 || Math.trunc(value) > kMaxLength) range('size');
  return Math.trunc(value);
}
function string(value) {
  if (typeof value !== 'string') type('string');
  if (value.length > kStringMaxLength) range('string');
  return value;
}
function encoding(value = 'utf8') {
  if (typeof value !== 'string') type('encoding');
  switch (value.toLowerCase()) {
    case 'utf8': case 'utf-8': return 'utf8';
    case 'ucs2': case 'ucs-2': case 'utf16le': case 'utf-16le': return 'utf16le';
    case 'binary': case 'latin1': return 'latin1';
    case 'ascii': case 'hex': case 'base64': case 'base64url': return value.toLowerCase();
    default: throw Object.assign(new TypeError('Unknown encoding: ' + value), {code: 'ERR_UNKNOWN_ENCODING'});
  }
}
function utf8Length(text, maximum = Infinity) {
  let count = 0, end = 0;
  for (let i = 0; i < text.length;) {
    const first = text.charCodeAt(i);
    const paired = first >= 0xd800 && first <= 0xdbff && i + 1 < text.length &&
      text.charCodeAt(i + 1) >= 0xdc00 && text.charCodeAt(i + 1) <= 0xdfff;
    const bytes = first < 0x80 ? 1 : first < 0x800 ? 2 : paired ? 4 : 3;
    if (count + bytes > maximum) break;
    count += bytes; i += paired ? 2 : 1; end = i;
  }
  return {count, end};
}
function hexDigit(code) {
  code &= 255; // Node's string decoder consumes the low byte of each code unit.
  return code >= 48 && code <= 57 ? code - 48 : code >= 65 && code <= 70 ? code - 55 :
    code >= 97 && code <= 102 ? code - 87 : -1;
}
function base64Digit(code) {
  code &= 255;
  return code >= 65 && code <= 90 ? code - 65 : code >= 97 && code <= 122 ? code - 71 :
    code >= 48 && code <= 57 ? code + 4 : code === 43 || code === 45 ? 62 :
    code === 47 || code === 95 ? 63 : -1;
}
function decodedLength(text, enc) {
  if (enc === 'utf8') return utf8Length(text).count;
  if (enc === 'utf16le') return text.length * 2;
  if (enc === 'hex') {
    let n = 0;
    while (n * 2 + 1 < text.length && hexDigit(text.charCodeAt(n * 2)) >= 0 &&
      hexDigit(text.charCodeAt(n * 2 + 1)) >= 0) ++n;
    return n;
  }
  if (enc === 'base64' || enc === 'base64url') {
    let digits = 0;
    for (let i = 0; i < text.length && (text.charCodeAt(i) & 255) !== 61; ++i)
      if (base64Digit(text.charCodeAt(i)) >= 0) ++digits;
    return Math.floor(digits * 6 / 8);
  }
  return text.length;
}
function decode(text, enc) {
  string(text);
  const length = size(decodedLength(text, enc)); // BEFORE the allocating codec.
  if (enc === 'utf8') {
    const value = new TextEncoder().encode(text);
    return new Buffer(value.buffer, value.byteOffset, value.byteLength);
  }
  const output = new Buffer(length);
  if (enc === 'base64' || enc === 'base64url') {
    let bits = 0, available = 0, at = 0;
    for (let i = 0; i < text.length && (text.charCodeAt(i) & 255) !== 61; ++i) {
      const digit = base64Digit(text.charCodeAt(i));
      if (digit < 0) continue;
      bits = (bits << 6) | digit; available += 6;
      if (available >= 8) { available -= 8; output[at++] = (bits >>> available) & 255; }
    }
  } else if (enc === 'hex') {
    for (let i = 0; i < length; ++i) output[i] = hexDigit(text.charCodeAt(i * 2)) * 16 + hexDigit(text.charCodeAt(i * 2 + 1));
  } else if (enc === 'utf16le') {
    for (let i = 0; i < text.length; ++i) { const c = text.charCodeAt(i); output[i * 2] = c & 255; output[i * 2 + 1] = c >>> 8; }
  } else {
    for (let i = 0; i < length; ++i) output[i] = text.charCodeAt(i) & 255;
  }
  return output;
}
function bytes(value) {
  if (!(value instanceof Uint8Array)) type('Uint8Array');
  return value;
}
function index(value, length, fallback) {
  if (value === undefined) return fallback;
  let n = Number(value);
  if (Number.isNaN(n)) n = 0;
  n = Math.trunc(n);
  return n < 0 ? Math.max(length + n, 0) : Math.min(n, length);
}
function bound(value, maximum, name) {
  if (typeof value !== 'number') type(name);
  if (!Number.isInteger(value) || value < 0 || value > maximum) range(name);
  return value;
}
function characters(values) {
  const pieces = [];
  for (let i = 0; i < values.length; i += 4096) pieces.push(String.fromCharCode(...values.subarray(i, i + 4096)));
  return pieces.join('');
}

export class Buffer extends Uint8Array {
  constructor(value = 0, offset = 0, length = undefined) {
    if (value instanceof ArrayBuffer) {
      offset = +offset;
      offset = Number.isNaN(offset) ? 0 : Math.trunc(offset);
      if (offset < 0) throw new RangeError('Start offset is outside the bounds of the buffer');
      if (offset > value.byteLength) throw Object.assign(new RangeError('offset outside buffer bounds'), {code: 'ERR_BUFFER_OUT_OF_BOUNDS'});
      const count = length === undefined ? value.byteLength - offset : Math.max(0, Math.trunc(+length) || 0);
      if (count > value.byteLength - offset) throw Object.assign(new RangeError('length outside buffer bounds'), {code: 'ERR_BUFFER_OUT_OF_BOUNDS'});
      size(count); super(value, offset, count);
    } else { super(size(value)); }
    brands.add(this);
  }
  static from(value, offsetOrEncoding, length) {
    if (typeof value === 'string') return decode(value, encoding(offsetOrEncoding));
    if (value instanceof ArrayBuffer) return new Buffer(value, offsetOrEncoding ?? 0, length);
    if (value && value.type === 'Buffer' && Array.isArray(value.data)) value = value.data;
    if (!Array.isArray(value) && !(ArrayBuffer.isView(value) && !(value instanceof DataView))) type('from');
    const output = new Buffer(size(value.length));
    output.set(value); // Native ToNumber/ToUint8; BigInt arrays fail truthfully.
    return output;
  }
  static alloc(length, fill = 0, enc) { const output = new Buffer(size(length)); return output.fill(fill, 0, output.length, enc); }
  // The selected profile deliberately supplies zero-filled unsafe allocation.
  static allocUnsafe(length) { return new Buffer(size(length)); }
  static allocUnsafeSlow(length) { return new Buffer(size(length)); }
  static isBuffer(value) { return brands.has(value); }
  static isEncoding(value) { try { if (typeof value !== 'string') return false; encoding(value); return true; } catch { return false; } }
  static byteLength(value, enc) {
    if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) return value.byteLength;
    string(value); enc = encoding(enc);
    if (enc === 'hex') return Math.floor(value.length / 2);
    if (enc === 'base64' || enc === 'base64url') {
      let length = value.length;
      if (value[length - 1] === '=') --length;
      if (value[length - 1] === '=') --length;
      return Math.floor(length * 3 / 4); // Node estimates, unlike permissive decode.
    }
    return decodedLength(value, enc);
  }
  static concat(list, totalLength) {
    if (!Array.isArray(list) || list.length > 4096) type('list');
    let needed = 0;
    for (const item of list) { bytes(item); needed += item.byteLength; if (!Number.isSafeInteger(needed)) range('length'); }
    const output = new Buffer(size(totalLength === undefined ? needed : totalLength));
    let at = 0;
    for (const item of list) { const count = Math.min(item.length, output.length - at); if (count > 0) output.set(item.subarray(0, count), at); at += count; }
    return output;
  }
  static compare(a, b) {
    bytes(a); bytes(b);
    for (let i = 0; i < Math.min(a.length, b.length); ++i) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
    return a.length === b.length ? 0 : a.length < b.length ? -1 : 1;
  }
  subarray(start, end) {
    const from = index(start, this.length, 0), to = Math.max(from, index(end, this.length, this.length));
    return new Buffer(this.buffer, this.byteOffset + from, to - from);
  }
  slice(start, end) { return this.subarray(start, end); }
  equals(other) { return Buffer.compare(this, other) === 0; }
  compare(target, targetStart = 0, targetEnd = target.length, sourceStart = 0, sourceEnd = this.length) {
    bytes(target); bound(targetStart, target.length, 'targetStart'); bound(targetEnd, target.length, 'targetEnd');
    bound(sourceStart, this.length, 'sourceStart'); bound(sourceEnd, this.length, 'sourceEnd');
    return Buffer.compare(this.subarray(sourceStart, sourceEnd), target.subarray(targetStart, targetEnd));
  }
  copy(target, targetStart = 0, sourceStart = 0, sourceEnd = this.length) {
    bytes(target);
    const integer = n => Math.trunc(+n) || 0;
    targetStart = integer(targetStart); sourceStart = integer(sourceStart); sourceEnd = integer(sourceEnd);
    for (const n of [targetStart, sourceStart, sourceEnd]) if (n < 0) range('copy');
    if (sourceStart > this.length) range('sourceStart');
    const count = Math.max(0, Math.min(sourceEnd, this.length) - sourceStart);
    const copied = Math.max(0, Math.min(count, target.length - targetStart));
    if (copied) target.set(this.subarray(sourceStart, sourceStart + copied), targetStart); // overlap-safe memmove
    return copied;
  }
  fill(value = 0, start = 0, end = this.length, enc) {
    if (typeof start === 'string') { enc = start; start = 0; end = this.length; }
    else if (typeof end === 'string') { enc = end; end = this.length; }
    bound(start, this.length, 'start'); bound(end, this.length, 'end');
    if (end <= start) return this;
    if (typeof value === 'number') { Uint8Array.prototype.fill.call(this, value, start, end); return this; }
    let pattern;
    if (typeof value === 'string') pattern = value === '' ? new Buffer(1) : decode(value, encoding(enc));
    else pattern = Buffer.from(bytes(value)); // Snapshot before aliasing writes.
    if (!pattern.length) throw Object.assign(new TypeError('Invalid fill value'), {code: 'ERR_INVALID_ARG_VALUE'});
    for (let i = start; i < end; ++i) this[i] = pattern[(i - start) % pattern.length];
    return this;
  }
  toString(enc, start = 0, end = this.length) {
    enc = encoding(enc);
    // Buffer.toString clamps negative bounds to0, unlike shared slice.
    start = Number(start); end = Number(end);
    start = Number.isNaN(start) || start < 0 ? 0 : Math.min(Math.trunc(start), this.length);
    end = Number.isNaN(end) || end < 0 ? 0 : Math.min(Math.trunc(end), this.length);
    const view = this.subarray(start, Math.max(start, end));
    if (enc === 'utf8') return new TextDecoder('utf-8', {ignoreBOM: true}).decode(view);
    if (enc === 'utf16le') {
      const units = new Uint16Array(Math.floor(view.length / 2));
      for (let i = 0; i < units.length; ++i) units[i] = view[i * 2] | view[i * 2 + 1] << 8;
      return characters(units);
    }
    if (enc === 'ascii' || enc === 'latin1') {
      if (enc === 'latin1') return characters(view);
      return characters(Uint8Array.prototype.map.call(view, value => value & 127));
    }
    const pieces = []; let part = '';
    if (enc === 'hex') {
      for (const value of view) { part += value.toString(16).padStart(2, '0'); if (part.length >= 4096) { pieces.push(part); part = ''; } }
    } else {
      for (let i = 0; i < view.length; i += 3) {
        const n = view[i] << 16 | (view[i + 1] ?? 0) << 8 | (view[i + 2] ?? 0);
        part += alphabet[n >>> 18] + alphabet[n >>> 12 & 63] +
          (i + 1 < view.length ? alphabet[n >>> 6 & 63] : '=') + (i + 2 < view.length ? alphabet[n & 63] : '=');
        if (part.length >= 4096) { pieces.push(part); part = ''; }
      }
    }
    pieces.push(part);
    const result = pieces.join('');
    return enc === 'base64url' ? result.replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '') : result;
  }
  write(text, offset = 0, length = this.length - (typeof offset === 'number' ? offset : 0), enc) {
    string(text);
    if (typeof offset === 'string') { enc = offset; offset = 0; length = this.length; }
    else if (typeof length === 'string') { enc = length; length = this.length - offset; }
    bound(offset, this.length, 'offset'); bound(length, this.length, 'length');
    length = Math.min(length, this.length - offset); enc = encoding(enc);
    if (enc === 'utf8') text = text.slice(0, utf8Length(text, length).end);
    else if (enc === 'utf16le') text = text.slice(0, Math.floor(length / 2));
    const source = decode(text, enc), count = Math.min(length, source.length);
    this.set(source.subarray(0, count), offset); return count;
  }
  toJSON() { return {type: 'Buffer', data: Array.from(this)}; }
}

function numericOffset(owner, offset, width) {
  if (offset === undefined) offset = 0;
  if (width > owner.length) throw Object.assign(new RangeError('Attempt to access memory outside buffer bounds'), {code: 'ERR_BUFFER_OUT_OF_BOUNDS'});
  bound(offset, owner.length - width, 'offset'); return offset;
}
function readNumber(owner, offset, width, signed, little) {
  offset = numericOffset(owner, offset, width);
  let value = 0;
  for (let i = 0; i < width; ++i) value = value * 256 + owner[offset + (little ? width - 1 - i : i)];
  return signed && value >= 2 ** (width * 8 - 1) ? value - 2 ** (width * 8) : value;
}
function writeNumber(owner, value, offset, width, signed, little) {
  value = +value;
  const low = signed ? -(2 ** (width * 8 - 1)) : 0, high = signed ? 2 ** (width * 8 - 1) - 1 : 2 ** (width * 8) - 1;
  if (value < low || value > high) range('value');
  offset = numericOffset(owner, offset, width);
  value = Number.isNaN(value) ? 0 : Math.trunc(value);
  if (value < 0) value += 2 ** (width * 8);
  for (let i = 0; i < width; ++i) { owner[offset + (little ? i : width - 1 - i)] = value % 256; value = Math.floor(value / 256); }
  return offset + width;
}
for (const signed of [false, true]) for (const width of [1, 2, 4]) for (const little of width === 1 ? [true] : [true, false]) {
  const name = (signed ? 'Int' : 'UInt') + width * 8 + (width === 1 ? '' : little ? 'LE' : 'BE');
  Object.defineProperty(Buffer.prototype, 'read' + name, {value(offset) { return readNumber(this, offset, width, signed, little); }, writable: true, configurable: true});
  Object.defineProperty(Buffer.prototype, 'write' + name, {value(value, offset) { return writeNumber(this, value, offset, width, signed, little); }, writable: true, configurable: true});
}
for (const signed of [false, true]) for (const little of [true, false]) {
  const name = (signed ? 'Int' : 'UInt') + (little ? 'LE' : 'BE');
  Object.defineProperty(Buffer.prototype, 'read' + name, {value(offset, width) { bound(width, 6, 'byteLength'); if (!width) range('byteLength'); return readNumber(this, offset, width, signed, little); }, writable: true, configurable: true});
  Object.defineProperty(Buffer.prototype, 'write' + name, {value(value, offset, width) { bound(width, 6, 'byteLength'); if (!width) range('byteLength'); return writeNumber(this, value, offset, width, signed, little); }, writable: true, configurable: true});
  const big = 'Big' + (signed ? 'Int' : 'UInt') + '64' + (little ? 'LE' : 'BE');
  Object.defineProperty(Buffer.prototype, 'read' + big, {value(offset) { offset = numericOffset(this, offset, 8); const view = new DataView(this.buffer, this.byteOffset, this.byteLength); return signed ? view.getBigInt64(offset, little) : view.getBigUint64(offset, little); }, writable: true, configurable: true});
  Object.defineProperty(Buffer.prototype, 'write' + big, {value(value, offset) {
    if (typeof value !== 'bigint') type('value');
    const low = signed ? -(1n << 63n) : 0n, high = signed ? (1n << 63n) - 1n : (1n << 64n) - 1n;
    if (value < low || value > high) range('value'); offset = numericOffset(this, offset, 8);
    const view = new DataView(this.buffer, this.byteOffset, this.byteLength);
    if (signed) view.setBigInt64(offset, value, little); else view.setBigUint64(offset, value, little);
    return offset + 8;
  }, writable: true, configurable: true});
}
for (const name of Object.getOwnPropertyNames(Buffer.prototype)) if (name.includes('UInt'))
  Object.defineProperty(Buffer.prototype, name.replace('UInt', 'Uint'), Object.getOwnPropertyDescriptor(Buffer.prototype, name));
for (const name of ['swap16', 'swap32', 'swap64', 'indexOf', 'lastIndexOf', 'includes',
  'readFloatLE', 'readFloatBE', 'readDoubleLE', 'readDoubleBE', 'writeFloatLE', 'writeFloatBE', 'writeDoubleLE', 'writeDoubleBE'])
  Object.defineProperty(Buffer.prototype, name, {value() { return unknown(name); }, writable: true, configurable: true});
export function SlowBuffer(length) { return Buffer.alloc(length); }
export default Object.freeze({Buffer, SlowBuffer, constants, kMaxLength, kStringMaxLength});
