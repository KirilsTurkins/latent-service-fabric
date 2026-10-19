// Compiler-owned standard Math.random path. This is not a crypto API.
export function installMathRandom(source, snapshotActive, target = globalThis.Math) {
  if (typeof snapshotActive !== 'function' || !target || typeof target !== 'object') {
    throw new TypeError('standard-entropy-installation-shape');
  }
  const read = source === null ? null : source?.u64Value;
  const toNumber = Number, Unsupported = Error, Invalid = TypeError;
  if (read !== null && typeof read !== 'function') throw new TypeError('standard-entropy-source-shape');
  function random() {
    if (snapshotActive()) throw new Unsupported('snapshot-time-entropy-observation-unsupported');
    if (read === null) throw new Unsupported('unsupported:Math.random-without-approved-entropy');
    // Every draw uses the admitted source. No seed, cached draw or retry exists.
    const bits = read();
    if (typeof bits !== 'bigint' || bits < 0n || bits > 0xffffffffffffffffn) {
      throw new Invalid('standard-entropy-u64-result');
    }
    return toNumber(bits >> 11n) / 9007199254740992;
  }
  Object.defineProperty(target, 'random', {value: random, writable: true, configurable: true,
                                        enumerable: false});
}
