// Repository-owned transitive fixture, not a published-library claim.
export const original = Buffer.from([0x12, 0x34]);
export function timerBytes(): number {
  return globalThis.Buffer.concat([original, Buffer.from([0x56])]).readUInt16BE(1);
}
