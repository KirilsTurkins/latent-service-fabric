// Run in a child process: an unhandled zlib error must fail, not kill the test runner.
import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {constants, deflateRawSync} from 'node:zlib';

const require = createRequire(new URL('../toolchain/node_modules/npm/package.json', import.meta.url));
const {PerMessageDeflate} = require('undici/lib/web/websocket/permessage-deflate.js');
const compress = bytes => deflateRawSync(bytes, {finishFlush: constants.Z_SYNC_FLUSH});
const message = Buffer.from('bounded control');
await new Promise((resolve, reject) => {
  new PerMessageDeflate(new Map(), {maxPayloadSize: 1024}).decompress(compress(message), false, (error, bytes) => {
    if (error) { reject(error); return; }
    try { assert.deepEqual(bytes, message); resolve(); } catch (failure) { reject(failure); }
  });
});

// 32 KiB is enough for one output chunk to exceed the 16-byte test limit
// before a malformed DEFLATE block (reserved BTYPE=3) reaches the inflater.
// There are no sockets, giant payloads, timers or global uncaught-error handlers.
const payload = Buffer.concat([compress(Buffer.alloc(32 * 1024, 65)), Buffer.from([0x07])]);
let errors = 0;
new PerMessageDeflate(new Map(), {maxPayloadSize: 16}).decompress(payload, false, error => {
  assert.equal(error?.constructor.name, 'MessageSizeExceededError');
  errors++;
});
process.once('beforeExit', () => {
  assert.equal(errors, 1, 'The oversized message must fail exactly once without an unhandled zlib error');
  console.log('GHSA-3wwx-pv8p-q78v: bounded decompression and normal control passed');
});
