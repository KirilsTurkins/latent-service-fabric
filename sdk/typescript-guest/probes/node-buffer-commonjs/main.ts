import xor from 'buffer-xor';
import { Buffer } from 'node:buffer';
import { Buffer as BareBuffer } from 'buffer';
import { Buffer as SafeBuffer } from 'safe-buffer';

let activations = 0;
function check(value: boolean): void {
  if (!value) throw new Error('published CommonJS Buffer case failed');
}
export const api = {
  run(mode: number): string {
    activations += 1;
    check(activations === 1);
    if (mode === 0) {
      const result = xor(Buffer.from([0, 255, 85, 170]), Buffer.from([255, 1, 170, 85]));
      check(result.toString('hex') === 'fffeffff');
    } else if (mode === 1) {
      const short = Buffer.from([255, 15]);
      const long = Buffer.from([1, 2, 3, 4]);
      check(xor(short, long).toString('hex') === 'fe0d0304');
      check(xor(long, short).toString('hex') === 'fe0d0304');
    } else if (mode === 2) {
      const empty = Buffer.alloc(0);
      check(xor(empty, empty).length === 0);
      check(xor(empty, Buffer.from([7, 8])).toString('hex') === '0708');
      check(xor(Buffer.from([7, 8]), empty).toString('hex') === '0708');
    } else if (mode === 3) {
      const a = Buffer.from([1, 2, 3]);
      const b = Buffer.from([4, 5, 6]);
      const first = xor(a, b);
      const second = xor(a, b);
      check(first !== a && first !== b && first !== second);
      check(first.toString('hex') === '050705');
      first[0] = 99;
      check(a.toString('hex') === '010203' && b.toString('hex') === '040506');
      check(second.toString('hex') === '050705');
    } else if (mode === 4) {
      const text = Buffer.from('\u00e9\u20ac', 'utf8');
      check(xor(text, Buffer.alloc(text.length)).toString('utf8') === '\u00e9\u20ac');
      check(xor(Buffer.from('AAECAwQ=', 'base64'), Buffer.from('ff00ff00ff', 'hex')).toString('hex') === 'ff01fd03fb');
    } else if (mode === 5) {
      check(Object.is(Buffer, BareBuffer) && Object.is(Buffer, SafeBuffer));
      check(Buffer.isBuffer(xor(Buffer.from([9]), Buffer.from([3]))));
      check(!('Buffer' in globalThis));
    } else {
      throw new RangeError('unknown published CommonJS case');
    }
    return 'buffer:' + mode + ':pass|fresh=' + activations;
  }
};
