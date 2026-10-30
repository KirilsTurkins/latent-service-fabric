import { SmartBuffer } from 'smart-buffer';
export const initialized = SmartBuffer.fromSize(2).writeUInt16BE(0x1234);
