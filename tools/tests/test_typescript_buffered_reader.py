"""Real native stream semantics; emitted components remain a separate gate."""
from pathlib import Path
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BufferedReaderTests(unittest.TestCase):
    def javascript(self, source):
        module = (ROOT/'tools/typescript_guest/fetch.mjs').as_uri()
        prefix = f"import assert from 'node:assert/strict'; import {{installFetch}} from '{module}';\n"
        result = subprocess.run(['node', '--input-type=module', '-e', prefix+source],
                                capture_output=True, timeout=30, check=False)
        self.assertEqual(result.returncode, 0, result.stderr.decode())

    def test_request_dictionary_ignores_unknown_members_without_reading_them(self):
        self.javascript(r'''
const target = {TextEncoder, TextDecoder, URL, URLSearchParams, AbortController, AbortSignal, ReadableStream};
installFetch({}, () => false, target);
for (const Request of [globalThis.Request,target.Request]) {
  let reads=0;
  const init={method:'GET',get libraryOption(){reads++;throw new Error('must-not-read-unknown');}};
  assert.equal(new Request('https://example.test',init).method,'GET');
  assert.equal(reads,0);
}
for(const init of [{credentials:'include'},{keepalive:true},{cache:'reload'},{integrity:'sha256-unknown'}])
  assert.throws(()=>new target.Request('https://example.test',init),/unsupported:/);
''')

    def test_bounded_reader_lock_disturbance_cancel_and_one_shot_match_native(self):
        self.javascript(r'''
const target = {TextEncoder, TextDecoder, URL, URLSearchParams, AbortController, AbortSignal, ReadableStream};
installFetch({}, () => false, target);
for (const Response of [globalThis.Response, target.Response]) {
  const response = new Response('abc'), stream = response.body;
  assert.equal(response.body, stream); assert.equal(response.bodyUsed, false);
  const reader = stream.getReader();
  assert.equal(stream.locked, true); assert.equal(response.bodyUsed, false);
  assert.throws(() => response.clone(), TypeError);
  await assert.rejects(response.text(), TypeError);
  const pending = reader.read(); assert.equal(response.bodyUsed, true);
  assert.equal(new TextDecoder().decode((await pending).value), 'abc');
  assert.deepEqual(await reader.read(), {done:true, value:undefined});
  reader.releaseLock(); await assert.rejects(response.text(), TypeError);
  const canceled = new Response('cancel');
  await canceled.body.cancel('unused'); assert.equal(canceled.bodyUsed, true);
  await assert.rejects(canceled.arrayBuffer(), TypeError);
  const direct = new Response('direct'), unused = direct.body;
  assert.equal(await direct.text(), 'direct');
  assert.equal(unused.locked,true);
  assert.throws(() => unused.getReader(), TypeError);
  const plain = new Response('plain');
  assert.equal(await plain.text(),'plain'); assert.equal(plain.bodyUsed,true);
  assert.equal(plain.body.locked,true);
  assert.equal(new Response(null).body, null);
}
const response = new target.Response(new Uint8Array(131073).fill(7));
const reader = response.body.getReader(), lengths=[];
for (;;) { const {done,value}=await reader.read(); if(done) break;
  lengths.push(value.byteLength); assert.ok(value.every(v => v === 7)); }
assert.deepEqual(lengths, [65536,65536,1]);
''')

    def test_no_implicit_prefetch_tee_pipe_or_streaming_upload(self):
        self.javascript(r'''
const target = {TextEncoder, TextDecoder, URL, URLSearchParams, AbortController, AbortSignal, ReadableStream};
installFetch({}, () => false, target);
const response = new target.Response('original'), stream = response.body;
await Promise.resolve(); await Promise.resolve();
assert.equal(response.bodyUsed, false);
const clone = response.clone(); assert.equal(await clone.text(),'original');
for (const method of ['tee','pipeTo','pipeThrough','values'])
  assert.throws(() => stream[method](), /unsupported:Body\./);
assert.throws(() => new target.Response(stream), /unsupported:body-type/);
assert.throws(() => new target.Request('https://example.test', {method:'POST',body:stream}), /unsupported:body-type/);
const reader=stream.getReader(); await assert.rejects(stream.cancel(),TypeError);
assert.equal(response.bodyUsed,false); reader.releaseLock();
assert.equal(await response.text(),'original');
''')


if __name__ == '__main__':
    unittest.main()
