import { Buffer } from "node:buffer";
import { create, fromBinary, toBinary, ScalarType, type DescField, type DescMessage, type Message } from "@bufbuild/protobuf";
import { preflight, ShapeError } from "./preflight.js";

interface Budget { bytes: number; fields: number; messages: number }
type RecordValue = Record<string, unknown>;

export function encode(schema: DescMessage, value: unknown, maximum: number): Uint8Array {
  const message = input(schema, value, { bytes: maximum, fields: 2048, messages: 256 }, 0);
  const encoded = toBinary(schema, message, { writeUnknownFields: false });
  if (encoded.length > maximum) throw new ShapeError();
  return encoded;
}

export function decode(schema: DescMessage, bytes: Uint8Array, maximum: number): RecordValue {
  if (bytes.length > maximum) throw new ShapeError();
  preflight(schema, bytes);
  const message = fromBinary(schema, bytes, { readUnknownFields: false, recursionLimit: 12 });
  return output(schema, message as unknown as RecordValue);
}

function debit(budget: Budget, bytes: number): void {
  budget.bytes -= bytes;
  if (budget.bytes < 0 || --budget.fields < 0) throw new ShapeError();
}

function record(value: unknown): RecordValue {
  if (value === null || typeof value !== "object" || Array.isArray(value)) throw new ShapeError();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) throw new ShapeError();
  if (Object.values(Object.getOwnPropertyDescriptors(value)).some((entry) => !("value" in entry))) throw new ShapeError();
  return value as RecordValue;
}

function input(schema: DescMessage, raw: unknown, budget: Budget, depth: number): Message {
  if (depth > 12 || --budget.messages < 0) throw new ShapeError();
  const value = record(raw);
  if (Object.keys(value).some((key) => !Object.hasOwn(schema.field, key))) throw new ShapeError();
  const result: RecordValue = {};
  for (const field of schema.fields) {
    const source = value[field.localName];
    if (source === undefined) continue;
    debit(budget, 10);
    const converted = fieldInput(field, source, budget, depth);
    if (field.oneof) {
      if (result[field.oneof.localName] !== undefined) throw new ShapeError();
      result[field.oneof.localName] = { case: field.localName, value: converted };
    } else result[field.localName] = converted;
  }
  return create(schema, result);
}

function fieldInput(field: DescField, value: unknown, budget: Budget, depth: number): unknown {
  if (field.fieldKind === "map") {
    const entries = Object.entries(record(value));
    if (entries.length > 32 || field.mapKey !== ScalarType.STRING
      || (field.scalar !== ScalarType.STRING && field.scalar !== ScalarType.UINT64)) throw new ShapeError();
    const result: RecordValue = Object.create(null);
    for (const [key, item] of entries) {
      if (Buffer.byteLength(key, "utf8") > 128
        || (field.scalar === ScalarType.STRING && (typeof item !== "string" || Buffer.byteLength(item, "utf8") > 1024))) throw new ShapeError();
      scalarInput(ScalarType.STRING, false, key, budget);
      result[key] = scalarInput(field.scalar, false, item, budget);
    }
    return result;
  }
  if (field.fieldKind === "list") {
    if (!Array.isArray(value) || value.length > 128) throw new ShapeError();
    for (let index = 0; index < value.length; index++) if (!Object.hasOwn(value, index)) throw new ShapeError();
    return value.map((item: unknown) => field.message
      ? input(field.message, item, budget, depth + 1)
      : scalarInput(field.scalar, field.enum !== undefined, item, budget));
  }
  return field.message ? input(field.message, value, budget, depth + 1)
    : scalarInput(field.scalar, field.enum !== undefined, value, budget);
}

function scalarInput(kind: ScalarType | undefined, enumeration: boolean, value: unknown, budget: Budget): unknown {
  debit(budget, 10);
  if (kind === ScalarType.STRING) {
    if (typeof value !== "string") throw new ShapeError();
    for (const character of value) {
      const point = character.codePointAt(0)!;
      if (point >= 0xd800 && point <= 0xdfff) throw new ShapeError();
    }
    debit(budget, Buffer.byteLength(value, "utf8"));
  } else if (kind === ScalarType.BYTES) {
    if (!(value instanceof Uint8Array)) throw new ShapeError();
    debit(budget, value.byteLength);
    return Uint8Array.from(value);
  } else if (kind === ScalarType.UINT64) {
    if (typeof value !== "bigint" || value < 0n || value > 18446744073709551615n) throw new ShapeError();
  } else if (enumeration || kind === ScalarType.INT32 || kind === ScalarType.UINT32) {
    const minimum = kind === ScalarType.UINT32 ? 0 : -2147483648;
    const maximum = kind === ScalarType.UINT32 ? 4294967295 : 2147483647;
    if (typeof value !== "number" || !Number.isInteger(value) || value < minimum || value > maximum) throw new ShapeError();
  } else if (kind === ScalarType.BOOL) {
    if (typeof value !== "boolean") throw new ShapeError();
  } else throw new ShapeError();
  return value;
}

function output(schema: DescMessage, message: RecordValue): RecordValue {
  const result: RecordValue = {};
  for (const field of schema.fields) {
    let value = message[field.localName];
    if (field.oneof) {
      const selected = message[field.oneof.localName] as { case: string | undefined; value?: unknown };
      if (selected.case !== field.localName) continue;
      value = selected.value;
    }
    if (value === undefined) continue;
    if (field.fieldKind === "map") {
      result[field.localName] = Object.assign(Object.create(null), value);
    } else if (field.fieldKind === "list") {
      result[field.localName] = (value as unknown[]).map((item) => field.message
        ? output(field.message, item as RecordValue) : item);
    } else result[field.localName] = field.message ? output(field.message, value as RecordValue)
      : field.scalar === ScalarType.BYTES ? Uint8Array.from(value as Uint8Array) : value;
  }
  return result;
}
