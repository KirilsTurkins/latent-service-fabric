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
