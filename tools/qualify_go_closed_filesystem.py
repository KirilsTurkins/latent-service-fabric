"""Execute the exact closed adapter and ordinary Go Unsupported API programme."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_suite_inventory as registry
from tools.build_observation import build_environment
from tools.go_closed_filesystem import ADAPTER_CASE, adapter_sources, strict_scratch_result
from tools.phase2_operator_process import require
from tools.qualify_sdk_scratch import qualify as scratch_qualify
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, write_json


def adapter_observations(raw, filtered):
    require(len(raw) <= 2 * 1024 * 1024, 'Go-closed-adapter-output-bound')
    names = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    require(names == [ADAPTER_CASE.encode()] and totals == [(b'1', b'0', b'0', b'0', str(filtered).encode())],
            'Go-closed-adapter-exact-execution-required')
    rows = [json.loads(line) for line in re.findall(rb'^GO_CLOSED_ADAPTER_CASE (.+)$', raw, re.M)]
    expected = [{'pathOpen': code, 'preopen': 8, 'mkdir': 76, 'socket': 76, 'read': 8, 'memoryBytes': 65536}
                for code in [76, 52]]
    require(rows == expected and all(all(type(value) is int for value in row.values()) for row in rows),
            'Go-closed-adapter-old-current-and-unchanged-authority-required')
    return rows


def qualify_adapter(output):
    require(sys.platform == 'linux', 'Go-closed-adapter-Linux-reference-required')
    original, current = adapter_sources()
    output = fresh(output)
    environment = build_environment(output)
    commands = Commands(ROOT, output, environment, deadline_seconds=1100, command_seconds=900)
    record = {'status': 'in-progress', 'sourceSha256': hashlib.sha256(current).hexdigest(),
              'originalSourceSha256': hashlib.sha256(original).hexdigest(), 'commands': commands.records}
    try:
        for label, source in [('old', original), ('current', current)]:
            wat = output / (label + '.wat')
            wasm = output / (label + '.wasm')
            wat.write_bytes(source)
            commands.run(label + '-closed-adapter', 'wasm-tools', 'parse', wat, '-o', wasm)
            require(wasm.stat().st_size <= 65536, 'Go-closed-adapter-binary-bound')
            environment['LSF_GO_CLOSED_ADAPTER_' + label.upper()] = str(wasm)
        suite, = [row for row in registry.load()['suites'] if row['id'] == 'latent-wasmtime.test.generic-backend']
        require(ADAPTER_CASE in suite['expectedCases'] and ADAPTER_CASE in suite['expectedIgnored'],
                'Go-closed-adapter-explicit-suite-required')
        result = commands.run('actual-old-current-adapter', 'cargo', '--config', '.cargo/managed-guest.toml',
            'test', '--locked', '-p', 'latent-wasmtime', '--test', 'generic_backend', ADAPTER_CASE,
            '--', '--ignored', '--exact', '--show-output')
        rows = adapter_observations(result, len(suite['expectedCases']) - 1)
        require(adapter_sources() == (original, current), 'Go-closed-adapter-source-changed')
        record.update(status='passed', cases=rows, hostFilesystemOrProviderInstalled=False,
                      actualComponentQualification=False)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        record['status'] = 'failed'
        write_json(output / 'FAILED.json', record)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--adapter-only', action='store_true')
    parser.add_argument('--native-qualification', type=Path)
    args = parser.parse_args()
    if args.adapter_only:
        require(args.native_qualification is None, 'Go-closed-adapter-no-native-input')
        qualify_adapter(args.output)
    else:
        require(args.native_qualification is not None, 'Go-scratch-original-normal-required')
        result = scratch_qualify('go', args.output, args.native_qualification)
        summary = strict_scratch_result(result)
        write_json(args.output / 'go-unsupported-results.json', summary)
    print('Exact closed Go filesystem reference passed; scratch storage remains unsupported')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
