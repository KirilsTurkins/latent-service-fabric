// Finite real-provider diagnostic, separate from the conformance fixtures.
export const api = {
  async run(port: number, mode: number): Promise<string> {
    const url = `http://localhost:${port}/allowed`;
    try {
      const options = {method: 'POST', body: 'abcdefgh', headers: {'x-fetch-control': '0'},
        signal: new AbortController().signal, redirect: 'error' as const};
      const response = await fetch(url, options);
      if (mode === 0) {
        await response.body!.cancel('diagnostic-after-headers');
        return JSON.stringify({stage: 'headers-and-cancel', status: response.status});
      }
      return JSON.stringify({stage: 'complete', status: response.status, text: await response.text()});
    } catch (error) {
      const cause = (error as {cause?: {payload?: unknown}})?.cause;
      return JSON.stringify({mode, error: String(error), cause: String(cause), payload: cause?.payload});
    }
  },
};
