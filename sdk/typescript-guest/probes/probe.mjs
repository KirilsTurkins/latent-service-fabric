import { echo, roundtrip } from 'lsf:typescript-probe/host@1.0.0';

let calls = 0;
export const probe = {
  echoSigned(value) { return value; },
  run(input) {
    if (++calls !== 1) throw new Error('stale-activation-state');
    if (input.text === 'panic') { while (true) { /* host fuel must terminate */ } }
    if (!input.text.trim()) throw 'Please enter text.';
    if (input.text.length > 4096 || input.bytes.length > 1024) throw 'Input limit exceeded.';
    const [value, minimum, maximum] = roundtrip(input.value, input.minimum, input.maximum);
    return { value, minimum, maximum, text: echo(input.text), bytes: input.bytes };
  },
};
