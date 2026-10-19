"""Replay one authenticated failed Fetch component; numeric frames, never qualification."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
import re
from pathlib import Path
import shutil
import secrets
import sys
import tempfile
import tomllib
import time

# The workflow preserves this helper outside the checkout before selecting the
# original tested tree. All runtime/configuration modules below are that tree's.
sys.path.insert(0, str(Path.cwd()))

from tools import diagnose_go_entry_frames as frames
from tools import diagnose_go_timer_failure as host
from tools import qualify_typescript_fetch_runtime as fetch
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError, require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file

TESTED = '0754391a20027a539f1d5b7c0426719a4bd6c3c1'
COMPONENT = {'sha256': 'sha256:467e52be57ded5ed89a0f63bbaa72f0b7e5d4921dd70168859ee326b1d9d59a9',
             'bytes': 12350291}
PACKAGE_INPUTS = 'sha256:f49ba2474ab58f5ba5186cf4303f62d03c84aaf14acddd6bd2a8f0bb094aef25'
FAILED = 'sha256:2ee91078f9d0b52f625a50e6a3c3e46b9d33f17e4e0fc85011b91a5bb9d51489'
WIT_INPUTS = {
    'wit/deps/activation/package.wit': 'wit/platform/activation-runtime/package.wit',
    'wit/deps/application/world.wit': fetch.FIXTURE+'/world.wit',
    'wit/deps/clock/package.wit': 'wit/platform/clock/package.wit',
    'wit/deps/http-v3/package.wit': 'wit/platform/http-v3/package.wit',
}


REGISTER_PATH = 'crates/latent-wasmtime/src/host/runtime.rs'
REGISTER_PREFIX = b'LSF_FETCH_REGISTER_FAILURE '
OWNER_KINDS = frozenset({'task', 'managed-idle-worker', 'executor', 'queued-work', 'wait', 'timer', 'result', 'native'})
ERROR_CODES = frozenset({'unavailable', 'permission-denied', 'resource-exhausted', 'cancelled',
                         'deadline', 'invalid-token', 'invalid-state'})
REGISTER_BEFORE = """            let owner = table
                .runtime
                .register(owner_kind(kind), continuation.map(token))?;
"""
REGISTER_AFTER = """            let kind_label = match &kind {
                wit::OwnerKind::Task => "task",
                wit::OwnerKind::ManagedIdleWorker => "managed-idle-worker",
                wit::OwnerKind::Executor => "executor",
                wit::OwnerKind::QueuedWork => "queued-work",
                wit::OwnerKind::Wait => "wait",
                wit::OwnerKind::Timer => "timer",
                wit::OwnerKind::Result => "result",
                wit::OwnerKind::Native => "native",
            };
            let registered = table.runtime.register(owner_kind(kind), continuation.map(token));
            if let Err(error) = &registered {
                // Private observer only. register returned and released its lock.
                // Read only the existing bounded counters; retain no token/text.
                let owners = table.runtime.snapshot().owners;
                static RECORDS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
                if owners.iter().all(|count| *count <= 8192)
                    && owners.iter().map(|count| u64::from(*count)).sum::<u64>() <= 8192
                    && RECORDS.fetch_update(std::sync::atomic::Ordering::Relaxed,
                        std::sync::atomic::Ordering::Relaxed,
                        |seen| if seen < 16 { Some(seen + 1) } else { None }).is_ok()
                {
                    let code = match &error.code {
                        PlatformErrorCode::Unavailable => "unavailable",
                        PlatformErrorCode::PermissionDenied | PlatformErrorCode::AdmissionRejected => "permission-denied",
                        PlatformErrorCode::ResourceExhausted => "resource-exhausted",
                        PlatformErrorCode::Cancelled => "cancelled",
                        PlatformErrorCode::DeadlineExceeded => "deadline",
                        PlatformErrorCode::InvalidArgument => "invalid-token",
                        _ => "invalid-state",
                    };
                    eprintln!("LSF_FETCH_REGISTER_FAILURE {}", serde_json::json!({
                        "ownerKind": kind_label, "errorCode": code, "owners": owners
                    }));
                }
            }
            let owner = registered?;
"""


def registration_overlay(root: Path, output: Path) -> tuple[dict, tuple[Path, Path]]:
    original = read_file(root/REGISTER_PATH)
    text = original.decode()
    require(text.count(REGISTER_BEFORE) == 1, 'fetch-frame-registration-preimage')
    derived = text.replace(REGISTER_BEFORE, REGISTER_AFTER, 1).encode()
    private = output/'runtime-registration.rs'
    private.write_bytes(derived)
    return {REGISTER_PATH: {'original': digest(original), 'private': digest(derived)}}, (private, root/REGISTER_PATH)


def registration_failures(data: bytes) -> dict:
    require(type(data) is bytes and len(data) <= 262144, 'fetch-register-capture-limit')
    rows = [line[len(REGISTER_PREFIX):] for line in data.splitlines() if line.startswith(REGISTER_PREFIX)]
    require(len(rows) <= 16 and all(len(row) <= 512 for row in rows), 'fetch-register-record-limit')
    records = []
    for row in rows:
        value = json.loads(row)
        require(isinstance(value, dict) and set(value) == {'ownerKind', 'errorCode', 'owners'}
            and value['ownerKind'] in OWNER_KINDS and value['errorCode'] in ERROR_CODES
            and isinstance(value['owners'], list) and len(value['owners']) == 7
            and all(type(n) is int and 0 <= n <= 8192 for n in value['owners'])
            and sum(value['owners']) <= 8192, 'fetch-register-closed-record')
        records.append(value)
    return {'scope': 'private-host-registration-refusals-only', 'records': records,
            'qualification': False, 'causeInferredFromAbsence': False}



def frame_capture(data: bytes) -> dict:
    """Read bounded closed records, retaining at most 32 numeric frames total."""
    require(type(data) is bytes and len(data) <= 262144, 'fetch-frame-private-stderr-bound')
    rows = [line for line in data.splitlines() if line.startswith(frames.PREFIX)]
    record = {'stderrBytes': len(data), 'observedRecords': len(rows), 'retainedFrameLimit': 32,
              'records': [], 'status': 'absent' if not rows else 'observed', 'rawOutputRetained': False}
    if len(rows) > 16:
        return {**record, 'status': 'refused-record-limit'}
    remaining = 32
    for row in rows:
        try:
            value = frames.numeric_frames(row+b'\n')
        except (ValueError, TypeError, KeyError, WorkflowError):
            return {**record, 'status': 'refused-closed-record', 'records': []}
        count = len(value['frames'])
        record['records'].append({**value, 'frames': value['frames'][:remaining],
                                  'truncated': value['truncated'] or count > remaining})
        remaining -= min(count, remaining)
    return record


def private_host_markers(binary: Path) -> dict:
    markers = {'numericFrames': frames.PREFIX, 'registrationFailures': REGISTER_PREFIX}
    found = {name: False for name in markers}
    total, carry = 0, b''
    with binary.open('rb') as source:
        while chunk := source.read(65536):
            total += len(chunk)
            require(total <= 512*1024**2, 'fetch-frame-private-host-size')
            window = carry+chunk
            for name, value in markers.items():
                found[name] = found[name] or value in window
            carry = window[-max(map(len, markers.values())):]
    return found


def private_build_command(root, overlays, environment, tools, context):
    require(len(overlays) == 3 and [original.relative_to(root).as_posix() for _, original in overlays]
            == [*frames.PATHS, REGISTER_PATH], 'fetch-frame-three-overlay-set')
    command = frames.build_command(root, overlays[:2], environment, tools, context)
    # Keep the reviewed host boundary and all ordinary build/preflight arguments.
    # The sole addition is the exact third read-only source overlay.
    index = command.index('--chdir')
    private, original = overlays[2]
    return command[:index] + ['--ro-bind', str(private), str(original)] + command[index:]


def package_materials(artifact: Path) -> dict[str, bytes]:
    """Restore omitted WIT assets only when every original byte is authenticated."""
    raw = read_file(artifact/'package-inputs.json')
    require(digest(raw) == PACKAGE_INPUTS, 'fetch-frame-original-package-manifest')
    manifest = json.loads(raw)
    expected = {'component.wasm', 'capsule.json', 'contracts.json', 'wit-lock.json',
        'compatibility-report.json', 'typescript-runtime-selection.json', 'package-source.json',
        'wit/world.wit', *WIT_INPUTS}
    require(isinstance(manifest, dict) and set(manifest) == expected, 'fetch-frame-package-source-set')
    selected = ('package examples:lsf-typescript-activation@1.0.0;\n\nworld selected {\n'
        '    include examples:typescript-fetch/service@1.0.0;\n'
        '    import latent:runtime/activation@0.1.0;\n'
        '    import latent:clock/monotonic@0.1.0;\n'
        '    import latent:clock/wall@0.1.0;\n}\n').encode()
    materials = {'wit/world.wit': selected}
    materials.update({name: read_file(ROOT/source) for name, source in WIT_INPUTS.items()})
    for name in expected-materials.keys():
        materials[name] = read_file(artifact/name, 16*1024**2)
    require(json.loads(inventory(materials)) == manifest, 'fetch-frame-package-bytes-changed')
    require(file_identity(artifact/'component.wasm', 16*1024**2) == COMPONENT,
            'fetch-frame-original-component')
    return materials


def package(artifact: Path, binary: Path, output: Path) -> None:
    materials = package_materials(artifact)  # Validate all inputs before any write/build.
    require(all(not (artifact/name).exists() for name in materials if name.startswith('wit/')),
            'fetch-frame-restored-source-already-exists')
    for name, raw in materials.items():
        if name.startswith('wit/'):
            target = artifact/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    environment = build_environment(output)
    for command in (['build', artifact/'package-source.json', artifact, artifact/'package'],
                    ['inspect', artifact/'package']):
        result = run_bounded_result([str(binary), *map(str, command)], output, environment, 30, 65536)
        require(result.returncode == 0, 'fetch-frame-original-package-rebuild')
    require(package_materials(artifact) == materials, 'fetch-frame-package-changed-after-rebuild')


def replay(artifact: Path, binaries: dict, output: Path) -> dict:
    """Replay only the failed JSON vector; it can never qualify the real gate."""
    output = fresh(output)
    expires = time.monotonic()+90
    record = {'qualification': False, 'status': 'incomplete', 'rawNodeOutputRetained': False}
    service = None
    try:
        environment = build_environment(output)
        signed = output/'releases'
        built = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, 30, 65536)
        require(built.returncode == 0, 'fetch-frame-original-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-fetch-frames-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'):
                (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii')
            credential.chmod(0o600)
            client = fetch.RecordingClient(binaries['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            peer = Process([sys.executable, str(ROOT/'tools/java_standard_http_peer.py'), '--credential', str(credential)],
                work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(expires, time.monotonic()+10))
            config = fetch.configuration(work/'node', signed, startup, credential)
            configured = json.loads(read_file(config))['providers']['activationRuntime']['limits']
            require(isinstance(configured, dict) and set(configured) == set(fetch.OWNER_LIMITS)
                    and all(type(value) is int and 0 <= value <= 8192 for value in configured.values()),
                    'fetch-frame-actual-runtime-owner-limits')
            record['runtimeOwnerLimits'] = configured
            service = fetch.connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(service.close)
            source = signed/'typescript-fetch'
            publication = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'fetch-frame-publish', '--expected-generation', '0')['data']['operation']['publication']['id']
            origin = startup['origins']['primary']
            _runtime, authorized = fetch.grants(client, service, publication, origin)
            target = fetch.deploy(client, source/'deployment.json', publication, grants=authorized)
            record['entry'] = fetch.call(client, target, 'typescript-fetch', 'run',
                [0, f"http://{origin['host']}:{origin['port']}/conformance/json"], 'fetch-json')
            require(record['entry']['response']['data']['resolvedRevision']['releaseDigest'] == COMPONENT['sha256'],
                    'fetch-frame-replay-release')
            record['status'] = 'observed'
            # The ordinary stop/complete path drains both pipes before closing.
            # Emergency close alone can discard a trailing diagnostic record.
            fetch.stop(client, service)
    finally:
        if service is not None:
            record['nodeReaped'] = service.owner.finished
            try:
                record['registrationFailures'] = registration_failures(bytes(service.buffers[1]))
            except (ValueError, TypeError, KeyError, WorkflowError):
                record['registrationCapture'] = 'unavailable-or-refused'
            # Only the existing strict numeric parser observes private stderr.
            # No raw buffer is written to any artifact, including failures.
            try:
                capture = frame_capture(bytes(service.buffers[1]))
                record['numericFrameCapture'] = capture
                if capture['status'] == 'observed' and len(capture['records']) == 1:
                    record['numericFrames'] = capture['records'][0]
            except (ValueError, TypeError, KeyError, WorkflowError):
                record['frameCapture'] = 'refused-stream-bound'
        write_json(output/'observation.json', record)
    return record


def retain_private_cargo(built, output: Path, environment: dict, *, stage: str = 'build') -> dict:
    """Retain bounded compiler output only, redacting known credential values.

    This runs before signing, node startup or peer credentials exist. These
    files are private setup diagnostics and are never runtime qualification.
    """
    require(stage in {'build', 'fetch'}, 'fetch-frame-private-compiler-stage')
    secrets = []
    for key, value in environment.items():
        if re.search(r'(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTHORIZATION|API_KEY|PRIVATE_KEY)(_|$)', key, re.I):
            require(type(value) is str and len(value) <= 32768, 'fetch-frame-redaction-value-limit')
            if value:
                secrets.append(value.encode())
    result = {}
    for label, raw in [('stdout', built.stdout), ('stderr', built.stderr)]:
        require(type(raw) is bytes and len(raw) <= 1048576, 'fetch-frame-private-compiler-output-bound')
        for value in sorted(set(secrets), key=len, reverse=True):
            raw = raw.replace(value, b'[REDACTED]')
        truncated = len(raw) > 1048576
        path = output/('private-'+stage+'.'+label+'.txt')
        path.write_bytes(raw[:1048576])
        result[label] = {**file_identity(path), 'redactedOutputTruncated': truncated}
    return {'scope': 'private-bounded-compiler-setup-only', 'knownCredentialValuesRedacted': True,
            'streams': result, 'qualification': False}


def cargo_setup_observation(built) -> dict:
    """Project fixed compiler/setup tokens only; never retain Cargo output."""
    data = built.stdout+b'\n'+built.stderr
    require(len(data) <= 2*1024**2+1, 'fetch-frame-build-capture-limit')
    categories = []
    for label, tokens in (
        ('offline-dependency-unavailable', (b'error: no matching package named ',
            b'attempting to make an HTTP request, but --offline was specified',)),
        ('locked-update-required', (b'the lock file ', b'needs to be updated but --locked was passed',)),
        ('missing-source-path', (b'failed to read ', b'No such file or directory',)),
        ('custom-build-command-failed', (b'failed to run custom build command for ',)),
        ('linker-failed', (b'linking with ', b'failed: exit status:',)),
    ):
        if (any(token in data for token in tokens) if label == 'offline-dependency-unavailable'
                else all(token in data for token in tokens)):
            categories.append(label)
    return {'categories': categories, 'stdout': {'bytes': len(built.stdout), 'sha256': digest(built.stdout)},
            'stderr': {'bytes': len(built.stderr), 'sha256': digest(built.stderr)}, 'rawOutputRetained': False}



def locked_registry_inputs(root: Path) -> dict:
    """Authenticate data-only registry hydration; no git/unlocked dependency."""
    raw = read_file(root/'Cargo.lock', 1024*1024)
    require(digest(raw) == 'sha256:9ca94752fc918c521dd365eab93c8b92dfdde8c770df1377a10c8b44fe85b4d8',
            'fetch-frame-original-lock')
    packages = tomllib.loads(raw.decode())['package']
    require(0 < len(packages) <= 2048 and all(not item.get('source') or (
        item['source'] == 'registry+https://github.com/rust-lang/crates.io-index'
        and re.fullmatch(r'[a-f0-9]{64}', item.get('checksum', ''))) for item in packages),
        'fetch-frame-checksummed-registry-only')
    return {'lock': file_identity(root/'Cargo.lock'), 'packages': len(packages),
            'registryPackages': sum(bool(item.get('source')) for item in packages),
            'target': 'x86_64-unknown-linux-gnu', 'locked': True, 'buildScriptsExecuted': False}


def private_target(root: Path, output: Path, environment: dict) -> tuple[Path, str]:
    """Use cached outputs when present, otherwise build only in fresh private storage.

    Registry inputs must already be cached: the unchanged command remains
    offline/locked and the same 450-second build and 600-second overall limits
    apply. A cache miss grants neither network acquisition nor passing credit.
    """
    target = Path(environment.get('CARGO_TARGET_DIR', str(root/'target'))).resolve()
    if target.is_dir():
        return target, 'existing-target'
    return fresh(output/'private-target'), 'fresh-private-target'


def diagnose(attempt: Path, native: Path, output: Path) -> dict:
    output = fresh(output)
    deadline = time.monotonic()+600
    record = {'schemaVersion': 'latent.typescript.private-fetch-frames.v1',
        'qualification': False, 'status': 'incomplete', 'stage': 'inputs', 'testedCommit': TESTED,
        'component': COMPONENT, 'rawNodeOutputRetained': False, 'privateCompilerOutputRetained': True,
        'privateBinaryPublished': True, 'privateBinaryScope': 'authenticated-private-observer-only;not-production',
        'helper': file_identity(Path(__file__)),
        'limits': {'overallSeconds': 600, 'buildSeconds': 450, 'registryFetchSeconds': 60, 'frames': 32, 'registrationFailures': 16, 'ownerCount': 8192}}
    try:
        head = run_bounded_result(['git', 'rev-parse', 'HEAD'], ROOT, build_environment(output), 10, 4096)
        require(head.returncode == 0 and head.stdout.decode().strip() == TESTED,
                'fetch-frame-original-tested-source')
        require(digest(read_file(attempt/'node/FAILED.json')) == FAILED, 'fetch-frame-original-failure')
        artifact = attempt/'build'
        material = package_materials(artifact)
        originals, identity = fetch.prepared_native(native)
        record['originalNative'] = identity
        record['originalBuild'] = fetch.build_evidence(artifact) if (artifact/'package').is_dir() else None
        context = host.frame_host_context()
        tools = {name: shutil.which(name) for name in ('cargo', 'bwrap', 'sudo', 'setpriv', 'env')}
        require(all(tools.values()), 'fetch-frame-existing-host-tools')
        overlay_root = fresh(output/'source-overlays')
        sources, overlays = frames.overlay_sources(ROOT, overlay_root)
        registration_sources, registration = registration_overlay(ROOT, overlay_root)
        sources.update(registration_sources)
        overlays.append(registration)
        record['sourceOverlays'] = sources
        record['stage'] = 'private-build'
        environment = build_environment(output)
        target, target_source = private_target(ROOT, output, os.environ)
        record['existingNativeTarget'] = target_source == 'existing-target'
        record['nativeTargetSource'] = target_source
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        record['stage'] = 'locked-registry-hydration'
        registry = locked_registry_inputs(ROOT)
        fetched = run_bounded_result([tools['cargo'], 'fetch', '--locked', '--target', registry['target']],
            ROOT, environment, min(60, deadline-time.monotonic()-120), 1048576)
        record['registryHydration'] = {**registry, 'exitCode': fetched.returncode,
            'privateDiagnostics': retain_private_cargo(fetched, output, os.environ, stage='fetch')}
        require(locked_registry_inputs(ROOT) == registry, 'fetch-frame-lock-drift-after-fetch')
        require(fetched.returncode == 0, 'fetch-frame-locked-registry-hydration')
        record['stage'] = 'private-build'
        built = run_bounded_result(private_build_command(ROOT, overlays, environment, tools, context),
            ROOT, environment, min(450, deadline-time.monotonic()-120), 1048576)
        record.update(frames.private_build_observation(built))
        record['cargoSetup'] = cargo_setup_observation(built)
        record['privateCompilerDiagnostics'] = retain_private_cargo(built, output, os.environ)
        require(built.returncode == 0 and record['hostPreflight'] is not None,
                'fetch-frame-private-host-build')
        private_host = output/'private-latentd'
        shutil.copy2(target/'debug/latentd', private_host)
        record['privateHost'] = file_identity(private_host, 512*1024**2)
        require(record['privateHost'] != identity['nativeProducts']['latentd'], 'fetch-frame-private-host-unchanged')
        record['privateHostMarkers'] = private_host_markers(private_host)
        write_json(output/'private-host-identity.json', {'schemaVersion': 'latent.typescript.private-host.v1',
            'qualification': False, 'sourceCommit': TESTED, 'component': COMPONENT,
            'helper': record['helper'], 'sourceOverlays': sources, 'privateHost': record['privateHost'],
            'markers': record['privateHostMarkers'], 'originalNative': identity})
        require(all(record['privateHostMarkers'].values()), 'fetch-frame-observer-markers-missing')
        record['stage'] = 'original-package'
        package(artifact, originals['package'], output)
        record['originalBuild'] = fetch.build_evidence(artifact)
        require(time.monotonic() < deadline-120, 'fetch-frame-replay-deadline')
        record['stage'] = 'private-replay'
        record['replay'] = replay(artifact, {**originals, 'latentd': private_host}, output/'node')
        record.update(status='observed', stage='complete')
    except Exception as error:
        record['failureClass'] = type(error).__name__ if type(error).__name__ in {
            'WorkflowError', 'ValueError', 'KeyError', 'TypeError', 'OSError', 'FileNotFoundError'} else 'Other'
        known = {'fetch-frame-existing-native-target', 'go-entry-frame-source-set',
                 'go-entry-frame-environment', 'fetch-frame-three-overlay-set', 'fetch-frame-private-host-build',
                  'fetch-frame-locked-registry-hydration', 'fetch-frame-lock-drift-after-fetch',
                  'fetch-frame-original-lock', 'fetch-frame-checksummed-registry-only',
                  'fetch-frame-observer-markers-missing'}
        record['guardReason'] = (error.args[0] if len(error.args) == 1 and type(error.args[0]) is str
                                 and error.args[0] in known else 'other')
    finally:
        if 'sourceOverlays' in record:
            record['originalSourceUnchanged'] = all(digest(read_file(ROOT/name)) == value['original']
                for name, value in sources.items())
            record['originalComponentAndPackageUnchanged'] = package_materials(artifact) == material
            record['frozenBinariesUnchanged'] = fetch.prepared_native(native)[1] == identity
            require(all(record[key] for key in ('originalSourceUnchanged',
                'originalComponentAndPackageUnchanged', 'frozenBinariesUnchanged')), 'fetch-frame-input-drift')
        write_json(output/'observation.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(diagnose(args.attempt.resolve(), args.native.resolve(), args.output.resolve())))
