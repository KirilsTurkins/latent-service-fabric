"""Draft same-source supplement to the existing host-codec native producer.

This does not build or execute a guest, qualify signed execution, change an
existing receipt, or select the experimental Rust HTTP combined profile.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import textwrap
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HISTORICAL = 'c7134289f446cb3171eb0ffd800a94afc2a5209f'
WORKFLOW = '.github/workflows/sdk-native-products.yml'
CURRENT_WORKFLOW = '.github/workflows/rust-http-current-native.yml'
WORKFLOW_SHA256 = '9e73af407916abff86ec74c0394fd1ce2c50ceba7b61d874a7f442ea29fe5687'
STAGES = ('rust-version', 'normal-host-build', 'closed-http-refusal-controls',
    'neutral-resource-signing-controls', 'positive-timer-observer-controls',
    'phase-nominal-type-owner-controls', 'phase-emitted-type-owner-controls',
    'independent-http-configuration-controls', 'independent-http-dispatch-controls',
    'independent-http-secret-controls', 'phase-operational-metadata-controls',
    'phase-operational-binding-controls', 'release-preparation-protocol-reader-controls',
    'release-preparation-deadline-controls', 'release-preparation-web-readiness-controls',
    'release-preparation-rpc-controls', 'release-preparation-cli-controls',
    'release-preparation-projection-controls', 'release-preparation-transport-controls',
    'release-preparation-command-name-controls', 'release-preparation-dispatch-controls',
    'c-original-and-final-proof-controls', *(f'c-profile-{n}' for n in range(1, 12)),
    'ordinary-async-worker-owner-controls')

# File, Rust test-module prefix and optional function-name filter. These are the
# original default-feature sources, not newly selected experimental fixtures.
TEST_SOURCES = {
    'closed-http-refusal-controls': (('crates/latent-capabilities/src/broker/http/refusal.rs', 'broker::http::refusal::tests::', ''),),
    'neutral-resource-signing-controls': (('crates/latent-policy/examples/capsule_authoring/resource_neutral.rs', 'authoring::resource_neutral::tests::', ''),),
    'positive-timer-observer-controls': (('crates/latent-wasmtime/src/host/runtime/positive_timer_observer.rs', 'host::runtime::positive_timer_observer::tests::', ''),),
    'phase-nominal-type-owner-controls': (
        ('crates/latent-packaging/src/semantics/authoring/tests.rs', 'semantics::authoring::tests::', 'phase_nominal_owner_'),
        ('crates/latent-packaging/src/semantics/host/tests.rs', 'semantics::host::tests::', 'phase_nominal_owner_')),
    'phase-emitted-type-owner-controls': (('crates/latent-packaging/src/semantics/host/tests.rs', 'semantics::host::tests::', 'phase_component_nominal_pruning_rejects_missing_or_changed_owned_types'),),
    'independent-http-configuration-controls': (('apps/latentd/src/config/tests/providers/http_streaming.rs', 'config::tests::providers::http_streaming::', ''),),
    'independent-http-dispatch-controls': (('apps/latentd/src/standalone/providers/http/streaming.rs', 'standalone::providers::runtime::http::streaming::tests::', ''),),
    'independent-http-secret-controls': (('crates/latent-http/src/tests/secret_references.rs', 'tests::secret_references::', 'separate_http_installation_cannot_rebind_foreign_tenant_provider_or_origin_credentials'),),
    'release-preparation-deadline-controls': (('crates/latent-wire/src/management/release/preparation/tests.rs', 'management::release::preparation::tests::', ''),),
    'release-preparation-web-readiness-controls': (('crates/latent-wire/src/management/release/web/preparation/tests.rs', 'management::release::web::preparation::tests::', ''),),
    'release-preparation-rpc-controls': (('crates/latent-wire/tests/management_service/release/preparation.rs', 'release::preparation::', ''),),
    'release-preparation-transport-controls': (('apps/latentd/src/standalone/transport/tests/web_preparation.rs', 'standalone::transport::tests::web_preparation::', ''),),
    'ordinary-async-worker-owner-controls': (('crates/latent-wasmtime/src/native_stacks/tests.rs', 'native_stacks::tests::', ''),),
    'c-original-and-final-proof-controls': tuple(
        ('crates/latent-component-threading/src/' + file, prefix, '') for file, prefix in (
            ('admission.rs', 'admission::tests::'), ('c_abi.rs', 'c_abi::tests::'),
            ('c_component.rs', 'component::c::tests::'), ('c_context.rs', 'c_context::tests::'),
            ('c_lifecycle.rs', 'c_lifecycle::tests::'), ('c_preimage.rs', 'c_preimage::tests::'),
            ('c_root.rs', 'c_root::tests::'), ('c_template.rs', 'c_template::tests::'),
            ('lib.rs', 'tests::'), ('root.rs', 'root::tests::'),
            ('thread_entry.rs', 'thread_entry::tests::'))),
}
TEST_COUNTS = {'closed-http-refusal-controls': 3, 'neutral-resource-signing-controls': 3,
    'positive-timer-observer-controls': 8, 'phase-nominal-type-owner-controls': 2,
    'phase-emitted-type-owner-controls': 1, 'independent-http-configuration-controls': 8,
    'independent-http-dispatch-controls': 2, 'independent-http-secret-controls': 1,
    'release-preparation-deadline-controls': 2, 'release-preparation-web-readiness-controls': 4,
    'release-preparation-rpc-controls': 6, 'release-preparation-transport-controls': 4,
    'c-original-and-final-proof-controls': 60, 'ordinary-async-worker-owner-controls': 11}
TEST_PATTERN = re.compile(rb'#\[(?:tokio::)?test(?:\([^]]*\))?\](?:\s*#\[[^]]+\])*\s*'
    rb'(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def historical_files(root, names):
    from tools.build_observation import build_environment
    from tools.build_process import run_bounded_input_result

    names = sorted(set(names))
    require(0 < len(names) <= 64 and all(re.fullmatch(r'[A-Za-z0-9_./-]{1,256}', n)
        and all(part not in ('', '.', '..') for part in n.split('/')) for n in names),
        'rust-http-historical-paths')
    payload = ''.join(HISTORICAL + ':' + name + '\n' for name in names).encode()
    result = run_bounded_input_result(['git', 'cat-file', '--batch'], cwd=root,
        env=build_environment(root), timeout_seconds=60, max_output_bytes=16 * 1024**2,
        payload=payload, max_input_bytes=64 * 1024)
    require(result.returncode == 0, 'rust-http-historical-git-command')
    raw = result.stdout
    require(len(raw) <= 16 * 1024**2, 'rust-http-historical-byte-bound')
    files, at = {}, 0
    for name in names:
        end = raw.index(b'\n', at)
        header = raw[at:end].decode('ascii').split()
        require(len(header) == 3 and header[1] == 'blob' and re.fullmatch('[0-9a-f]{40}', header[0]),
            'rust-http-historical-blob')
        size, at = int(header[2]), end + 1
        require(0 <= size <= 4 * 1024**2 and at + size < len(raw), 'rust-http-historical-size')
        body = raw[at:at + size]
        actual = hashlib.sha1(b'blob ' + str(size).encode() + b'\0' + body).hexdigest()
        require(actual == header[0] and raw[at + size:at + size + 1] == b'\n',
            'rust-http-historical-identity')
        files[name] = body
        at += size + 1
    require(at == len(raw), 'rust-http-historical-complete')
    return files


def historical_plan(raw):
    require(hashlib.sha256(raw).hexdigest() == WORKFLOW_SHA256, 'rust-http-historical-workflow')
    marker, end = b"          python3 -B - <<'PY'\n", b'\n          PY'
    require(raw.count(marker) == 1 and raw.count(end) == 1, 'rust-http-historical-block')
    block = raw.split(marker, 1)[1].split(end, 1)[0].decode('utf-8')
    calls = []
    for node in ast.walk(ast.parse(textwrap.dedent(block))):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == 'commands'
            and node.func.attr == 'run'):
            continue
        values = []
        for arg in node.args:
            if isinstance(arg, ast.Constant) and type(arg.value) is str:
                values.append(arg.value)
            elif (isinstance(arg, ast.BinOp) and isinstance(arg.left, ast.Name)
                and arg.left.id == 'root' and isinstance(arg.op, ast.Div)
                and isinstance(arg.right, ast.Constant) and arg.right.value == '.cargo/managed-guest.toml'):
                values.append('ROOT/.cargo/managed-guest.toml')
            else:
                raise ValueError('rust-http-historical-command-argument')
        require(not node.keywords and values, 'rust-http-historical-command-shape')
        calls.append((node.lineno, tuple(values)))
    plan = tuple(row for _, row in sorted(calls))
    require(tuple(row[0] for row in plan) == STAGES, 'rust-http-historical-all-stages')
    require(plan[0] == ('rust-version', 'rustc', '--version') and len(plan) == 34,
        'rust-http-historical-version-stage')
    for row in plan[1:]:
        if row[0] == 'release-preparation-protocol-reader-controls':
            require(row[1:4] == ('python3', '-B', '-c') and len(row) == 5,
                'rust-http-original-python-test-command')
        else:
            require(row[1:4] == ('cargo', '--config', 'ROOT/.cargo/managed-guest.toml')
                and '--features' not in row and '--all-features' not in row
                and '--no-default-features' not in row, 'rust-http-original-default-feature-command')
    return plan


def historical_tests(files):
    result = {}
    for stage, sources in TEST_SOURCES.items():
        names = []
        for path, prefix, needle in sources:
            names.extend(prefix + name.decode('ascii') for name in TEST_PATTERN.findall(files[path])
                if needle in name.decode('ascii'))
        require(len(names) == len(set(names)) == TEST_COUNTS[stage],
            'rust-http-original-test-inventory')
        result[stage] = frozenset(names)
    return result


def list_tests(raw, expected):
    names = [name.decode('utf-8') for name in re.findall(rb'^([^\r\n]+): test$', raw, re.M)]
    require(0 < len(names) <= 1024 and len(names) == len(set(names)) and expected <= set(names),
        'rust-http-original-test-missing-or-duplicate')
    return tuple(names)


def same_products(before, after):
    require(before == after, 'rust-http-current-native-evidence-changed')


def loaded_sources(root):
    """Record every repository Python module loaded by this owner process."""
    root = root.resolve(strict=True)
    names = set()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if not isinstance(filename, str):
            continue
        path = Path(filename).resolve()
        if path.suffix == '.py' and path.is_relative_to(root):
            names.add(path.relative_to(root).as_posix())
    return names


def toolchain_snapshot(environment, root, identify, runner=None):
    """Bind the actual rustup-selected tools and ambient Cargo configuration."""
    if runner is None:
        from tools.build_process import run_bounded_result
        runner = run_bounded_result
    rustup = shutil.which('rustup', path=environment.get('PATH'))
    require(rustup is not None, 'rust-http-current-rustup-required')
    rustup = Path(rustup).resolve(strict=True)
    result = {'rustup': {'path': str(rustup), 'identity': identify(rustup, 512 * 1024**2)}}
    for name in ('rustc', 'cargo'):
        launcher = shutil.which(name, path=environment.get('PATH'))
        require(launcher is not None, 'rust-http-current-tool-launcher')
        launcher = Path(launcher).resolve(strict=True)
        observed = runner([str(rustup), 'which', name], cwd=root, env=environment,
            timeout_seconds=30, max_output_bytes=4096)
        require(observed.returncode == 0 and 0 < len(observed.stdout) <= 4096 and len(observed.stderr) <= 4096,
            'rust-http-current-tool-path-output')
        path = Path(observed.stdout.decode('utf-8').strip()).resolve(strict=True)
        result[name] = {'path': str(path), 'identity': identify(path, 512 * 1024**2),
            'launcher': {'path': str(launcher), 'identity': identify(launcher, 512 * 1024**2)}}
    cargo_home = Path(environment.get('CARGO_HOME') or (Path(environment['HOME']) / '.cargo')).resolve()
    result['cargoHomeConfig'] = {}
    for name in ('config', 'config.toml'):
        path = cargo_home / name
        result['cargoHomeConfig'][name] = identify(path, 4 * 1024**2) if path.exists() else None
    return result


def qualify(prepared, output, revision):
    # Deferred imports keep the inventory/parser tests independent of a build.
    from tools import c_timed_current_products as current, qualify_host_codec_native as producer
    from tools.build_observation import build_environment
    from tools.phase3_resource_identity import file_identity
    from tools.rust_capsule_build import Commands
    from tools.rust_capsule_project import ROOT, checked_path, fresh, write_json

    require(sys.platform == 'linux' and sys.version_info[:3] == (3, 13, 5) and os.geteuid() != 0,
        'rust-http-current-linux-unprivileged-python3135')
    require(re.fullmatch('[0-9a-f]{40}', revision) is not None, 'rust-http-current-revision')
    prepared, output = checked_path(prepared), checked_path(output)
    for path in (prepared, output):
        require(path != ROOT and path not in ROOT.parents and ROOT not in path.parents and not path.exists(),
            'rust-http-current-fresh-outside-checkout')
    require(prepared != output and prepared not in output.parents and output not in prepared.parents,
        'rust-http-current-disjoint-outputs')
    started = time.monotonic()
    head, _ = current.current_source()
    require(head == revision, 'rust-http-current-exact-head')
    names = {WORKFLOW, *(path for sources in TEST_SOURCES.values() for path, _, _ in sources)}
    historical = historical_files(ROOT, names)
    plan, tests = historical_plan(historical[WORKFLOW]), historical_tests(historical)
    own = {WORKFLOW, CURRENT_WORKFLOW, 'tools/qualify_rust_capsules.py', 'tools/rust_http_current_controls.py',
        'tools/tests/test_rust_http_current_controls.py', 'tools/sdk_native_products_reader.py',
        'tools/tests/test_sdk_native_products_reader.py'} | loaded_sources(ROOT)
    materials = producer.materials(ROOT) | {name: file_identity(ROOT / name) for name in own}
    current.committed_materials(head, materials)
    target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()
    output = fresh(output)
    stage = 'current-native-producer'
    record = {'schemaVersion': 'latent.rust.http.current-native-controls.v1', 'status': 'incomplete',
        'sourceRevision': head, 'historicalSource': HISTORICAL, 'historicalWorkflowSha256': WORKFLOW_SHA256,
        'materials': materials, 'sourceBoundNativeVerified': False, 'signedQualification': False,
        'guestComponentsBuilt': 0, 'historicalReceiptRewritten': False,
        'cargoFeatureSelection': 'original-default-no-extra-feature-flags',
        'featureClosureBoundary': 'test targets may resolve different dev dependencies; identical full graphs are not claimed',
        'commands': []}
    try:
        environment = build_environment(output)
        environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
            CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        tools_before = toolchain_snapshot(environment, ROOT, file_identity)
        producer.qualify(prepared, head)
        before = current.native_evidence(prepared)
        require(before[0]['compiledSource'] == head and before[1]['compiledSourceByteExact'] is True,
            'rust-http-current-product-source')
        record.update(nativeEvidence=before[0], sourceBoundNativeVerified=True)
        native_record = current.read_json(prepared / 'native-products.json', 1024**2)
        for index in (0, 1):
            actual = tuple(native_record['commands'][index + 1]['argv'])
            original = tuple(str(ROOT / '.cargo/managed-guest.toml') if value == 'ROOT/.cargo/managed-guest.toml'
                else value for value in plan[index][1:])
            require(actual == original, 'rust-http-current-original-build-argv')
        remaining = int(1320 - (time.monotonic() - started))
        require(remaining > 0, 'rust-http-current-original-overall-deadline')
        selected_python = shutil.which('python3', path=environment.get('PATH'))
        require(selected_python is not None and Path(selected_python).resolve() == Path(sys.executable).resolve(),
            'rust-http-current-python-interpreter')
        commands = Commands(ROOT, output, environment, deadline_seconds=remaining,
            command_seconds=min(remaining, 1200))
        stages = producer.Stages(commands, output)
        for row in plan[2:]:
            stage, args = row[0], list(row[1:])
            args = [str(ROOT / '.cargo/managed-guest.toml') if x == 'ROOT/.cargo/managed-guest.toml'
                else x for x in args]
            if stage == 'release-preparation-protocol-reader-controls':
                result = stages.run(stage, *args)
                require(re.search(rb'^Ran 12 tests in [^\r\n]+$', result, re.M)
                    and re.search(rb'^OK$', result, re.M), 'rust-http-original-python-tests')
                continue
            require('--' in args, 'rust-http-original-rust-test-separator')
            split = args.index('--')
            listing = args[:split + 1] + (['--exact'] if '--exact' in args[split + 1:] else []) + ['--list']
            expected = tests.get(stage)
            if expected is None:
                require('--exact' in args[split + 1:] and split > 0, 'rust-http-exact-test-selector')
                expected = frozenset((args[split - 1],))
            observed = list_tests(stages.run(stage + '-list', *listing), expected)
            producer.exact_result(stages.run(stage + '-run', *args), observed)
        stage = 'final-source-products-and-deadline'
        require(time.monotonic() - started < 1320, 'rust-http-current-original-overall-deadline')
        same_products(before, current.native_evidence(prepared))
        require(tools_before == toolchain_snapshot(environment, ROOT, file_identity)
            and target == Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve(),
            'rust-http-current-original-tools-and-target')
        require(loaded_sources(ROOT) <= own
            and materials == producer.materials(ROOT) | {name: file_identity(ROOT / name) for name in own},
            'rust-http-current-materials-changed')
        record.update(status='passed', commands=stages.records, elapsedSeconds=time.monotonic() - started,
            historicalCommandStages=len(plan), currentCodecControls=native_record['controlCount'],
            toolchain=tools_before)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, signedQualification=False)
        try:
            write_json(output / 'FAILED.json', record)
        except OSError:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    options = parser.parse_args()
    qualify(options.prepared, options.output, options.revision)
