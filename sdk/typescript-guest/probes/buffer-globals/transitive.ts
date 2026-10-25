import {original, timerBytes} from './dependency.js';
export const initial = globalThis.Buffer.concat([original, Buffer.alloc(1, 0x56)]);
export {timerBytes};
