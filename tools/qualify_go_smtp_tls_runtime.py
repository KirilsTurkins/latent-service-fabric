#!/usr/bin/env python3
"""One freshly compiled ordinary Go SMTP/STARTTLS fixture in a targeted signed test harness.

The provider is the explicit logical-reference development installation. Neither
its user-space idle counters nor peer FIN/RST certify final kernel retirement.
Guest crypto/tls is distinct from a host TLS provider/accounting qualification.
"""
from __future__ import annotations

import argparse
import hashlib
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

CACHE_TEMPLATE = 'sdk/go-guest/runtime/tls_cert_cache.go.in'
CACHE_TESTS = 'tools/tests/fixtures/go_network/tls-cache-test.go.txt'
CACHE_CASES = ('TestCacheRetainsIdentityThroughGC', 'TestCacheRejectsOversizedDERBeforeParseOrCopy',
    'TestCacheRejectsNinthDistinctCertificateAndRetainsHits', 'TestCacheAggregateDERBudgetAndNoEviction',
    'TestCacheParseFailureMatchesUpstreamAndConsumesNoEntry', 'TestFreshCacheStartsEmpty',
    'TestConcurrentSameCertificatePublishesOnce', 'TestCacheExactPerDERBoundaryAndOneByteRefusal')
REFERENCE_GO_SHA = '548d3c32f83fa81152f543eb1526be7884cfe0526eb5e9ce29d3eca14786e7e0'

CASE = 'signed_ordinary_go_smtp_starttls_preserves_trust_hostname_and_fresh_connection'
SUITE = 'latent-wasmtime.test.go_smtp_tls'
EXPECTED = (
    ('ordinary-smtp-plain', 0, 'ordinary-smtp-plain', 1),
    ('ordinary-starttls13', 1, 'ordinary-smtp-tls13', 1),
    ('hostname-refused', 2, 'ordinary-starttls-hostname-refused', 1),
    ('trust-refused', 3, 'ordinary-starttls-trust-refused', 1),
    ('ordinary-starttls12', 4, 'ordinary-smtp-tls12', 1),
    ('fresh-starttls13', 5, 'ordinary-smtp-tls13', 1),
)


def encoded(value: dict) -> bytes:
    raw = (json.dumps(value, indent=2) + '\n').encode()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError('Go-smtp-tls-runtime-receipt-bound')
    return raw


def source_inputs(root: Path) -> dict:
    names = set(BUILD_RECIPE) | {'Cargo.toml', 'Cargo.lock', 'rust-toolchain.toml',
        'tools/qualify_go_smtp_tls_runtime.py', 'tools/ci/suites.d/go-smtp-tls-runtime.json', CACHE_TESTS}
    # Bind data included by Rust fixtures as well as .rs/manifest files. Do not
    # silently omit include_bytes/include_str inputs or authenticated vendor code.
    listed = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root, timeout=30)
    if len(listed) > 4 * 1024 * 1024:
        raise ValueError('Go-smtp-tls-runtime-path-inventory-bound')
    for name in listed.decode('utf-8').split('\0'):
        if name.startswith(('apps/', 'crates/', 'wit/', 'schemas/', 'examples/', 'sdk/go-guest/')) or (
                name.startswith('tools/') and name.endswith('.py')):
            names.add(name)
    if not 100 <= len(names) <= 32768:
        raise ValueError('Go-smtp-tls-runtime-input-count')
    result, total = {}, 0
    for name in sorted(names):
        raw = read_file(root / name, 16 * 1024 * 1024)
        total += len(raw)
        if total > 128 * 1024 * 1024:
            raise ValueError('Go-smtp-tls-runtime-source-aggregate-bound')
        result[name] = {'digest': digest(raw), 'size': len(raw)}
    return result


def outcomes(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('Go-smtp-tls-runtime-output-bound')
    passed = re.findall(rb'^test ([A-Za-z0-9_:]+) \.\.\. ok$', raw, re.M)
    totals = re.findall(rb'^test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;', raw, re.M)
    if passed != [CASE.encode()] or totals != [(b'1', b'0', b'0', b'0', b'0')]:
        raise ValueError('Go-smtp-tls-runtime-exact-native-case-required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Go-smtp-tls-runtime-duplicate-observation-field')
            result[key] = value
        return result
    def decode(row):
        return json.loads(row, object_pairs_hook=unique)
    def same(actual, expected):
        # Python considers True == 1 and 0.0 == 0; the closed wire evidence does not.
        return json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True)
    rows = [decode(row) for row in re.findall(rb'^GO_SMTP_CASE (.+)$', raw, re.M)]
    wanted = [dict(zip(('case', 'mode', 'result', 'contacts'), row)) for row in EXPECTED]
    if not same(rows, wanted):
        raise ValueError('Go-smtp-tls-runtime-exact-ordinary-observations-required')
    owners = [decode(row) for row in re.findall(rb'^GO_SMTP_OWNER (.+)$', raw, re.M)]
    wanted_owners = [{'case': row[0], 'stores': 0, 'instances': 0, 'streamOwners': 0,
                      'ioOwners': 0, 'kernelRetirementQualified': False} for row in EXPECTED]
    if not same(owners, wanted_owners):
        raise ValueError('Go-smtp-tls-runtime-exact-user-owner-retirement-required')
    complete = [decode(row) for row in re.findall(rb'^GO_SMTP_COMPLETE (.+)$', raw, re.M)]
    if not same(complete, [{'cases': 6, 'contacts': 6, 'cleanLogicalProviderStop': True,
                     'kernelRetirementQualified': False, 'normalProviderInstalled': False, 'hostTlsQualified': False}]):
        raise ValueError('Go-smtp-tls-runtime-completion-or-kernel-claim')
    return {'cases': rows, 'userSpaceOwners': owners, 'completion': complete[0]}


def cache_reference_source(raw: bytes) -> bytes:
    if len(raw) > 16384 or b'\r' in raw or raw.count(b'\npackage tls\n') != 1:
        raise ValueError('Go-tls-cache-reference-source-shape')
    # Only the package declaration changes; the production cache body is exact.
    return raw.replace(b'\npackage tls\n', b'\npackage tlscache\n', 1)


def cache_reference_outcomes(raw: bytes) -> list[str]:
    if len(raw) > 1024 * 1024:
        raise ValueError('Go-tls-cache-reference-output-bound')
    cases, packages = [], []
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result: raise ValueError('Go-tls-cache-reference-duplicate-field')
            result[key] = value
        return result
    for line in raw.splitlines():
        row = json.loads(line, object_pairs_hook=unique)
        if not isinstance(row, dict) or row.get('Package') != 'example.invalid/tlscache':
            raise ValueError('Go-tls-cache-reference-package')
        action, name = row.get('Action'), row.get('Test')
        if action not in {'start', 'run', 'output', 'pass'} or name is not None and name not in CACHE_CASES:
            raise ValueError('Go-tls-cache-reference-failed-skipped-or-unknown')
        if action == 'pass':
            (packages if name is None else cases).append('pass' if name is None else name)
    if cases != list(CACHE_CASES) or packages != ['pass']:
        raise ValueError('Go-tls-cache-reference-all-eight-required')
    return cases


def qualify(root: Path, output: Path, revision: str, reference_go: Path) -> dict:
    environment = dict(os.environ, CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
                       CARGO_TARGET_DIR=str(root / 'target'), LSF_GUEST_SDK_LANGUAGE='go')
    artifacts.require_source(root, revision, environment)
    if sys.platform != 'linux':
        raise ValueError('Go-smtp-tls-runtime-linux-required')
    output = fresh(output)
    before = source_inputs(root)
    inputs = encoded(before)
    (output / 'native-inputs.json').write_bytes(inputs)
    record = {'schemaVersion': 'latent.go.smtp-tls.runtime.v1', 'sourceRevision': revision,
              'status': 'in-progress', 'sourceDigest': digest(inputs), 'normalProviderInstalled': False,
              'kernelAccountingQualified': False, 'fullGoNetworkingQualified': False, 'hostTlsAccountingQualified': False}
    deadline = time.monotonic() + 1800

    def command(args: list[str], name: str, timeout: int, maximum: int, *, env=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Go-smtp-tls-runtime-overall-deadline')
        try:
            result = run_owned(args, cwd=root, env=environment if env is None else env, timeout=min(timeout, remaining),
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
            raise ValueError('Go-smtp-tls-runtime-command-failed:' + name)
        return result.output

    try:
        reference_go = reference_go.resolve(strict=True)
        reference_before = read_file(reference_go, 64 * 1024 * 1024)
        if hashlib.sha256(reference_before).hexdigest() != REFERENCE_GO_SHA:
            raise ValueError('Go-tls-cache-reference-compiler-preimage')
        reference = output / 'cache-reference'; reference.mkdir()
        (reference / 'go.mod').write_bytes(b'module example.invalid/tlscache\n\ngo 1.27.3\n')
        cache_source = read_file(root / CACHE_TEMPLATE, 16384)
        cache_tests = read_file(root / CACHE_TESTS, 16384)
        (reference / 'cache.go').write_bytes(cache_reference_source(cache_source))
        (reference / 'cache_test.go').write_bytes(cache_tests)
        reference_env = dict(environment, GOOS='linux', GOARCH='amd64', CGO_ENABLED='0',
            GOTOOLCHAIN='local', GOENV='off', GOWORK='off', GOFLAGS='', GOPROXY='off',
            GOSUMDB='off', GOMAXPROCS='2', GOCACHE=str(reference / 'cache'))
        version = command([str(reference_go), 'version'], 'cache-go-version', 30, 4096, env=reference_env).decode().strip()
        if version != 'go version go1.27.3 linux/amd64':
            raise ValueError('Go-tls-cache-reference-compiler-version')
        raw_reference = command([str(reference_go), '-C', str(reference), 'test', '-json',
            '-count=1', '-timeout=15s', './...'], 'cache-reference', 120, 1024 * 1024, env=reference_env)
        reference_cases = cache_reference_outcomes(raw_reference)
        if reference_before != read_file(reference_go, 64 * 1024 * 1024):
            raise ValueError('Go-tls-cache-reference-compiler-changed')
        record['cacheReference'] = {'cases': reference_cases, 'compilerDigest': digest(reference_before),
            'cacheSourceDigest': digest(cache_source), 'testSourceDigest': digest(cache_tests),
            'projection': 'package-declaration-only; exact-production-cache-body',
            'entries': 8, 'maximumDERBytes': 16384, 'maximumAggregateDERBytes': 65536}
        # Compile the real public smtp client and guest crypto/tls once.
        # Existing TCP components do not contain these ordinary protocol paths.
        prepared = output / 'fixture'
        prepared.mkdir()
        fixture = root / 'sdk/go-guest/runtime/smtp-tls-conformance'
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
            raise ValueError('Go-smtp-tls-runtime-source-changed')
        compiled = {'profile': MANAGED_PROFILE, 'sourceUnchanged': True,
                    'sourceDigest': digest(source['main.go']), 'componentDigest': digest(read_file(component, 64 * 1024 * 1024)),
                    'tools': compiler.materials, 'compilerInputsDigest': digest(inventory(source))}
        (prepared / 'GO-SMTP-TLS-COMPILE.json').write_bytes(encoded(compiled))
        record['component'] = compiled
        compiler_version = command(['rustc', '--version'], 'rustc', 30, 4096).decode().strip()
        if not compiler_version.startswith('rustc 1.97.1 '):
            raise ValueError('Go-smtp-tls-runtime-rust-compiler')
        command(['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--test', 'go_smtp_tls',
                 '--no-run', '--message-format=json'], 'cargo', 1200, 16 * 1024 * 1024)
        suite, = [row for row in registry.load(root / 'tools/ci/suites.json')['suites'] if row['id'] == SUITE]
        if suite['expectedCases'] != [CASE] or suite['expectedIgnored'] != [CASE] or suite['minimumCases'] != 1:
            raise ValueError('Go-smtp-tls-runtime-suite-contract')
        descriptor = artifacts.Suite(suite['manifest'], suite['target'], suite['source'], CASE, frozenset({CASE}), True, kind='test')
        native = artifacts.read_inventory(output / 'cargo.stdout.log', root, descriptor, target=root / 'target')
        environment = artifacts.cargo_environment(root, native, environment, target=root / 'target')
        environment['LSF_GO_SMTP_TLS_FIXTURE'] = str(prepared)
        listed = command([str(native.executable), '--list'], 'list', 30, 65536)
        ignored = command([str(native.executable), '--ignored', '--list'], 'ignored', 30, 65536)
        discovery.validate_cases(suite, discovery.listing(listed), discovery.listing(ignored), {})
        raw = command([str(native.executable), '--ignored', '--exact', CASE, '--show-output', '--test-threads=1'],
                      'native', 300, 1024 * 1024)
        record['observations'] = outcomes(raw)
        if before != source_inputs(root):
            raise ValueError('Go-smtp-tls-runtime-native-inputs-changed')
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
    parser.add_argument('--reference-go', type=Path, required=True)
    parser.add_argument('--source-commit', default=os.environ.get('GITHUB_SHA'))
    arguments = parser.parse_args()
    print(json.dumps(qualify(ROOT, arguments.output.resolve(), arguments.source_commit, arguments.reference_go)))
