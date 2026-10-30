import {Buffer as bare} from 'buffer';
import {Buffer as named} from 'node:buffer';
import {initial, timerBytes} from './transitive.js';

let calls = 0;
function check(value: boolean): void { if (!value) throw new Error('global-buffer-fixture'); }
export const api = {
  async run(which: number): Promise<string> {
    check(++calls === 1);
    check(Buffer === bare && bare === named && globalThis.Buffer === named);
    check(initial.toString('hex') === '123456');
    const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'Buffer');
    check(descriptor?.value === named && descriptor.writable === true &&
      descriptor.configurable === true && descriptor.enumerable === false);
    if (which === 0) {
      const view = initial.subarray(0, 2);
      view[1] = 0x35;
      check(initial.readUInt16BE(0) === 0x1235);
      const copy = Buffer.from(view); copy[0] = 0;
      check(view[0] === 0x12);
    } else if (which === 1) {
      const value = await new Promise<number>(resolve => setTimeout(() => resolve(timerBytes()), 1));
      check(value === 0x3456);
    } else if (which === 2) {
      let caught = false;
      try { Buffer.alloc(1048577); }
      catch (error) {
        caught = error instanceof RangeError && 'code' in error && error.code === 'ERR_OUT_OF_RANGE';
      }
      check(caught && Buffer.alloc(2, 7).readUInt16BE(0) === 0x0707);
      initial.fill(0); // The next Store must still start from its original initializer bytes.
    } else if (which === 3) {
      check(initial.readUInt16BE(0) === 0x1234 && Buffer.from('A').toString('hex') === '41');
    } else throw new RangeError('global-buffer-fixture-mode');
    return 'global-buffer:' + which + ':pass|fresh=1';
  },
};
