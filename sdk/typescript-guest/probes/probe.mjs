import { echo } from 'lsf:typescript-probe/host@1.0.0';

let calls = 0;
export const probe = {
  run(input) {
    if (++calls !== 1) throw new Error('stale-activation-state');
    if (input.text === 'panic') { while (true) { /* host fuel must terminate */ } }
    if (!input.text.trim()) throw 'Please enter text.';
    if (input.text.length > 4096 || input.bytes.length > 1024) throw 'Input limit exceeded.';
    return { value: input.value, text: echo(input.text), bytes: input.bytes };
  },
};
