import type * as Contract from '../generated/interfaces/examples-greeting-api.js';
import { trim, utf8Length } from '../vendor/lsf/sdk/typescript-guest/runtime/text.js';

// lsf-example-begin: capsule
export const api: typeof Contract = {
  greet(name) {
    const clean = trim(name);
    if (!clean) throw 'Please enter a name.';
    if (utf8Length(clean) > 100) throw 'Use a name of at most 100 bytes.';
    return `Hello, ${clean}!`;
  },
};
// lsf-example-end: capsule
