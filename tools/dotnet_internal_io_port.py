#!/usr/bin/env python3
"""Pair an independently compiled NativeAOT probe with the exact closed I/O port."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment, file_identity
from tools.dotnet_guest.internal_io import prepare
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json


def project(raw: Path, adapter: Path, output: Path):
    output = fresh(output)
    environment = build_environment(output)
    wasm = Path(shutil.which('wasm-tools', path=environment['PATH']) or 'missing-wasm-tools').resolve(strict=True)
    commands = Commands(ROOT, output, environment)
    record = {'status': 'in-progress', 'qualification': 'component-encoding-only', 'signedExecution': 'not-run',
        'original': file_identity(raw, 'original-component', 64*1024*1024),
        'adapter': file_identity(adapter, 'closed-runtime', 64*1024*1024),
        'tool': file_identity(wasm, 'wasm-tools'), 'commandLimits': {'overallSeconds': 900, 'perCommandSeconds': 600}}
    try:
        if commands.run('validator-version', wasm, '--version').split()[:2] != [b'wasm-tools', b'1.254.0']:
            raise ValueError('unreviewed-internal-io-component-validator')
        compiler = SimpleNamespace(commands=commands, wasm=wasm, run=commands.run)
        original = json.loads(commands.run('original-wit', wasm, 'component', 'wit', raw, '--json'))
        selected, port = prepare(compiler, raw, adapter, output/'port', original)
        (output/'component.wasm').write_bytes(read_file(selected, 64*1024*1024))
        if (record['original'] != file_identity(raw, 'original-component', 64*1024*1024)
                or record['adapter'] != file_identity(adapter, 'closed-runtime', 64*1024*1024)
                or record['tool'] != file_identity(wasm, 'wasm-tools')):
            raise ValueError('internal-io-component-input-changed')
        record.update(status='passed', port=port, selected=file_identity(output/'component.wasm', 'selected-component', 64*1024*1024))
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw', required=True, type=Path)
    parser.add_argument('--adapter', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(project(args.raw.resolve(strict=True), args.adapter.resolve(strict=True), args.output.resolve())))
