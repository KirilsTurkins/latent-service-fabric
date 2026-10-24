"""Finite Node reference controls; no compiler, engine or signed qualification."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from tools.typescript_guest import buffer_profile

ROOT = Path(__file__).resolve().parents[2]


class TypeScriptNodeBuffer(unittest.TestCase):
    def javascript(self, code):
        node = shutil.which('node')
        self.assertIsNotNone(node, 'Node is required for actual reference controls')
        prefix = "import assert from 'node:assert/strict';import {Buffer as N} from 'node:buffer';\n"
        prefix += f"import {{Buffer as B, kMaxLength as MAX, kStringMaxLength as STR}} from {json.dumps((ROOT/buffer_profile.BACKEND).as_uri())};\n"
        result = subprocess.run([node, '--input-type=module', '-e', prefix + code],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_copy_views_subarray_slice_and_overlap_match_native(self):
        self.javascript(r"""
function scenario(C) {
 const backing=new ArrayBuffer(12), shared=C.from(backing,2,6);shared.set([1,2,3,4,5,6]);
 const copied=C.from(shared), view=shared.slice(-4,-1), other=shared.subarray(1,4);
 view[0]=77;other[0]=88;const moved=shared.copy(shared,1,0,5);
 const target=C.alloc(3);const count=copied.copy(target,0,2,100);
 return [[...shared],[...copied],[...target],moved,count,shared.buffer===backing,
         view.buffer===backing,other.buffer===backing,C.isBuffer(view),C.isBuffer(C.from(new Uint16Array([0x1234,0x5678]))),[...C.from(new Uint16Array([0x1234,0x5678]))]];
}
assert.deepEqual(scenario(B),scenario(N));
assert.equal(B.isBuffer(Object.create(B.prototype)),false);
assert.equal(B.isBuffer(new Uint8Array(2)),false);
assert.equal(B.isBuffer(B.from([1,2])),true);
assert.deepEqual([...B.from({type:'Buffer',data:[-1,256,3]})],[255,0,3]);
for(const C of [B,N])assert.equal(C.alloc(1.9).length,1);
function coercions(C){const shared=C.from(new ArrayBuffer(8),1.9,2.9),target=C.alloc(4);return [shared.byteOffset,shared.length,C.from(new ArrayBuffer(8),-0.5).byteOffset,C.from(new ArrayBuffer(8),'2','3').length,C.from([1,2,3]).copy(target,0.5,0.8,2.9),[...target]];}
assert.deepEqual(coercions(B),coercions(N));
""")

    def test_text_hex_base64_and_invalid_utf8_match_native(self):
        self.javascript(r"""
for(const enc of ['utf8','utf-8','ascii','latin1','binary','utf16le','ucs2','base64','base64url','hex']) {
 for(const text of ['', 'Aé😀\ud800Z', 'YW-J_j==\n', 'ff10zz20', 'fı', 'ŔQ==']) {
  assert.deepEqual([...B.from(text,enc)],[...N.from(text,enc)],`from ${enc}/${text}`);
  assert.equal(B.byteLength(text,enc),N.byteLength(text,enc),`length ${enc}/${text}`);
 }
}
for(const raw of [[239,187,191,65],[240,159,152,128,255],[237,160,128],[65,0,0,216,1]]) {
 for(const enc of ['utf8','ascii','latin1','utf16le','hex','base64','base64url'])
  assert.equal(B.from(raw).toString(enc),N.from(raw).toString(enc),`string ${enc}`);
}
for(const name of ['utf8','HEX','base64url','ucs-2','bogus','',null])assert.equal(B.isEncoding(name),N.isEncoding(name));
""")

    def test_truncated_write_fill_compare_and_concat_match_native(self):
        self.javascript(r"""
function scenario(C) {
 const results=[];
 for(const length of [0,1,2,3,4,5]) {
  const value=C.alloc(8,0xaa);results.push(value.write('é😀Z',1,length,'utf8'),[...value]);
 }
 for(const enc of ['utf16le','hex','base64','latin1']) {
  const value=C.alloc(9);results.push(value.write('aabbcc',2,5,enc),[...value]);
 }
 const filled=C.from([1,2,3,4,5]);filled.fill(filled.subarray(0,2),1,5);
 results.push([...filled],C.alloc(5,'é').toString('hex'),C.alloc(3,'').toJSON());
 results.push(C.compare(C.from([1,2]),C.from([1,2,0])), C.from([1,2,3]).compare(C.from([0,2,3]),1,3,1,3));
 results.push([...C.concat([C.from([1,2]),C.from([3,4])],3)],[...C.concat([C.from([1])],4)]);
 return results;
}
assert.deepEqual(scenario(B),scenario(N));
""")

    def test_fixed_variable_and_big_integer_values_match_native(self):
        self.javascript(r"""
const names=['UInt8','Int8','UInt16LE','UInt16BE','Int16LE','Int16BE','UInt32LE','UInt32BE','Int32LE','Int32BE'];
for(const name of names)for(const value of [0,1,name.startsWith('Int')?-1:127]) {
 const b=B.alloc(12),n=N.alloc(12);assert.equal(b['write'+name](value,2),n['write'+name](value,2));
 assert.deepEqual([...b],[...n]);assert.equal(b['read'+name](2),n['read'+name](2));
}
for(const name of ['UIntLE','UIntBE','IntLE','IntBE'])for(const width of [1,3,6]) {
 const value=name.startsWith('Int')?-37:2**(width*8)-1,b=B.alloc(10),n=N.alloc(10);
 assert.equal(b['write'+name](value,1,width),n['write'+name](value,1,width));
 assert.deepEqual([...b],[...n]);assert.equal(b['read'+name](1,width),n['read'+name](1,width));
}
for(const name of ['BigUInt64LE','BigUInt64BE','BigInt64LE','BigInt64BE']) {
 const value=name.startsWith('BigInt')?-(1n<<63n):(1n<<64n)-1n,b=B.alloc(10),n=N.alloc(10);
 assert.equal(b['write'+name](value,1),n['write'+name](value,1));assert.deepEqual([...b],[...n]);assert.equal(b['read'+name](1),n['read'+name](1));
}
for(const value of [NaN,1.9,'12']) {const b=B.alloc(4),n=N.alloc(4);assert.equal(b.writeUInt16BE(value),n.writeUInt16BE(value));assert.deepEqual([...b],[...n]);}
assert.equal(B.prototype.readUint32LE,B.prototype.readUInt32LE);
assert.equal(B.prototype.writeBigUint64BE,B.prototype.writeBigUInt64BE);
""")

    def test_range_and_real_zero_filled_allocation_profile(self):
        self.javascript(r"""
const sameFailure=fn=>{let a,b;try{fn(B);}catch(e){a=[e.name,e.code];}try{fn(N);}catch(e){b=[e.name,e.code];}assert.deepEqual(a,b);assert(a);};
for(const fn of [C=>C.alloc(-1),C=>C.alloc('1'),C=>C.from([1]).readUInt16LE(),
 C=>C.alloc(4).readUInt32LE(1),C=>C.alloc(4).readInt8(-1),C=>C.alloc(2).writeUInt8(256),
 C=>C.alloc(2).writeInt8(-129),C=>C.alloc(8).writeBigUInt64LE(-1n),C=>C.alloc(8).writeBigInt64BE(1n<<63n),
 C=>C.alloc(8).readUIntLE(0,7),C=>C.alloc(4).writeUInt16BE(1,0.5)])sameFailure(fn);
assert.deepEqual([...B.allocUnsafe(4)],[0,0,0,0]);assert.deepEqual([...B.allocUnsafeSlow(3)],[0,0,0]);
for(const fn of [()=>B.alloc(MAX+1),()=>new B(MAX+1),()=>B.from(new ArrayBuffer(8),-1),
 ()=>B.from(new ArrayBuffer(8),7,2),()=>B.from('a','made-up'),()=>B.alloc(1).readFloatLE(),
 ()=>B.alloc(1).includes(0)])assert.throws(fn);
let encodes=0;const Original=globalThis.TextEncoder;
globalThis.TextEncoder=class {constructor(){encodes++;throw Error('must not allocate codec');}};
try{assert.throws(()=>B.from('€'.repeat(Math.floor(MAX/3)+1)),RangeError);assert.equal(encodes,0);
 assert.throws(()=>B.from('x'.repeat(STR+1)),RangeError);assert.equal(encodes,0);}
finally{globalThis.TextEncoder=Original;}
""")

    def test_real_compiler_resolver_alias_identity_and_other_modules_are_unselected(self):
        self.javascript(f"""
import {{bufferBuiltin,BUFFER_PROFILE}} from {json.dumps((ROOT/buffer_profile.RESOLVER).as_uri())};
import {{readFile}} from 'node:fs/promises';
const source=await readFile(new URL({json.dumps((ROOT/buffer_profile.BACKEND).as_uri())}),'utf8');
const resolver=bufferBuiltin(source);assert.deepEqual(resolver.selection(),[]);
assert.equal(resolver.resolve('node:net'),undefined);assert.equal(resolver.resolve('events'),undefined);
const bare=resolver.resolve('buffer'),named=resolver.resolve('node:buffer');assert.deepEqual(bare,named);
assert.deepEqual(resolver.load(bare),{{contents:source,loader:'js'}});assert.deepEqual(resolver.selection(),['node:buffer']);
assert.equal(BUFFER_PROFILE,'lsf-node-buffer-v1');assert.throws(()=>resolver.load({{...bare,path:'caller-chosen'}}));
assert.equal(globalThis.Buffer,N);assert.notEqual(B,N);
""")

    def test_selected_materials_and_profile_refuse_forged_backend(self):
        from tools.typescript_guest.build import RECIPE
        for name in (buffer_profile.BACKEND, buffer_profile.RESOLVER,
                     buffer_profile.DECLARATION, 'tools/typescript_guest/buffer_profile.py'):
            self.assertIn(name, RECIPE)
        digest = 'sha256:' + hashlib.sha256((ROOT/buffer_profile.BACKEND).read_bytes()).hexdigest()
        observed = dict(standardBufferProfile=buffer_profile.PROFILE,
                        standardBufferModules=['node:buffer'], standardBufferBackendDigest=digest)
        value = buffer_profile.check_selection(observed, digest)
        self.assertEqual(value['authority'], 'none')
        self.assertFalse(value['globalBufferInstalled'])
        self.assertIsNone(buffer_profile.check_selection({}, digest))
        for changed in (dict(observed, standardBufferProfile='forged'),
                        dict(observed, standardBufferModules=['buffer', 'node:buffer']),
                        dict(observed, standardBufferBackendDigest='sha256:' + '0' * 64),
                        {'standardBufferProfile': buffer_profile.PROFILE},
                        {'standardBufferModules': None}):
            with self.assertRaises(ValueError):
                buffer_profile.check_selection(changed, digest)

    def test_unselected_legacy_capture_does_not_require_new_buffer_declaration(self):
        import tempfile
        expected = (ROOT/buffer_profile.DECLARATION).read_bytes()
        selection = {'profile': buffer_profile.PROFILE}
        with tempfile.TemporaryDirectory() as temporary:
            captured = Path(temporary)/'buffer.d.ts'
            reads = []

            def read_captured():
                reads.append(True)
                return captured.read_bytes()

            buffer_profile.verify_captured_declaration(None, expected, read_captured)
            self.assertEqual(reads, [], 'an unselected legacy project must not read a new SDK file')
            with self.assertRaises(FileNotFoundError):
                buffer_profile.verify_captured_declaration(selection, expected, read_captured)
            captured.write_bytes(expected)
            buffer_profile.verify_captured_declaration(selection, expected, read_captured)
            captured.write_bytes(expected + b'// stale capture\n')
            with self.assertRaisesRegex(ValueError, 'captured TypeScript buffer declarations differ'):
                buffer_profile.verify_captured_declaration(selection, expected, read_captured)
            captured.unlink()
            buffer_profile.verify_captured_declaration(None, expected, read_captured)
            self.assertEqual(len(reads), 3)


if __name__ == '__main__':
    unittest.main()
