import type * as Contract from '../generated/interfaces/examples-shipping-api.js';

// lsf-example-begin: capsule
export const api: typeof Contract = {
  quote(items, express) {
    if (items < 1 || items > 100) throw 'Choose between 1 and 100 items.';
    return (express ? 1200 : 500) + items * 75;
  },
};
// lsf-example-end: capsule
