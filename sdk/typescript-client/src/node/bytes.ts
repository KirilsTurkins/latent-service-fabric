// Read the native typed-array view length, not a subclass property override.
const lengthGetter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(Uint8Array.prototype), "byteLength")!.get!;

export function byteLength(value: Uint8Array): number {
  return lengthGetter.call(value) as number;
}
