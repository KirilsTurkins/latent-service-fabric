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
      throw new Error('unsupported finite diagnostic selector');
    } catch (error) {
      return JSON.stringify({mode, error: String(error), cause: String((error as {cause?: unknown})?.cause)});
    }
  },
};
