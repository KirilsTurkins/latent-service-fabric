import { SmartBuffer } from 'smart-buffer';
import { initialized } from './dependency.js';

let calls = 0;
function check(value: boolean): void { if (!value) throw new Error('smart-buffer-fixture'); }
export const api = {
  async run(which: number): Promise<string> {
    check(++calls === 1);
    check(initialized.length === 2 && initialized.internalBuffer.readUInt16BE(0) === 0x1234);
    check(Buffer.isBuffer(initialized.internalBuffer) && initialized.internalBuffer.constructor === Buffer);
    if (which === 0) {
      const value = new SmartBuffer();
      check(value.length === 0 && value.internalBuffer.length === 4096);
      value.writeUInt16BE(0x1234);
      check(value.readUInt16BE() === 0x1234 && value.remaining() === 0);
    } else if (which === 1) {
      const value = SmartBuffer.fromSize(2).writeUInt16BE(0x1234)
        .writeUInt8(0x56).insertUInt8(0xab, 1);
      check(value.toBuffer().toString('hex') === '12ab3456' && value.length === 4);
      const shared = value.toBuffer(); shared[1] = 0xcd;
      check(value.internalBuffer.toString('hex', 0, 4) === '12cd3456');
      check(value.readUInt16BE() === 0x12cd);
    } else if (which === 2) {
      const value = await new Promise<SmartBuffer>(resolve =>
        setTimeout(() => resolve(SmartBuffer.fromSize(2).writeStringNT('A\u00e9')), 1));
      check(value.toBuffer().toString('hex') === '41c3a900');
      check(value.readStringNT() === 'A\u00e9' && value.readOffset === 4 && value.remaining() === 0);
    } else if (which === 3) {
      const value = SmartBuffer.fromSize(4).writeUInt8(7);
      let refused = false;
      try { value.readUInt16BE(); }
      catch (error) {
        refused = error instanceof Error &&
          error.message === 'Attempted to read beyond the bounds of the managed data.';
      }
      check(refused && value.readOffset === 0 && value.readUInt8() === 7 && value.remaining() === 0);
    } else if (which === 4) {
      let refused = false;
      try { SmartBuffer.fromSize(1048577); }
      catch (error) {
        refused = error instanceof RangeError && 'code' in error && error.code === 'ERR_OUT_OF_RANGE';
      }
      check(refused && SmartBuffer.fromSize(2).writeUInt16BE(0x3456).readUInt16BE() === 0x3456);
      initialized.internalBuffer[0] = 0xff;
    } else if (which === 5) {
      check(initialized.readUInt16BE() === 0x1234);
      check(SmartBuffer.fromSize(1).writeUInt8(9).toBuffer().toString('hex') === '09');
    } else throw new RangeError('smart-buffer-fixture-mode');
    return 'smart-buffer:' + which + ':pass|fresh=1';
  },
};
