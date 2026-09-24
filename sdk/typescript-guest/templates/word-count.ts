import type * as Contract from '../generated/interfaces/examples-word-count-api.js';
import { whitespace, utf8Length } from '../vendor/lsf/sdk/typescript-guest/runtime/text.js';

// lsf-example-begin: capsule
export const api: typeof Contract = {
  count(text) {
    if (utf8Length(text) > 4096) throw 'Use text of at most 4096 bytes.';
    let count = 0, inWord = false;
    for (const scalar of text) {
      const word = !whitespace(scalar);
      if (word && !inWord) count++;
      inWord = word;
    }
    return count;
  },
};
// lsf-example-end: capsule
