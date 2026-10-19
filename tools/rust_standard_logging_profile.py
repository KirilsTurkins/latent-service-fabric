"""Exact pinned stdio derivation; source proof alone never selects a sysroot."""
from __future__ import annotations

import hashlib
from tools.dev_workflow.common import require

PROFILE = 'lsf-rust-std-logging-source-v1'
SELECTOR = b'all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "")'
ORIGINALS = {
    'std/src/sys/stdio/mod.rs': 'ffc59c348ecc12e0d4748855309112f13979392983cafb677be6b82fc6e74d59',
    'std/src/sys/stdio/unsupported.rs': '1fd09fcb0a7f21d2b453dcd2447f14ba3cc957cbb489d582a4964e689959d987',
    'std/src/io/stdio.rs': 'e302f4b2fa83f2d703e1d3211368dc01860b4a602765b62238d8303bba357879',
}
RECIPE = ('tools/rust_standard_logging_profile.py', 'sdk/rust-standard-runtime/stdio_closed.rs',
          'sdk/rust-standard-runtime/stdio_logging.rs', 'wit/platform/log/package.wit',
          'sdk/rust-standard-stdio/Cargo.toml', 'sdk/rust-standard-stdio/src/lib.rs')


def overlay(original: dict[str, bytes], pal: bytes):
    require(set(original) == set(ORIGINALS), 'rust-stdio-original-set')
    for name, raw in original.items():
        require(hashlib.sha256(raw).hexdigest() == ORIGINALS[name], 'rust-stdio-original-preimage')
    branch = b'    _ => {\n        mod unsupported;\n        pub use unsupported::*;\n    }'
    source = original['std/src/sys/stdio/mod.rs']
    require(source.count(branch) == 1, 'rust-stdio-selector-preimage')
    selected = b'    ' + SELECTOR + b' => {\n        mod lsf;\n        pub use lsf::*;\n    }\n' + branch
    stdout = original['std/src/io/stdio.rs']
    buffered = b'LineWriter::new(stdout_raw())'
    require(stdout.count(buffered) == 1, 'rust-stdio-buffer-selector-preimage')
    immediate = b'if cfg!(' + SELECTOR + b') { LineWriter::with_capacity(0, stdout_raw()) } else { ' + buffered + b' }'
    return {'std/src/sys/stdio/mod.rs': source.replace(branch, selected, 1),
            'std/src/sys/stdio/lsf.rs': pal,
            'std/src/io/stdio.rs': stdout.replace(buffered, immediate, 1)}


def selected(original: dict[str, bytes], inputs: dict[str, bytes], *, logging=False):
    require(type(logging) is bool, 'rust-stdio-selection-invalid')
    name = 'sdk/rust-standard-runtime/stdio_' + ('logging' if logging else 'closed') + '.rs'
    return overlay({name: original[name] for name in ORIGINALS}, inputs[name])
