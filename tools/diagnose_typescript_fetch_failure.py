"""Replay one authenticated failed Fetch component; numeric frames, never qualification."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import secrets
import sys
import tempfile
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
                record['numericFrames'] = frames.numeric_frames(bytes(service.buffers[1]))
            except (ValueError, TypeError, KeyError, WorkflowError):
                record['frameCapture'] = 'unavailable-or-refused'
        write_json(output/'observation.json', record)
    return record


def diagnose(attempt: Path, native: Path, output: Path) -> dict:
    output = fresh(output)
    deadline = time.monotonic()+600
    record = {'schemaVersion': 'latent.typescript.private-fetch-frames.v1',
        'qualification': False, 'status': 'incomplete', 'stage': 'inputs', 'testedCommit': TESTED,
        'component': COMPONENT, 'rawNativeOutputRetained': False, 'privateBinaryPublished': False,
        'helper': file_identity(Path(__file__)),
        'limits': {'overallSeconds': 600, 'buildSeconds': 450, 'frames': 32, 'registrationFailures': 16, 'ownerCount': 8192}}
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
        target = Path(os.environ.get('CARGO_TARGET_DIR', str(ROOT/'target'))).resolve()
        record['existingNativeTarget'] = target.is_dir()
        require(target.is_dir(), 'fetch-frame-existing-native-target')
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        built = run_bounded_result(private_build_command(ROOT, overlays, environment, tools, context),
            ROOT, environment, min(450, deadline-time.monotonic()), 1048576)
        record.update(frames.private_build_observation(built))
        require(built.returncode == 0 and record['hostPreflight'] is not None,
                'fetch-frame-private-host-build')
        private_host = output/'private-latentd'
        shutil.copy2(target/'debug/latentd', private_host)
        record['privateHost'] = file_identity(private_host, 512*1024**2)
        require(record['privateHost'] != identity['nativeProducts']['latentd'], 'fetch-frame-private-host-unchanged')
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
                 'go-entry-frame-environment', 'fetch-frame-three-overlay-set', 'fetch-frame-private-host-build'}
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
