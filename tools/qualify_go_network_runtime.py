#!/usr/bin/env python3
"""One freshly compiled ordinary Go TCP fixture in a targeted signed test harness.

The provider is the explicit logical-reference development installation. Neither
its user-space idle counters nor peer FIN/RST certify final kernel retirement.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_rust_artifacts as artifacts
from tools import ci_suite_discovery as discovery
from tools import ci_suite_inventory as registry
from tools.go_capsule_build import RECIPE as BUILD_RECIPE
from tools.go_guest.activation import MANAGED_PROFILE
from tools.go_guest.compiler import Compiler
from tools.owned_test_process import ProcessFailure, run_owned
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot
from tools.stage_runtime_wit import stage
from tools.test_run import redact

CASE = 'signed_ordinary_go_declared_tcp_preserves_refusals_io_and_cancelled_owner_retirement'
SUITE = 'latent-wasmtime.test.go_outbound_streams'
EXPECTED = (
    ('unsupported-network', 0, 'unsupported-network', 0),
    ('standalone-dns', 1, 'unsupported-standalone-dns', 0),
    ('pre-cancelled', 2, 'cancelled-before-connect', 0),
    ('expired', 3, 'expired-before-connect', 0),
    ('resolver-replaced', 5, 'unsupported-custom-default-resolver', 0),
    ('resolver-prefer-go', 6, 'unsupported-custom-default-resolver', 0),
    ('resolver-strict', 7, 'unsupported-custom-default-resolver', 0),
    ('resolver-dial', 8, 'unsupported-custom-default-resolver', 0),
    ('ordinary-tcp', 4, 'ordinary-tcp-exchange', 1),
    ('half-close-eof', 9, 'ordinary-half-close-eof', 1),
    ('cancel-pending-read', 4, 'cancelled', 1),
    ('fresh-after-cancel', 4, 'ordinary-tcp-exchange', 1),
)


def encoded(value: dict) -> bytes:
    raw = (json.dumps(value, indent=2) + '\n').encode()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Go-network-runtime-receipt-bound')
    return raw


def source_inputs(root: Path) -> dict:
    names = set(BUILD_RECIPE) | {'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml',
        'tools/qualify_go_network_runtime.py', 'tools/ci/suites.d/go-network-runtime.json'}
    # Bind data included by Rust fixtures as well as .rs/manifest files. Do not
    # silently omit include_bytes/include_str inputs or authenticated vendor code.
    listed = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root, timeout=30)
    if len(listed) > 4 * 1024 * 1024:
        raise ValueError('Go-network-runtime-path-inventory-bound')
    for name in listed.decode('utf-8').split('\0'):
        if name.startswith(('apps/', 'crates/', 'wit/', 'schemas/', 'examples/', 'sdk/go-guest/')) or (
                name.startswith('tools/') and name.endswith('.py')):
            names.add(name)
    if not 100 <= len(names) <= 32768:
        raise ValueError('Go-network-runtime-input-count')
    result, total = {}, 0
    for name in sorted(names):
        raw = read_file(root / name, 16 * 1024 * 1024)
        total += len(raw)
        if total > 128 * 1024 * 1024:
            raise ValueError('Go-network-runtime-source-aggregate-bound')
        result[name] = {'digest': digest(raw), 'size': len(raw)}
    return result


def outcomes(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('Go-network-runtime-output-bound')
    passed = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if passed != [CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', b'0')]:
        raise ValueError('Go-network-runtime-exact-native-case-required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Go-network-runtime-duplicate-observation-field')
            result[key] = value
        return result
    def decode(row):
        return json.loads(row, object_pairs_hook=unique)
    def same(actual, expected):
        # Python considers True == 1 and 0.0 == 0; the closed wire evidence does not.
        return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    rows = [decode(row) for row in re.findall(rb'^GO_NETWORK_CASE (.+)$', raw, re.M)]
    wanted = [dict(zip(('case', 'mode', 'result', 'contacts'), row)) for row in EXPECTED]
    if not same(rows, wanted):
        raise ValueError('Go-network-runtime-exact-ordinary-observations-required')
    owners = [decode(row) for row in re.findall(rb'^GO_NETWORK_OWNER (.+)$', raw, re.M)]
    wanted_owners = [{'case': row[0], 'stores': 0, 'instances': 0, 'streamOwners': 0,
                      'ioOwners': 0, 'kernelRetirementQualified': False} for row in EXPECTED]
    if not same(owners, wanted_owners):
        raise ValueError('Go-network-runtime-exact-user-owner-retirement-required')
    complete = [decode(row) for row in re.findall(rb'^GO_NETWORK_COMPLETE (.+)$', raw, re.M)]
    if not same(complete, [{'cases': 12, 'contacts': 4, 'cleanLogicalProviderStop': True,
                     'kernelRetirementQualified': False, 'normalProviderInstalled': False}]):
        raise ValueError('Go-network-runtime-completion-or-kernel-claim')
    return {'cases': rows, 'userSpaceOwners': owners, 'completion': complete[0]}


def qualify(root: Path, output: Path, revision: str) -> dict:
    environment = dict(os.environ, CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
                       CARGO_TARGET_DIR=str(root / 'target'), LSF_GUEST_SDK_LANGUAGE='go')
    artifacts.require_source(root, revision, environment)
    if sys.platform != 'linux':
        raise ValueError('Go-network-runtime-linux-required')
    output = fresh(output)
    before = source_inputs(root)
    inputs = encoded(before)
    (output / 'native-inputs.json').write_bytes(inputs)
    record = {'schemaVersion': 'latent.go.network.runtime.v1', 'sourceRevision': revision,
              'status': 'in-progress', 'sourceDigest': digest(inputs), 'normalProviderInstalled': False,
              'kernelAccountingQualified': False, 'fullGoNetworkingQualified': False}
    deadline = time.monotonic() + 1800

    def command(args: list[str], name: str, timeout: int, maximum: int):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Go-network-runtime-overall-deadline')
        try:
            result = run_owned(args, cwd=root, env=environment, timeout=min(timeout, remaining),
                               maximum=maximum, separate_stderr=True)
        except ProcessFailure as error:
            result = error.result
            if result is not None:
                (output / (name + '.stdout.log')).write_bytes(result.output)
                (output / (name + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
            raise
        (output / (name + '.stdout.log')).write_bytes(result.output)
        (output / (name + '.stderr.log')).write_bytes(redact(result.stderr.decode('utf-8', 'replace')).encode())
        if result.returncode:
            raise ValueError('Go-network-runtime-command-failed:' + name)
        return result.output

    try:
        # Recompile the current guarded ordinary source once. The earlier770
        # component does not contain the four custom-resolver refusals or EOF mode.
        prepared = output / 'fixture'
        prepared.mkdir()
        fixture = root / 'sdk/go-guest/runtime/network-conformance'
        source = snapshot(fixture)
        (prepared / 'src').mkdir()
        (prepared / 'src/main.go').write_bytes(source['main.go'])
        for name in ('go.mod', 'go.sum'):
            (prepared / name).write_bytes(read_file(root / 'sdk/go-guest/runtime-deps' / name))
        stage(prepared / 'wit', fixture)
        commands = Commands(prepared, prepared, environment, deadline_seconds=900, command_seconds=600)
        compiler = Compiler(prepared / 'compiler', root / 'sdk/go-guest', commands, runtime_profile=MANAGED_PROFILE)
        component, _ = compiler.compile(prepared / 'src', prepared / 'wit',
            'examples:go-standard-network/service@1.0.0', prepared / 'build', runtime_profile=MANAGED_PROFILE)
        compiler.check_unchanged()
        if source != snapshot(fixture):
            raise ValueError('Go-network-runtime-source-changed')
        compiled = {'profile': MANAGED_PROFILE, 'sourceUnchanged': True,
                    'sourceDigest': digest(source['main.go']), 'componentDigest': digest(read_file(component, 64 * 1024 * 1024)),
                    'tools': compiler.materials, 'compilerInputsDigest': digest(inventory(source))}
        (prepared / 'GO-NETWORK-COMPILE.json').write_bytes(encoded(compiled))
        record['component'] = compiled
        compiler_version = command(['rustc', '--version'], 'rustc', 30, 4096).decode().strip()
        if not compiler_version.startswith('rustc 1.97.1 '):
            raise ValueError('Go-network-runtime-rust-compiler')
        command(['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--test', 'go_outbound_streams',
                 '--no-run', '--message-format=json'], 'cargo', 1200, 16 * 1024 * 1024)
        suite, = [row for row in registry.load(root / 'tools/ci/suites.json')['suites'] if row['id'] == SUITE]
        if suite['expectedCases'] != [CASE] or suite['expectedIgnored'] != [CASE] or suite['minimumCases'] != 1:
            raise ValueError('Go-network-runtime-suite-contract')
        descriptor = artifacts.Suite(suite['manifest'], suite['target'], suite['source'], CASE, frozenset({CASE}), True, kind='test')
        native = artifacts.read_inventory(output / 'cargo.stdout.log', root, descriptor, target=root / 'target')
        environment = artifacts.cargo_environment(root, native, environment, target=root / 'target')
        environment['LSF_GO_NETWORK_FIXTURE'] = str(prepared)
        listed = command([str(native.executable), '--list'], 'list', 30, 65536)
        ignored = command([str(native.executable), '--ignored', '--list'], 'ignored', 30, 65536)
        discovery.validate_cases(suite, discovery.listing(listed), discovery.listing(ignored), {})
        raw = command([str(native.executable), '--ignored', '--exact', CASE, '--show-output', '--test-threads=1'],
                      'native', 300, 1024 * 1024)
        record['observations'] = outcomes(raw)
        if before != source_inputs(root):
            raise ValueError('Go-network-runtime-native-inputs-changed')
        compiler.check_unchanged()
        record.update(status='passed', sourceUnchanged=True, nativeCompiler=compiler_version,
                      nativeExecutableDigest=digest(read_file(native.executable, 1024 * 1024 * 1024)))
        (output / 'receipt.json').write_bytes(encoded(record))
        return record
    except BaseException:
        record['status'] = 'failed'
        (output / 'FAILED.json').write_bytes(encoded(record))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    arguments = parser.parse_args()
    print(json.dumps(qualify(ROOT, arguments.output.resolve(), arguments.source_commit)))
