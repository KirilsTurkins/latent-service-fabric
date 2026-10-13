// Installed SDK globals; the application supplies no transport or polyfill.
let calls = 0;
export const api = {
  async run(port: number, mode: number): Promise<number> {
    if (++calls !== 1) throw new Error('stale-fetch-activation');
    const url = `http://localhost:${port}/allowed`;
    if (mode === 4) {
      try { await fetch(url, {method: 'POST', body: 'abcdefgh', headers: {'x-fetch-control': '0'},
        signal: new AbortController().signal, redirect: 'error'}); }
      catch (error) {
        if (!(error instanceof TypeError)) throw error;
        const cause = (error as {cause?: {message?: string, payload?: {tag?: string}}}).cause;
        if (cause?.payload?.tag !== 'permission-denied') throw new Error(`native-denial-not-reached:${cause?.message}`);
        return 42;
      }
      throw new Error('denied native provider unexpectedly contacted');
    }
    const controller = new AbortController();
    const response = await fetch(url, {
      method: 'POST', body: 'abcdefgh', headers: {'x-fetch-control': String(mode)},
      signal: controller.signal, redirect: 'error',
    });
    if (response.status !== 200 || response.headers.get('x-fetch-response') !== 'native')
      throw new Error('native response metadata changed');
    if (mode === 0) {
      if (await response.text() !== 'abcdefgh' || !response.bodyUsed)
        throw new Error('default body consumer changed');
      return 42;
    }
    if (mode === 6) {
      // Root return leaves the actual canonical body owned until native Store
      // cleanup. The host verifies socket closure and zero physical owners.
      return 42;
    }
    const reader = response.body!.getReader();
    if (mode === 1) {
      const pending = reader.read();
      setTimeout(() => controller.abort('actual-read-abort'), 20);
      try { await pending; throw new Error('borrowed read did not cancel'); }
      catch (error) { if (error !== 'actual-read-abort') throw error; }
      // Native cleanup must stay accepted and drain after the stream errors.
      reader.releaseLock();
      return 42;
    }
    if (mode === 2) {
      const first = await reader.read();
      if (first.done || Array.from(first.value!).join(',') !== '97,98,99,100')
        throw new Error('native partial body changed');
      await reader.cancel('drop-unread-tail');
      reader.releaseLock();
      return 42;
    }
    if (mode === 3) {
      // The host cancels this real parked read and verifies physical closure.
      await reader.read();
      throw new Error('externally cancelled read unexpectedly returned');
    }
    if (mode === 5) {
      const first = await reader.read();
      if (first.done || Array.from(first.value!).join(',') !== '97,98,99,100')
        throw new Error('native first chunk changed');
      throw new Error('trap-with-unread-body');
    }
    throw new Error('finite-fetch-selector-required');
  },
};
