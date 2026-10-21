"""Private closed Trap enum and numeric frames; never production qualification."""
from pathlib import Path
import json
from tools import diagnose_go_entry_frames as frames
from tools.phase2_operator_process import require
from tools.rust_capsule_project import digest,read_file

PREFIX=b'LSF_JAVA_RESOURCE_TRAP '
PREIMAGES={'crates/latent-wasmtime/src/containment.rs': 'sha256:a671571e7983a77bb5041478e5b30fea9a09cc31791ec3a6ec9d3bb15985e0aa', 'crates/latent-wasmtime/src/config/engine.rs': 'sha256:844246d9b18864cf5c6d0b2ca43bab375eeaadf50f8b3100824f5aad00f6acc5'}

VARIANTS = (
    'cannot-enter-component', 'cannot-leave-component', 'cannot-block-sync-task',
    'no-async-result', 'async-deadlock', 'uncaught-exception', 'invalid-char',
    'string-out-of-bounds', 'list-out-of-bounds', 'invalid-discriminant',
    'unaligned-pointer', 'debug-string-encoding', 'debug-code-units',
    'debug-pointer-aligned', 'debug-upper-bits', 'unreachable-code',
    'memory-out-of-bounds', 'other-known-trap', 'not-a-wasmtime-trap',
)

TRAP_MATCH = '''
    let private_variant = match error.downcast_ref::<wasmtime::Trap>() {
        Some(wasmtime::Trap::CannotEnterComponent) => "cannot-enter-component",
        Some(wasmtime::Trap::CannotLeaveComponent) => "cannot-leave-component",
        Some(wasmtime::Trap::CannotBlockSyncTask) => "cannot-block-sync-task",
        Some(wasmtime::Trap::NoAsyncResult) => "no-async-result",
        Some(wasmtime::Trap::AsyncDeadlock) => "async-deadlock",
        Some(wasmtime::Trap::UncaughtException) => "uncaught-exception",
        Some(wasmtime::Trap::InvalidChar) => "invalid-char",
        Some(wasmtime::Trap::StringOutOfBounds) => "string-out-of-bounds",
        Some(wasmtime::Trap::ListOutOfBounds) => "list-out-of-bounds",
        Some(wasmtime::Trap::InvalidDiscriminant) => "invalid-discriminant",
        Some(wasmtime::Trap::UnalignedPointer) => "unaligned-pointer",
        Some(wasmtime::Trap::DebugAssertStringEncodingFinished) => "debug-string-encoding",
        Some(wasmtime::Trap::DebugAssertEqualCodeUnits) => "debug-code-units",
        Some(wasmtime::Trap::DebugAssertPointerAligned) => "debug-pointer-aligned",
        Some(wasmtime::Trap::DebugAssertUpperBitsUnset) => "debug-upper-bits",
        Some(wasmtime::Trap::UnreachableCodeReached) => "unreachable-code",
        Some(wasmtime::Trap::MemoryOutOfBounds) => "memory-out-of-bounds",
        Some(_) => "other-known-trap",
        None => "not-a-wasmtime-trap",
    };
'''

def overlay_sources(root: Path, output: Path):
    require(all(digest(read_file(root / name)) == expected for name, expected in PREIMAGES.items()),
            'java-resource-private-host-original-preimage')
    sources, overlays = frames.overlay_sources(root, output)
    path = overlays[0][0]
    text = read_file(path).decode()
    require(text.count(frames.OBSERVER) == 1, 'java-resource-private-frame-observer-preimage')
    observer = TRAP_MATCH + frames.OBSERVER.replace(frames.PREFIX.decode().strip(), PREFIX.decode().strip())
    observer = observer.replace('"available": true,', '"trapVariant": private_variant, "available": true,', 1)
    observer = observer.replace('"available": false,', '"trapVariant": private_variant, "available": false,', 1)
    path.write_bytes(text.replace(frames.OBSERVER, observer, 1).encode())
    sources[frames.PATHS[0]]['private'] = digest(read_file(path))
    return sources, overlays

def capture(data: bytes):
    require(type(data) is bytes and len(data) <= 262144, 'java-resource-private-stderr-bound')
    rows = [line[len(PREFIX):] for line in data.splitlines() if line.startswith(PREFIX)]
    require(len(rows) <= 16, 'java-resource-private-record-bound')
    result, remaining = [], 32
    for row in rows:
        require(len(row) <= 8192, 'java-resource-private-record-size')
        value = json.loads(row)
        require(isinstance(value, dict) and set(value) == {'trapVariant', 'available', 'truncated', 'frames'}
                and value['trapVariant'] in VARIANTS, 'java-resource-private-closed-trap-variant')
        variant = value.pop('trapVariant')
        # Reuse the already reviewed exact numeric-frame validator. Neither a
        # symbol, arbitrary error text nor the surrounding stderr is retained.
        numeric = frames.numeric_frames(frames.PREFIX + json.dumps(value).encode() + b'\n')
        count = len(numeric['frames'])
        result.append({'trapVariant': variant, **numeric, 'frames': numeric['frames'][:remaining],
                       'truncated': numeric['truncated'] or count > remaining})
        remaining -= min(remaining, count)
    return {'status': 'observed' if rows else 'absent', 'records': result,
            'rawNodeOutputRetained': False, 'qualification': False, 'numericFrameLimit': 32}
