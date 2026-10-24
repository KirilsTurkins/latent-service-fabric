"""Explicit v7 single-stack ceiling; no new allocator, owner or byte refund.

Authenticate the complete pinned Go source before deriving three allocation
guards. The original stack pools, GC roots/copy/shrink/free and old+new transient
ownership remain intact inside the original limited Wasm Store.
"""
import hashlib

from tools.go_guest.runtime import checked_sources, replace_once

PROFILE = 'go-component-activation-v7'
MAXIMUM_STACK_BYTES = 1_048_576
BRIDGE_SHA256 = 'bb058dd4008270d002ae27f55178c53ac56e6875f515408a1bace2e3545e7362'
PREIMAGES = {
    'runtime/stack.go': '0225942ade2eed1e4ec5a0e813c66b3ed06c142c33c987b2fd9e031a0b871d3d',
}


def stack_source(text: str) -> str:
    if hashlib.sha256(text.encode('utf-8')).hexdigest() != PREIMAGES['runtime/stack.go']:
        raise ValueError('go-runtime-source-drift:runtime/stack.go')
    text = replace_once(text,
        '\tif n&(n-1) != 0 {\n\t\tthrow("stack size not a power of 2")\n\t}\n',
        '\tif n&(n-1) != 0 {\n\t\tthrow("stack size not a power of 2")\n\t}\n'
        '\tif uintptr(n) > lsfMaximumStackBytes { lsfStackLimitExceeded() }\n')
    # Guard before both the GC delta and uint32 narrowing, including direct
    # GC-forced copies. No original stack is freed when this refuses.
    text = replace_once(text,
        'func copystack(gp *g, newsize uintptr) {\n',
        'func copystack(gp *g, newsize uintptr) {\n'
        '\tif newsize > lsfMaximumStackBytes { lsfStackLimitExceeded() }\n')
    text = replace_once(text,
        '\tif newsize > maxstacksize || newsize > maxstackceiling {\n',
        '\tif newsize > lsfMaximumStackBytes { lsfStackLimitExceeded() }\n'
        '\tif newsize > maxstacksize || newsize > maxstackceiling {\n')
    return text


def runtime_sources(goroot, sources, sdk):
    original = checked_sources(goroot, PREIMAGES)['runtime/stack.go']
    bridge = (sdk / 'runtime/stack_bridge.go.in').read_bytes()
    if hashlib.sha256(bridge).hexdigest() != BRIDGE_SHA256:
        raise ValueError('go-bounded-stack-bridge-source-drift')
    sources['runtime/stack.go'] = stack_source(original)
    sources['runtime/os_wasip1.go'] += '\n' + bridge.decode('utf-8')
