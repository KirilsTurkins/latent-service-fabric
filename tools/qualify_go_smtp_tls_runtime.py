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
from tools.go_guest.activation import MANAGED_PROFILE, STACK_PROFILE
from tools.go_network_read_barrier import profile_witness
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
REFERENCE_GO_SHA = '5f5eb6d0b2fb6aa0bb5d5f8c5f1c944e0de955c925f0111af92a9d8f79680b5b'

CASE = 'signed_ordinary_go_smtp_starttls_preserves_trust_hostname_and_fresh_connection'
PUBLISHED_CASE = 'signed_published_go_smtp_and_separate_worker_timer_preserve_original_owners'
LOST_REPLY_CASE = 'signed_published_go_smtp_lost_reply_does_not_replay_and_fresh_succeeds'
SUITE = 'latent-wasmtime.test.go_smtp_tls'
V5_PUSH_BRANCH = 'feat/go-smtp-starttls-20261020'
V7_PUSH_BRANCH = 'feat/go-smtp-v7-20261110'
PUBLISHED_PUSH_BRANCH = 'feat/go-published-smtp-v7-20261110'
REFERENCE_PIN_PUSH_BRANCH = 'fix/go-smtp-reference-pin-20261110'
LOST_REPLY_PUSH_BRANCH = 'test/go-smtp-lost-reply-20261110'
EXPECTED = (
    ('ordinary-smtp-plain', 0, 'ordinary-smtp-plain', 1),
    ('ordinary-starttls13', 1, 'ordinary-smtp-tls13', 1),
    ('hostname-refused', 2, 'ordinary-starttls-hostname-refused', 1),
    ('trust-refused', 3, 'ordinary-starttls-trust-refused', 1),
    ('ordinary-starttls12', 4, 'ordinary-smtp-tls12', 1),
    ('fresh-starttls13', 5, 'ordinary-smtp-tls13', 1),
)
PUBLISHED_EXPECTED = (
    ('published-smtp-plain', 0, 'published-smtp-plain', 1),
    ('published-starttls13', 1, 'published-smtp-tls13', 1),
    ('published-hostname-refused', 2, 'published-starttls-hostname-refused', 1),
    ('published-trust-refused', 3, 'published-starttls-trust-refused', 1),
    ('published-starttls12', 4, 'published-smtp-tls12', 1),
    ('published-fresh-starttls13', 5, 'published-smtp-tls13', 1),
)
LOST_REPLY_EXPECTED = (
    ('published-lost-reply', 0, 'published-smtp-delivery-unknown', 1),
    ('published-fresh-after-lost-reply', 1, 'published-smtp-fresh', 1),
)


def workflow_profile(event: str, branch: str, choice: str) -> str:
    """Select the original v5 branch, dedicated v7 branch or bounded manual choice."""
    if event == 'push' and not choice:
        if branch == V5_PUSH_BRANCH:
            return MANAGED_PROFILE
        if branch in (V7_PUSH_BRANCH, PUBLISHED_PUSH_BRANCH, REFERENCE_PIN_PUSH_BRANCH, LOST_REPLY_PUSH_BRANCH):
            return STACK_PROFILE
    elif event == 'workflow_dispatch':
        if choice in ('', 'v5'):
            return MANAGED_PROFILE
        if choice == 'v7':
            return STACK_PROFILE
    raise ValueError('Go-smtp-tls-runtime-workflow-selection')


def workflow_program(event: str, branch: str, choice: str) -> str:
    if event == 'push' and not choice:
        if branch in (V5_PUSH_BRANCH, V7_PUSH_BRANCH):
            return 'standard'
        if branch in (PUBLISHED_PUSH_BRANCH, REFERENCE_PIN_PUSH_BRANCH):
            return 'published'
        if branch == LOST_REPLY_PUSH_BRANCH:
            return 'published-lost-reply'
    elif event == 'workflow_dispatch':
        if choice in ('', 'standard'):
            return 'standard'
        if choice == 'published':
            return 'published'
        if choice == 'published-lost-reply':
            return 'published-lost-reply'
    raise ValueError('Go-smtp-tls-runtime-workflow-program')


def require_reference_go(raw: bytes) -> None:
    """Authenticate the complete official Linux Go executable before use."""
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != REFERENCE_GO_SHA:
        raise ValueError('Go-tls-cache-reference-compiler-preimage')


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


def outcomes(raw: bytes, filtered: int = 0, program: str = 'standard') -> dict:
    if program == 'standard':
        selected_case, selected_rows = CASE, EXPECTED
    elif program == 'published':
        selected_case, selected_rows = PUBLISHED_CASE, PUBLISHED_EXPECTED
    elif program == 'published-lost-reply':
        selected_case, selected_rows = LOST_REPLY_CASE, LOST_REPLY_EXPECTED
    else:
        raise ValueError('Go-smtp-tls-runtime-program-not-selected')
    if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
        raise ValueError('Go-smtp-tls-runtime-output-bound')
    if type(filtered) is not int or filtered < 0:
        raise ValueError('Go-smtp-tls-runtime-invalid-filtered-count')
    tests = [line for line in raw.split(b'\n')
             if line.lstrip(b' \t') == b'test' or line.lstrip(b' \t').startswith((b'test ', b'test\t'))]
    summary = re.compile(rb'test result: ok\. 1 passed; 0 failed; 0 ignored; 0 measured; '
                         + str(filtered).encode() + rb' filtered out; finished in [0-9]+(?:\.[0-9]+)?s')
    if (len(tests) != 2 or tests[0] != b'test ' + selected_case.encode() + b' ... ok'
            or summary.fullmatch(tests[1]) is None):
        raise ValueError('Go-smtp-tls-runtime-exact-native-case-required')

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Go-smtp-tls-runtime-duplicate-observation-field')
            result[key] = value
        return result

    def nonfinite(_):
        raise ValueError('Go-smtp-tls-runtime-nonfinite-observation')

    def same(actual, expected):
        return (type(actual) is dict and actual.keys() == expected.keys()
                and all(type(actual[key]) is type(value) and actual[key] == value
                        for key, value in expected.items()))

    observed = []
    for line in raw.split(b'\n'):
        if not line.lstrip().startswith(b'GO_SMTP_'):
            continue
        if len(line) > 4096:
            raise ValueError('Go-smtp-tls-runtime-record-bound')
        name, separator, payload = line.partition(b' ')
        if (separator != b' ' or name not in {b'GO_SMTP_OWNER', b'GO_SMTP_CASE', b'GO_SMTP_COMPLETE'}
                or not payload):
            raise ValueError('Go-smtp-tls-runtime-malformed-observation')
        try:
            value = json.loads(payload.decode('utf-8'), object_pairs_hook=unique, parse_constant=nonfinite)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise ValueError('Go-smtp-tls-runtime-malformed-observation') from None
        observed.append((name, value))
        if len(observed) > 2 * len(selected_rows) + 1:
            raise ValueError('Go-smtp-tls-runtime-exact-event-order-required')

    expected = []
    for label, mode, result, contacts in selected_rows:
        expected.append((b'GO_SMTP_OWNER', {'case': label, 'stores': 0, 'instances': 0,
            'streamOwners': 0, 'ioOwners': 0, 'kernelRetirementQualified': False}))
        expected.append((b'GO_SMTP_CASE', {'case': label, 'mode': mode, 'result': result, 'contacts': contacts}))
    complete = {'cases': 6, 'contacts': 6, 'cleanLogicalProviderStop': True,
        'kernelRetirementQualified': False, 'normalProviderInstalled': False, 'hostTlsQualified': False}
    if program == 'published-lost-reply':
        complete = {'cases': 2, 'contacts': 2, 'peerMutations': 1, 'postCompletionReplayWindowMillis': 250,
            'cleanLogicalProviderStop': True, 'kernelRetirementQualified': False,
            'normalProviderInstalled': False, 'hostTlsQualified': False}
    expected.append((b'GO_SMTP_COMPLETE', complete))
    if [name for name, _ in observed] != [name for name, _ in expected]:
        raise ValueError('Go-smtp-tls-runtime-exact-event-order-required')
    reasons = {b'GO_SMTP_CASE': 'Go-smtp-tls-runtime-exact-ordinary-observations-required',
               b'GO_SMTP_OWNER': 'Go-smtp-tls-runtime-exact-user-owner-retirement-required',
               b'GO_SMTP_COMPLETE': 'Go-smtp-tls-runtime-completion-or-kernel-claim'}
    for (name, value), (_, wanted) in zip(observed, expected):
        if not same(value, wanted):
            raise ValueError(reasons[name])
    return {'cases': [value for name, value in observed if name == b'GO_SMTP_CASE'],
            'userSpaceOwners': [value for name, value in observed if name == b'GO_SMTP_OWNER'],
            'completion': observed[-1][1]}


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


def contracts_artifact(raw: bytes, root: Path) -> Path:
    """Select the exact successful Cargo example from this checkout's inventory."""
    if not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024:
        raise ValueError('Go-published-smtp-contracts-inventory-bound')
    expected_manifest = (root / 'crates/latent-packaging/Cargo.toml').resolve(strict=True)
    expected_source = (root / 'crates/latent-packaging/examples/capsule_contracts.rs').resolve(strict=True)
    expected_directory = (root / 'target/debug/examples').resolve(strict=True)
    selected = None
    finished = False
    for line in raw.splitlines():
        if not line.strip():
            continue
        if len(line) > 1024 * 1024 or finished:
            raise ValueError('Go-published-smtp-contracts-inventory-invalid')
        row = json.loads(line, object_pairs_hook=artifacts.unique_object)
        if not isinstance(row, dict):
            raise ValueError('Go-published-smtp-contracts-inventory-invalid')
        if row.get('reason') == 'build-finished':
            if row.get('success') is not True:
                raise ValueError('Go-published-smtp-contracts-build-failed')
            finished = True
        elif row.get('reason') == 'compiler-artifact':
            manifest = row.get('manifest_path')
            target = row.get('target')
            if not isinstance(manifest, str) or not isinstance(target, dict):
                raise ValueError('Go-published-smtp-contracts-inventory-invalid')
            if Path(manifest).resolve() != expected_manifest:
                continue
            if target.get('kind') != ['example'] or target.get('name') != 'capsule_contracts':
                continue
            profile = row.get('profile')
            if not isinstance(profile, dict) or profile.get('test') is not False:
                raise ValueError('Go-published-smtp-contracts-profile-invalid')
            if Path(target.get('src_path', '')).resolve() != expected_source:
                raise ValueError('Go-published-smtp-contracts-source-mismatch')
            executable = artifacts.absolute_path(row.get('executable'))
            if not executable.is_relative_to(expected_directory) or not executable.is_file() or selected is not None:
                raise ValueError('Go-published-smtp-contracts-artifact-invalid')
            selected = executable
    if not finished or selected is None:
        raise ValueError('Go-published-smtp-contracts-artifact-missing')
    return selected


def qualify(root: Path, output: Path, revision: str, reference_go: Path, profile: str = MANAGED_PROFILE,
            program: str = 'standard') -> dict:
    if profile not in (MANAGED_PROFILE, STACK_PROFILE):
        raise ValueError('Go-smtp-tls-runtime-profile-not-selected')
    if program not in ('standard', 'published', 'published-lost-reply') or program != 'standard' and profile != STACK_PROFILE:
        raise ValueError('Go-smtp-tls-runtime-program-not-selected')
    environment = dict(os.environ, CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0',
                       CARGO_TARGET_DIR=str(root / 'target'), LSF_GUEST_SDK_LANGUAGE='go',
                       LSF_GO_SMTP_TLS_PROFILE=profile)
    artifacts.require_source(root, revision, environment)
    if sys.platform != 'linux':
        raise ValueError('Go-smtp-tls-runtime-linux-required')
    output = fresh(output)
    before = source_inputs(root)
    inputs = encoded(before)
    (output / 'native-inputs.json').write_bytes(inputs)
    schema = ('latent.go.published-smtp.lost-reply.v1' if program == 'published-lost-reply' else
              'latent.go.published-smtp.runtime.v1' if program == 'published' else
              'latent.go.smtp-tls.runtime.v1' if profile == MANAGED_PROFILE else 'latent.go.smtp-tls.runtime.v7.v1')
    record = {'schemaVersion': schema, 'sourceRevision': revision,
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
        require_reference_go(reference_before)
        reference = output / 'cache-reference'; reference.mkdir()
        (reference / 'go.mod').write_bytes(b'module example.invalid/tlscache\n\ngo 1.27.4\n')
        cache_source = read_file(root / CACHE_TEMPLATE, 16384)
        cache_tests = read_file(root / CACHE_TESTS, 16384)
        (reference / 'cache.go').write_bytes(cache_reference_source(cache_source))
        (reference / 'cache_test.go').write_bytes(cache_tests)
        reference_env = dict(environment, GOOS='linux', GOARCH='amd64', CGO_ENABLED='0',
            GOTOOLCHAIN='local', GOENV='off', GOWORK='off', GOFLAGS='', GOPROXY='off',
            GOSUMDB='off', GOMAXPROCS='2', GOCACHE=str(reference / 'cache'))
        version = command([str(reference_go), 'version'], 'cache-go-version', 30, 4096, env=reference_env).decode().strip()
        if version != 'go version go1.27.4 linux/amd64':
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
        compiler_version = command(['rustc', '--version'], 'rustc', 30, 4096).decode().strip()
        if not compiler_version.startswith('rustc 1.97.1 '):
            raise ValueError('Go-smtp-tls-runtime-rust-compiler')
        prepared = output / 'fixture'
        compiler = None
        if program in ('published', 'published-lost-reply'):
            # Build only the maintained authoring contracts example, then
            # select its source-bound product from this exact Cargo inventory.
            cargo = command(['cargo', 'build', '--locked', '-p', 'latent-packaging',
                             '--example', 'capsule_contracts', '--message-format=json'],
                            'cargo-contracts', 1200, 16 * 1024 * 1024)
            contracts = contracts_artifact(cargo, root)
            remaining = min(1100, int(deadline - time.monotonic()) - 5)
            if remaining < 30:
                raise ValueError('Go-smtp-tls-runtime-overall-deadline')
            args = [sys.executable, str(root / 'tools/qualify_go_published_smtp.py'),
                     '--output', str(prepared), '--contracts-tool', str(contracts),
                     '--deadline-seconds', str(remaining)]
            if program == 'published-lost-reply': args.append('--lost-reply')
            command(args, 'published-compile', remaining, 1024 * 1024)
            compiled = json.loads(read_file(prepared / 'GO-SMTP-PUBLISHED-COMPILE.json', 4 * 1024 * 1024))
            fixture = root / 'sdk/go-guest/runtime/published-smtp-conformance'
            original_source = snapshot(fixture)
            source = dict(original_source)
            if program == 'published-lost-reply':
                source['main.go'] = read_file(root / 'sdk/go-guest/runtime/published-smtp-lost-reply/main.go', 65536)
            if (compiled.get('profile') != STACK_PROFILE or compiled.get('sourceUnchanged') is not True
                    or compiled.get('sourceDigest') != digest(source['main.go'])
                    or compiled.get('componentDigest') != digest(read_file(prepared / 'build/component.wasm', 64 * 1024 * 1024))):
                raise ValueError('Go-published-smtp-compiled-inputs-disagree')
            record['program'] = program
            record['contractsExecutableDigest'] = digest(read_file(contracts, 512 * 1024 * 1024))
        else:
            # Preserve the original ordinary standard-library fixture and path.
            prepared.mkdir()
            fixture = root / 'sdk/go-guest/runtime/smtp-tls-conformance'
            source = snapshot(fixture)
            (prepared / 'src').mkdir()
            (prepared / 'src/main.go').write_bytes(source['main.go'])
            for name in ('go.mod', 'go.sum'):
                (prepared / name).write_bytes(read_file(root / 'sdk/go-guest/runtime-deps' / name))
            stage(prepared / 'wit', fixture)
            commands = Commands(prepared, prepared, environment, deadline_seconds=900, command_seconds=600)
            compiler = Compiler(prepared / 'compiler', root / 'sdk/go-guest', commands, runtime_profile=profile)
            component, _ = compiler.compile(prepared / 'src', prepared / 'wit',
                'examples:go-standard-network/service@1.0.0', prepared / 'build', runtime_profile=profile)
            compiler.check_unchanged()
            if source != snapshot(fixture):
                raise ValueError('Go-smtp-tls-runtime-source-changed')
            compiled = {'profile': profile, 'sourceUnchanged': True,
                        'sourceDigest': digest(source['main.go']),
                        'componentDigest': digest(read_file(component, 64 * 1024 * 1024)),
                        'tools': compiler.materials, 'compilerInputsDigest': digest(inventory(source))}
            (prepared / 'GO-SMTP-TLS-COMPILE.json').write_bytes(encoded(compiled))
        record['component'] = compiled
        command(['cargo', 'test', '--locked', '-p', 'latent-wasmtime', '--test', 'go_smtp_tls',
                 '--no-run', '--message-format=json'], 'cargo', 1200, 16 * 1024 * 1024)
        suite, = [row for row in registry.load(root / 'tools/ci/suites.json')['suites'] if row['id'] == SUITE]
        selected_case = (LOST_REPLY_CASE if program == 'published-lost-reply' else
                         PUBLISHED_CASE if program == 'published' else CASE)
        if selected_case not in suite['expectedIgnored']:
            raise ValueError('Go-smtp-tls-runtime-suite-contract')
        descriptor = artifacts.Suite(suite['manifest'], suite['target'], suite['source'],
                                     selected_case, frozenset({selected_case}), True, kind='test')
        native = artifacts.read_inventory(output / 'cargo.stdout.log', root, descriptor, target=root / 'target')
        environment = artifacts.cargo_environment(root, native, environment, target=root / 'target')
        environment['LSF_GO_SMTP_TLS_FIXTURE'] = str(prepared)
        listed = command([str(native.executable), '--list'], 'list', 30, 65536)
        ignored = command([str(native.executable), '--ignored', '--list'], 'ignored', 30, 65536)
        available = discovery.listing(listed)
        discovery.validate_cases(suite, available, discovery.listing(ignored), {})
        if selected_case not in available:
            raise ValueError('required-native-case-missing')
        raw = command([str(native.executable), '--ignored', '--exact', selected_case, '--show-output', '--test-threads=1'],
                      'native', 300, 1024 * 1024)
        record['observations'] = outcomes(raw, filtered=len(available) - 1, program=program)
        selected_limits = profile_witness(raw, profile)
        if selected_limits is not None:
            record['selectedRuntimeLimits'] = selected_limits
        if before != source_inputs(root):
            raise ValueError('Go-smtp-tls-runtime-native-inputs-changed')
        if compiler is not None:
            compiler.check_unchanged()
        if ((original_source if program in ('published', 'published-lost-reply') else source) != snapshot(fixture)
                or program == 'published-lost-reply' and source['main.go'] !=
                read_file(root / 'sdk/go-guest/runtime/published-smtp-lost-reply/main.go', 65536)):
            raise ValueError('Go-smtp-tls-runtime-source-changed')
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
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--profile', choices=(MANAGED_PROFILE, STACK_PROFILE))
    selection.add_argument('--workflow-selection', action='store_true')
    parser.add_argument('--program', choices=('standard', 'published', 'published-lost-reply'))
    arguments = parser.parse_args()
    if arguments.workflow_selection:
        if arguments.program is not None:
            raise ValueError('Go-smtp-tls-runtime-workflow-program-conflict')
        event, branch = os.environ.get('GITHUB_EVENT_NAME', ''), os.environ.get('GITHUB_REF_NAME', '')
        profile = workflow_profile(event, branch, os.environ.get('LSF_GO_SMTP_TLS_DISPATCH_PROFILE', ''))
        program = workflow_program(event, branch, os.environ.get('LSF_GO_SMTP_TLS_DISPATCH_PROGRAM', ''))
    else:
        profile = arguments.profile or MANAGED_PROFILE
        program = arguments.program or 'standard'
    print(json.dumps(qualify(ROOT, arguments.output.resolve(), arguments.source_commit, arguments.reference_go,
                             profile, program)))
