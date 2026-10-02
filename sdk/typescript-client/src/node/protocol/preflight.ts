import { ScalarType, type DescField, type DescMessage } from "@bufbuild/protobuf";
import { BinaryReader, WireType } from "@bufbuild/protobuf/wire";

export class ShapeError extends Error {
  readonly unsupportedWireValue?: { readonly field: string; readonly value: string };
  constructor(field?: string, value?: string) {
    super("unsupported or malformed bounded protobuf shape");
    if (field !== undefined && value !== undefined && value.length <= 256) this.unsupportedWireValue = { field, value };
  }
}

interface Work { fields: number; messages: number; graph: number; transaction: boolean }

export function preflight(schema: DescMessage, bytes: Uint8Array, transaction = false): void {
  walk(schema, bytes, 0, { fields: transaction ? 65536 : 2048, messages: transaction ? 4096 : 256, graph: 8 * 1024 * 1024, transaction });
}

function charge(work: Work, bytes: number): void {
  if (work.transaction && (work.graph -= bytes) < 0) throw new ShapeError();
}

function walk(schema: DescMessage, bytes: Uint8Array, depth: number, work: Work): void {
  if (depth > 12 || --work.messages < 0) throw new ShapeError();
  charge(work, 128 + schema.fields.length * 48);
  const reader = new BinaryReader(bytes);
  const counts = new Map<number, number>();
  const groups = new Set<string>();
  const maps = new Map<number, Set<string>>();
  while (reader.pos < reader.len) {
    const [number, wire] = reader.tag();
    if (--work.fields < 0 || wire === WireType.StartGroup || wire === WireType.EndGroup) throw new ShapeError();
    const field = schema.fields.find((candidate) => candidate.number === number);
    if (!field) {
      reader.skip(wire, number, 12);
      continue;
    }
    const count = (counts.get(number) ?? 0) + 1;
    counts.set(number, count);
    const maximum = field.fieldKind === "list" ? field.name === "required_record_ids" ? 256 : 128 : field.fieldKind === "map" ? 32 : 1;
    if (count > maximum) throw new ShapeError();
    if (field.oneof) {
      if (groups.has(field.oneof.localName)) throw new ShapeError();
      groups.add(field.oneof.localName);
    }
    if (field.fieldKind === "map") {
      charge(work, 256);
      if (wire !== WireType.LengthDelimited) throw new ShapeError();
      const key = mapEntry(field, reader.bytes(), work);
      const keys = maps.get(number) ?? new Set<string>();
      if (keys.has(key)) throw new ShapeError();
      keys.add(key);
      maps.set(number, keys);
    } else if (field.message) {
      if (wire !== WireType.LengthDelimited) throw new ShapeError();
      walk(field.message, reader.bytes(), depth + 1, work);
    } else {
      if (field.fieldKind === "list") charge(work, 48);
      scalar(field.scalar, field.enum !== undefined, reader, wire, work, bytes);
    }
  }
  if (reader.pos !== reader.len) throw new ShapeError();
}

function mapEntry(field: DescField, bytes: Uint8Array, work: Work): string {
  if (field.fieldKind !== "map" || field.mapKey !== ScalarType.STRING
    || (field.scalar !== ScalarType.STRING && field.scalar !== ScalarType.UINT64)) throw new ShapeError();
  const reader = new BinaryReader(bytes);
  const seen = new Set<number>();
  let key = "";
  while (reader.pos < reader.len) {
    const [number, wire] = reader.tag();
    if (--work.fields < 0 || wire === WireType.StartGroup || wire === WireType.EndGroup) throw new ShapeError();
    if (number === 1 || number === 2) {
      if (seen.has(number)) throw new ShapeError();
      seen.add(number);
      if (number === 1 || field.scalar === ScalarType.STRING) {
        if (wire !== WireType.LengthDelimited) throw new ShapeError();
        const text = reader.string(true);
        charge(work, Buffer.byteLength(text, "utf8") * 3 + 64);
        if (Buffer.byteLength(text, "utf8") > (number === 1 ? work.transaction ? 256 : 128 : 1024)) throw new ShapeError();
        if (number === 1) key = text;
      } else scalar(field.scalar, false, reader, wire, work, bytes);
    } else {
      reader.skip(wire, number, 12);
    }
  }
  return key;
}

function scalar(kind: ScalarType | undefined, enumeration: boolean, reader: BinaryReader, wire: WireType, work: Work, source: Uint8Array): void {
  if (kind === ScalarType.STRING || kind === ScalarType.BYTES) {
    if (wire !== WireType.LengthDelimited) throw new ShapeError();
    const start = reader.pos;
    if (kind === ScalarType.STRING) reader.string(true); else reader.bytes();
    charge(work, (reader.pos - start) * 3 + 64);
    return;
  }
  if (wire !== WireType.Varint) throw new ShapeError();
  if (work.transaction) {
    let value = 0n, finished = false;
    for (let index = 0; index < 10; index++) {
      const byte = source[reader.pos + index];
      if (byte === undefined || (index === 9 && byte > 1)) throw new ShapeError();
      value |= BigInt(byte & 127) << BigInt(7 * index);
      if (byte < 128) { finished = true; break; }
    }
    if (!finished || (kind === ScalarType.BOOL && value > 1n)
      || (kind === ScalarType.UINT32 && value > 4294967295n)
      || ((enumeration || kind === ScalarType.INT32) && value > 2147483647n && value < 18446744071562067968n)) throw new ShapeError();
  }
  if (enumeration || kind === ScalarType.INT32) reader.int32();
  else if (kind === ScalarType.UINT32) reader.uint32();
  else if (kind === ScalarType.UINT64) reader.uint64();
  else if (kind === ScalarType.BOOL) reader.bool();
  else throw new ShapeError();
}
