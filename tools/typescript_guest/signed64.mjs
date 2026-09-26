// ComponentizeJS 0.22's embedding coreabi_from_bigint64 accepts unsigned
// bit patterns, including for canonical signed i64 arguments. The maintained
// generator's toInt64 intrinsic supplies a negative BigInt instead. Preserve
// exactly the same 64 bits at that internal boundary; WIT is never rewritten.
// See bytecodealliance/ComponentizeJS#343 and embedding/embedding.cpp.
export function coreI64Lowering(source) {
  if (!source.includes('function toInt64(')) return source;
  const intrinsic = /function toInt64\(val\)\s*\{\s*const converted = BigInt\(val\)\s*return BigInt\.asIntN\(64, converted\);\s*\}/g;
  const matches = [...source.matchAll(intrinsic)];
  if (matches.length !== 1 || source.split('function toInt64(').length !== 2) {
    throw new Error('signed-i64-generated-intrinsic-drift');
  }
  return source.replace(intrinsic, matches[0][0].replace('BigInt.asIntN', 'BigInt.asUintN'));
}

// The embedding's core i32 boundary reads an Int32 JS value. A u32 above
// INT32_MAX is represented as a Double in JS; pass the identical 32-bit signed
// core bit pattern, while canonical lifting still exposes an unsigned Number.
export function coreIntegerLowering(source) {
  source = coreI64Lowering(source);
  if (!source.includes('function toUint32(')) return source;
  const intrinsic = /function toUint32\(val\)\s*\{\s*return val >>> 0;\s*\}/g;
  const matches = [...source.matchAll(intrinsic)];
  if (matches.length !== 1 || source.split('function toUint32(').length !== 2) {
    throw new Error('unsigned-i32-generated-intrinsic-drift');
  }
  return source.replace(intrinsic, matches[0][0].replace('>>> 0', '| 0'));
}
