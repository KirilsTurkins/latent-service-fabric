/** WIT declared errors are data. An ordinary JavaScript exception still traps. */
export type Result<T, E> = { tag: 'ok'; val: T } | { tag: 'err'; val: E };

export function call<T, E extends { tag: string }>(operation: () => T,
    tags: readonly E['tag'][]): Result<T, E> {
  try { return { tag: 'ok', val: operation() }; }
  catch (error) {
    // The pinned maintained generator puts a WIT result error in Error.payload.
    // Never translate arbitrary exceptions or resource misuse into WIT success.
    // The generated binding and application use distinct SpiderMonkey realms;
    // instanceof uses the local Error prototype and rejects valid WIT errors.
    if (typeof error !== 'object' || error === null
        || Object.prototype.toString.call(error) !== '[object Error]'
        || !Object.hasOwn(error, 'payload')) throw error;
    const value: unknown = (error as Error & { payload: unknown }).payload;
    if (typeof value !== 'object' || value === null || !('tag' in value)
        || typeof value.tag !== 'string' || Object.keys(value).length !== 1
        || !tags.includes(value.tag)) throw error;
    return { tag: 'err', val: value as E };
  }
}

/** Propagate a declared error through a generated WIT result export. */
export function unwrap<T, E>(result: Result<T, E>): T {
  if (result.tag === 'err') throw result.val;
  return result.val;
}
