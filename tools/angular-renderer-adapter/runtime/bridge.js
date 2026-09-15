import './timers.js';
import {render} from './application.js';

let activations = 0;
export const engine = {
  async render(input) {
    // Defense against an accidentally retained guest instance. No attempt to
    // reset arbitrary application globals, injectors or outstanding promises.
    if (++activations !== 1) throw new Error('renderer-store-reuse-denied');
    const frame = JSON.parse(input);
    if (frame.formatVersion !== 1) throw new Error('renderer-adapter-contract');
    return JSON.stringify(await render(frame.request, frame.context));
  },
};
