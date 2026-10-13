// Finite runtime diagnostic; these outputs do not qualify installed fetch.
export const api = {
  async run(mode: number): Promise<string> {
    const url = 'http://localhost:9876/allowed';
    try {
      if (mode === 0) {
        new Request(url, {method: 'POST', body: 'abcdefgh'});
        return 'Request-constructor:PASS';
      }
      if (mode === 1) {
        const request = new Request(url, {method: 'POST', body: 'abcdefgh'});
        return 'Request-text:' + await request.text();
      }
      if (mode === 2) {
        const request = new Request(url, {method: 'POST', body: 'abcdefgh'});
        const reader = request.body!.getReader();
        const first = await reader.read();
        const second = await reader.read();
        reader.releaseLock();
        return JSON.stringify({bytes: Array.from(first.value!), done: second.done});
      }
      if (mode === 3) {
        const parsed = new URL(url);
        parsed.hash = '';
        return parsed.href;
      }
      if (mode >= 4 && mode <= 7) {
        const options = mode === 4 ? undefined : {method: 'POST',
          ...(mode >= 6 ? {body: 'abcdefgh'} : {}),
          ...(mode === 7 ? {signal: new AbortController().signal} : {})};
        await fetch(url, options);
        return 'denied diagnostic unexpectedly succeeded';
      }
      throw new Error('unsupported finite diagnostic selector');
    } catch (error) {
      const cause = (error as {cause?: {payload?: unknown}})?.cause;
      return JSON.stringify({mode, error: String(error), cause: String(cause), payload: cause?.payload});
    }
  },
};
