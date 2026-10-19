"""Bounded actual PAL host reference with an authenticated old-source RED.

The fake bridge does not qualify generated bindings, rebuilt std or a component.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import rust_standard_logging_profile as profile
from tools.build_observation import build_environment, file_identity
from tools.build_process import run_bounded_result
from tools.dev_workflow.common import require
from tools.rust_capsule_project import ROOT, checked_path, digest, fresh, inventory, read_file, write_json


def original_methods(raw: bytes) -> bytes:
    # Only these exact authenticated, brace-flat upstream methods are selected.
    # Their arguments and bodies are unchanged; unstable unrelated std-internal
    # traits are not copied into the separate stable host reference.
    profile.overlay({name: read_file(ROOT / 'sdk/rust-standard-runtime/upstream' / name)
                     for name in profile.ORIGINALS}, b'reference-only')
    require(digest(raw) == 'sha256:' + profile.ORIGINALS['std/src/sys/stdio/unsupported.rs'],
            'rust-stdio-reference-original-preimage')
    signatures = (b'fn write(&mut self, buf: &[u8]) -> io::Result<usize>',
                  b'fn write_all(&mut self, _buf: &[u8]) -> io::Result<()>',
                  b'fn flush(&mut self) -> io::Result<()>')
    selected = []
    for signature in signatures:
        require(raw.count(signature) == 1, 'rust-stdio-reference-method-preimage')
        start = raw.index(signature); end = raw.index(b'\n    }', start) + len(b'\n    }')
        method = raw[start:end]
        require(method.count(b'{') == method.count(b'}') == 1, 'rust-stdio-reference-method-shape')
        selected.append(method)
    return b'\n'.join(selected)


def run(rustc: Path, output: Path):
    rustc, output = checked_path(rustc), fresh(output)
    names = ('sdk/rust-standard-runtime/stdio_reference.rs', 'sdk/rust-standard-runtime/stdio_closed.rs',
             'sdk/rust-standard-runtime/stdio_logging.rs', 'tools/run_rust_stdio_reference.py',
             'sdk/rust-standard-runtime/upstream/std/src/sys/stdio/unsupported.rs')
    source = {name: read_file(ROOT / name) for name in names}
    compiler = file_identity(rustc, 'rustc')
    environment = build_environment(output)
    def command(arguments, expected=0):
        result = run_bounded_result(list(map(str, arguments)), output, environment, 30, 65536)
        require(result.returncode == expected, 'rust-stdio-reference-command-outcome')
        return (result.stdout + result.stderr).decode('utf-8')
    version = command([rustc, '--version', '--verbose'])
    from tools import rust_standard_clock_profile as clock
    require('release: ' + clock.RUST + '\n' in version and 'commit-hash: ' + clock.RUST_COMMIT + '\n' in version,
            'rust-stdio-reference-compiler-pin')
    for name in names[:3]:
        (output / Path(name).name).write_bytes(source[name])
    new_binary, old_binary = output / 'new-reference.exe', output / 'old-reference.exe'
    command([rustc, '--edition=2024', '--test', output / 'stdio_reference.rs', '-o', new_binary])
    new_output = command([new_binary, '--test-threads=1'])
    old_source = b'use std::io::{self, Write, ErrorKind};\nstruct Stdout;\nimpl io::Write for Stdout {\n'
    old_source += original_methods(source[names[-1]]) + b'\n}\n'
    for name, call in (('write', 'write(b"outside")'), ('write_all', 'write_all(b"outside")'), ('flush', 'flush()')):
        old_source += ('#[test]\nfn old_' + name + '_must_be_unsupported() { assert_eq!(Stdout.' + call +
                       '.unwrap_err().kind(), ErrorKind::Unsupported); }\n').encode()
    (output / 'old.rs').write_bytes(old_source)
    command([rustc, '--edition=2024', '--test', output / 'old.rs', '-o', old_binary])
    old_output = command([old_binary, '--test-threads=1'], 101)
    require('3 failed' in old_output and '7 passed' in new_output and '0 ignored' in new_output,
            'rust-stdio-reference-case-inventory')
    require({n: read_file(ROOT / n) for n in names} == source and file_identity(rustc, 'rustc') == compiler,
            'rust-stdio-reference-input-mutated')
    value = {'schemaVersion': 'latent.rust.stdio-host-reference.v1', 'status': 'passed',
        'oldSource': {'digest': digest(source[names[-1]]), 'result': '3 intended Unsupported assertions failed'},
        'newSource': {'result': '7 actual PAL tests passed; zero ignored', 'fakeTypedLogSink': True},
        'sourceDigest': digest(inventory(source)), 'compiler': compiler,
        'rebuiltStdQualified': False, 'generatedBindingQualified': False, 'signedComponentQualified': False}
    write_json(output / 'qualification.json', value)
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rustc', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.rustc, args.output)))
    return 0


if __name__ == '__main__': raise SystemExit(main())
