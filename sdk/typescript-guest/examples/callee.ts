import type * as Contract from '../generated/interfaces/tests-local-api.js';
export const api: typeof Contract = {
  answer() { return 42; },
  fail() { throw 'declared application failure'; },
  spin() { while (true) { /* Fuel, epoch deadline and cancellation remain host-owned. */ } },
};
