"""Execute the actual Rust-emitted guard on tiny encoded engine controls.

This is not an original Rust allocator, captured application, canonical host,
signed component or runtime qualification. The owning hosted programme builds
the exact context executable once and retains every input/output and refusal.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from tools import rust_thread_callback_paths as wasm
from tools import rust_thread_object_graph as graph
from tools.rust_capsule_project import digest, read_file, write_json
from tools.dev_workflow.common import require

PUBLIC = 'examples:guard/control@1.0.0#run'
POST = 'cabi_post_' + PUBLIC
RECIPE = ('tools/rust_thread_guard_controls.py', 'tools/rust_thread_callback_paths.py',
          'tools/rust_thread_object_graph.py')


def fixture() -> bytes:
    u, s, section = wasm.unsigned, wasm.signed, wasm.section

    def name(value):
        raw = value.encode()
        return u(len(raw)) + raw

    def constant(value):
        return b'\x41' + s(value)

    def store(address, value, byte=False):
        return constant(address) + constant(value) + (b'\x3a\0\0' if byte else b'\x36\x02\0')

    def mode(value, instructions):
        return b'\x23\x02' + constant(value) + b'\x46\x04\x40' + instructions + b'\x0b'

    types = [((), (0x7f,)), ((0x7f,), ()), ((0x7f, 0x7f), (0x7f,)),
             ((0x7e, 0x7e, 0x7f), ()), ((0x7f,) * 4, (0x7f,)), ((0x7f,) * 3, ())]
    ty = section(1, u(len(types)) + b''.join(wasm._function_type(t) for t in types))
    imports = [("$root", '[context-get-1]', 0), ("$root", '[context-set-1]', 1),
               ("$root", '[thread-new-indirect-v0]', 2),
               ('latent:runtime-native/threads@0.1.0', 'start', 3)]
    imported = section(2, u(len(imports)) + b''.join(name(m) + name(n) + b'\0' + u(t)
                                                   for m, n, t in imports))
    functions = section(3, b'\x0b\x01\0\x02\x01\x01\x01\x04\x01\x05\x01\0')
    table = section(4, b'\x01\x70\x01\x01\x01')
    memory = section(5, b'\x01\x01\x04\x04')
    globals_ = section(6, b'\x03\x7f\x01' + constant(196608) + b'\x0b\x7f\0' +
                       constant(65536) + b'\x0b\x7f\x01\x41\0\x0b')
    exports = [('__stack_pointer', 3, 0), ('__stack_low', 3, 1),
               ('__indirect_function_table', 1, 0), ('memory', 2, 0),
               ('__lsf_rust_owned_thread_entry', 0, 4), (PUBLIC, 0, 5),
               ('__lsf_rust_root_bootstrap', 0, 6), ('__lsf_rust_root_finish', 0, 7),
               ('__lsf_rust_root_reap', 0, 8), (POST, 0, 9), ('cabi_realloc', 0, 10),
               ('set-mode', 0, 11), ('hook-count', 0, 14)]
    exported = section(7, u(len(exports)) + b''.join(name(n) + bytes([k]) + u(i)
                                                  for n, k, i in exports))
    elements = section(9, b'\x01\0\x41\0\x0b\x01\x04')
    public = b'\0\x23\0\x1a' + store(512, 0, True) + store(516, 196608) + store(520, 8)
    public += mode(4, store(516, 1) + store(520, 0))  # Valid empty sentinel.
    public += mode(5, store(516, -16) + store(520, 32))  # u32 overflow.
    public += mode(6, store(516, 65536))  # Nonempty original Root stack.
    public += mode(7, store(516, 131080))  # Nonempty original System stack.
    public += mode(8, store(516, 262144))  # Past actual physical memory.
    public += mode(9, store(512, 2, True))  # Invalid WIT result tag.
    panic = constant(0) * 3 + b'\x10\x0c'
    public += mode(11, panic)  # Ordinary Root panic must retain its hook path.
    public += constant(512) + b'\x0b'
    boot = (b'\0' + constant(1024) + b'\x20\x01\x36\x02\0' +
            constant(1028) + b'\x20\0\x36\x02\0' +
            constant(1032) + b'\x20\x01\x36\x02\0' + store(1036, 1) + constant(1024) + b'\x0b')
    finish = (b'\0' + mode(1, store(512, 1, True)) + mode(2, store(516, 196616)) +
              mode(3, store(520, 7)) + store(1036, 4) + b'\x0b')
    bodies = [b'\0\x0b', public, boot, finish, b'\0\x0b',
              b'\0\x20\0\x1a\x0b',
              b'\0' + mode(10, panic) + b'\x20\x03\x0b',
              b'\0\x20\0\x24\x02\x0b',
              b'\0\x20\0\x10\x0d\0\x0b',  # Panic entry calls the original hook.
              b'\0' + store(28, 1) + b'\x10\0\x1a\0\x0b',  # Hook uses context; forbidden in System.
              b'\0' + constant(28) + b'\x28\x02\0\x0b']
    code = section(10, u(len(bodies)) + b''.join(u(len(body)) + body for body in bodies))
    return b'\0asm\1\0\0\0' + ty + imported + functions + table + memory + globals_ + exported + elements + code


SCRIPT = r"""
const fs = require('fs');
const raw = fs.readFileSync(process.argv[2]);
const module_ = new WebAssembly.Module(raw);
const outcomes = [];
for (let mode = 0; mode < 12; ++mode) {
  let context = 0;
  let contextGets = 0;
  const forbidden = () => { throw new Error('unexpected thread/native operation'); };
  const instance = new WebAssembly.Instance(module_, {
    '$root': {'[context-get-1]': () => {++contextGets;return context;}, '[context-set-1]': value => {context=value;},
              '[thread-new-indirect-v0]': forbidden},
    'latent:runtime-native/threads@0.1.0': {'start': forbidden}
  }).exports;
  instance['set-mode'](mode);
  let trapped = false;
  try {
    if (mode === 10) instance.cabi_realloc(0,0,1,8);
    else {
      if (instance['examples:guard/control@1.0.0#run']() !== 512) throw new Error('wrong retarea');
      instance['cabi_post_examples:guard/control@1.0.0#run'](512);
      if (context !== 0) throw new Error('context retained after legal cleanup');
    }
  } catch (e) { if (!(e instanceof WebAssembly.RuntimeError)) throw e; trapped = true; }
  if (trapped !== (mode !== 0 && mode !== 4)) throw new Error('guard mode mismatch:'+mode);
  if (mode === 10 && (instance['hook-count']() !== 0 || contextGets !== 0 || context !== 0))
    throw new Error('System panic entered original hook/context');
  if (mode === 11 && (instance['hook-count']() !== 1 || context === 0))
    throw new Error('normal Root panic hook changed');
  outcomes.push({mode, trapped});
}
console.log(JSON.stringify({node:process.versions.node, outcomes}));
"""


DISPATCH_SCRIPT = r"""
const fs = require('fs');
const instance = new WebAssembly.Instance(new WebAssembly.Module(fs.readFileSync(process.argv[2]))).exports;
const cases = [['strict',0,107],['strict',1,null],['release',0,107],
               ['release',1,17],['ordinary',0,null],['ordinary',1,17]];
const outcomes = [];
for (const [method,pointer,expected] of cases) {
  let value=null, trapped=false;
  try { value=instance[method](7,pointer); }
  catch(e) {if (!(e instanceof WebAssembly.RuntimeError)) throw e;trapped=true;}
  if (trapped!==(expected===null) || value!==expected) throw new Error('dispatch mismatch:'+method+':'+pointer);
  outcomes.push({method,pointer,value,trapped});
}
console.log(JSON.stringify({node:process.versions.node,outcomes}));
"""


def run(commands, tool: Path, output: Path) -> dict:
    output.mkdir(exist_ok=False)
    source, script = output / 'original-control.wasm', output / 'engine-controls.cjs'
    source.write_bytes(fixture())
    script.write_text(SCRIPT, encoding='utf-8', newline='\n')
    _, imports, bodies = graph.code(read_file(source))
    commands.run('guard-control-actual-context-derivation', tool, '--guarded-ordinary-core-panic',
                 source, digest(read_file(source)), PUBLIC, POST, 'cabi_realloc',
                 '512', '196608', '12', digest(bodies[12 - len(imports)]), output / 'derived')
    node = shutil.which('node', path=commands.environment.get('PATH'))
    require(node is not None, 'rust-guard-controls-node-unavailable')
    raw = commands.run('guard-control-emitted-wrapper-engine', node, script, output / 'derived/core.wasm')
    require(len(raw) <= 8192, 'rust-guard-controls-output-bound')
    result = json.loads(raw)
    require(result.get('node') == '24.19.0' and result.get('outcomes') ==
            [{'mode': value, 'trapped': value not in (0, 4)} for value in range(12)],
            'rust-guard-controls-exact-engine-outcomes')
    dispatch, dispatch_script = output / 'private-dispatch.wasm', output / 'private-dispatch.cjs'
    commands.run('private-dispatch-actual-native-emission', tool,
                 '--emit-private-dispatch-controls', dispatch)
    dispatch_script.write_text(DISPATCH_SCRIPT, encoding='utf-8', newline='\n')
    dispatch_raw = commands.run('private-dispatch-emitted-helper-engine', node, dispatch_script, dispatch)
    require(len(dispatch_raw) <= 8192, 'rust-dispatch-controls-output-bound')
    dispatch_result = json.loads(dispatch_raw)
    require(dispatch_result.get('node') == '24.19.0' and dispatch_result.get('outcomes') == [
        {'method': method, 'pointer': pointer, 'value': value, 'trapped': value is None}
        for method, pointer, value in [('strict', 0, 107), ('strict', 1, None),
            ('release', 0, 107), ('release', 1, 17), ('ordinary', 0, None), ('ordinary', 1, 17)]],
        'rust-dispatch-controls-exact-engine-outcomes')
    receipt = json.loads(read_file(output / 'derived/receipt.json'))
    require(receipt['canonicalResultGuardInstalled'] is True
            and receipt['canonicalStaticResultArea'] == 512
            and receipt['canonicalSystemPanicOriginalFunction'] == 12
            and receipt['canonicalSystemPanicTrapFunction'] == 12
            and receipt['canonicalResultAreaAuthenticated'] is False
            and receipt['privateExecutorGraphAuthenticated'] is False
            and receipt['standardRuntimeQualified'] is False,
            'rust-guard-controls-source-scope')
    record = {'schemaVersion': 'latent.rust.emitted-result-guard-controls.v1',
              'originalDigest': digest(read_file(source)),
              'emittedDigest': digest(read_file(output / 'derived/core.wasm')),
              'engine': result, 'privateDispatchEngine': dispatch_result,
              'actualCapturedRustGuestExecuted': False,
              'canonicalHostQualified': False, 'ordinaryThreadPoolQualified': False}
    write_json(output / 'engine-result.json', record)
    return record
