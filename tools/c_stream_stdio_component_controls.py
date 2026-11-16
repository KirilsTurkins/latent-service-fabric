"""Build selected C components; no signed node or live provider is used."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, c_capsule_project
from tools.c_guest import standard_facilities, threading
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json


def prepare(project: Path, source: Path) -> Path:
    created = c_capsule_project.create(project, 'greeting', threading_profile=threading.PROFILE,
        runtime_profile=standard_facilities.STREAM_STDIO_PROFILE)
    configuration = json.loads((created / 'capsule-project.json').read_bytes())
    configuration['limits'].update(memoryBytes=32 * 1024 * 1024, wallTimeLimitMillis=5000,
                                   cpuFuel=1_000_000_000, logBytes=4096, outboundRequests=1)
    (created / 'capsule-project.json').write_text(json.dumps(configuration, indent=2) + '\n')
    (created / 'src/main.c').write_bytes(read_file(source, 262144))
    return created


def command(*arguments: str | Path) -> bytes:
    result = subprocess.run(list(map(str, arguments)), capture_output=True, timeout=60, check=False)
    if result.returncode or len(result.stdout) + len(result.stderr) > 4 * 1024 * 1024:
        raise ValueError('c-stream-stdio-component-control-command')
    return result.stdout


def validate_unsupported(output: Path, wasm: Path, core_wat: Path) -> None:
    failed = json.loads((output / 'BUILD-FAILED.json').read_bytes())
    commands = failed.get('commands')
    bad_core = output / 'core-componentization-failed.wasm'
    if (failed.get('stage') != 'compile' or not isinstance(commands, list) or not commands
            or commands[-1].get('stage') != 'wasm-tools' or commands[-1].get('exitCode') != 1
            or not bad_core.is_file() or (output / 'component.wasm').exists()):
        raise ValueError('c-stream-stdio-unsupported-stdin-wrong-failure')
    diagnostic = read_file(output / 'logs' / f'{len(commands)-1:02}-wasm-tools.stderr.txt', 65536)
    if (b'failed to resolve import `wasi_snapshot_preview1::fd_read`' not in diagnostic
            or b'module requires an import interface named `wasi_snapshot_preview1`' not in diagnostic):
        raise ValueError('c-stream-stdio-unsupported-stdin-wrong-diagnostic')
    command(wasm, 'print', bad_core, '-o', core_wat)
    if core_wat.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('c-stream-stdio-unsupported-core-bound')
    text = core_wat.read_text(encoding='utf-8')
    if not re.search(r'^  \(import "wasi_snapshot_preview1" "fd_read" ', text, re.MULTILINE):
        raise ValueError('c-stream-stdio-unsupported-stdin-not-observed')


def run(output: Path, zig: Path, wit: Path, wasm: Path, contracts: Path) -> dict:
    output = fresh(output)
    deadline = time.monotonic() + 600
    supported = ROOT / 'tools/tests/fixtures/c-stream-stdio-component.c'
    unsupported = ROOT / 'tools/tests/fixtures/c-stream-stdio-unsupported.c'
    fixtures = {path.name: hashlib.sha256(read_file(path, 262144)).hexdigest()
                for path in (supported, unsupported)}
    installed = {'zig': zig, 'wit-bindgen': wit, 'wasm-tools': wasm}
    package_url = 'https://github.com/KirilsTurkins/latent-service-fabric'
    project = prepare(output / 'supported-project', supported)
    built = c_capsule_build.build(project, output / 'supported-build', contracts, None,
                                 package_url, installed=installed, _deadline=deadline)
    component = built / 'component.wasm'
    complete = json.loads((built / 'BUILD-COMPLETE.json').read_bytes())
    selection = json.loads((built / 'standard-runtime-selection.json').read_bytes())
    world = command(wasm, 'component', 'wit', component).decode('utf-8')
    imports = re.findall(r'^  import ([^;]+);$', world, re.MULTILINE)
    required = {'latent:runtime/activation@0.1.0', 'latent:runtime-native/threads@0.1.0',
                'latent:network/streams@0.1.0', 'latent:clock/monotonic@0.1.0',
                'latent:clock/wall@0.1.0', 'latent:random/random@0.1.0', 'latent:log/log@0.1.0'}
    if (set(imports) != required or len(imports) != len(required)
            or 'wasi_snapshot_preview1' in world or complete.get('packageAssembled') is not False
            or selection.get('profile') != standard_facilities.STREAM_STDIO_PROFILE
            or selection.get('authority') != 'none'):
        raise ValueError('c-stream-stdio-component-profile-or-authority')
    # The production builder already authenticates the original four-module
    # routing and validates its final component with the selected features.
    core_wat = output / 'unsupported-core.wat'
    bad_project = prepare(output / 'unsupported-project', unsupported)
    bad_output = output / 'unsupported-build'
    try:
        c_capsule_build.build(bad_project, bad_output, contracts, None, package_url,
                              installed=installed, _deadline=deadline)
    except ValueError:
        pass
    else:
        raise ValueError('c-stream-stdio-unsupported-stdin-accepted')
    validate_unsupported(bad_output, wasm, core_wat)
    if fixtures != {path.name: hashlib.sha256(read_file(path, 262144)).hexdigest()
                    for path in (supported, unsupported)}:
        raise ValueError('c-stream-stdio-component-fixture-changed')
    result = {'status': 'passed', 'fixtures': fixtures, 'componentDigest': complete['componentDigest'],
              'imports': imports, 'unsupportedStdin': 'preview1-fd-read-refused-before-component',
              'grantsCreated': False, 'signedComponent': False, 'realProvider': False}
    write_json(output / 'component-controls.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'zig', 'wit-bindgen', 'wasm-tools', 'contracts'):
        parser.add_argument('--' + name, required=True, type=Path)
    options = parser.parse_args()
    print(run(options.output, options.zig, options.wit_bindgen, options.wasm_tools, options.contracts)['status'])
