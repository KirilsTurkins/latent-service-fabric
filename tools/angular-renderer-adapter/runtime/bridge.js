import './timers.js';
import {prepare, render} from './application.js';

let activations = 0;
export const engine = {
  async prepare(input) {
    if (activations !== 0) throw new Error('renderer-prepare-order');
    activations = 1;
    const frame = JSON.parse(input);
    if (frame.formatVersion !== 1) throw new Error('renderer-adapter-contract');
    return JSON.stringify(await prepare(frame.request, frame.context));
  },
  async render(input) {
    // Defense against an accidentally retained guest instance. No attempt to
    // reset arbitrary application globals, injectors or outstanding promises.
    if (activations > 1) throw new Error('renderer-store-reuse-denied');
    activations = 2;
    const frame = JSON.parse(input);
    if (frame.formatVersion !== 1) throw new Error('renderer-adapter-contract');
    return JSON.stringify(await render(frame.request, frame.context, frame.backend ?? null));
  },
};
