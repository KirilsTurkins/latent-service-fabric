"""Private replay of the unchanged failed Console component; never qualification."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import tomllib

# The manual job keeps this helper outside the checkout, then selects exactly
# the original tested tree. Runtime and packaging modules come from that tree.
sys.path.insert(0, str(Path.cwd()))

from tools import diagnose_go_entry_frames as frames
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, digest, read_file

TESTED = 'a1028e1bd854700f27e75017349c58b88b53b0d5'
ARTIFACT = 12208042991
COMPONENT = {'sha256': 'sha256:ae70bb14ba532ab9cfcef0ea342e9929c08586e77d94e03d71f444ef0076fe74',
             'bytes': 2985677}
PREIMAGES = {
    'crates/latent-wasmtime/src/containment.rs':
        'sha256:a671571e7983a77bb5041478e5b30fea9a09cc31791ec3a6ec9d3bb15985e0aa',
    'crates/latent-wasmtime/src/config/engine.rs':
        'sha256:844246d9b18864cf5c6d0b2ca43bab375eeaadf50f8b3100824f5aad00f6acc5',
}
PREFIX = b'LSF_DOTNET_CONSOLE_TRAP '
VARIANTS = (
    'cannot-enter-component', 'cannot-leave-component', 'cannot-block-sync-task',
    'no-async-result', 'async-deadlock', 'uncaught-exception', 'invalid-char',
    'string-out-of-bounds', 'list-out-of-bounds', 'invalid-discriminant',
    'unaligned-pointer', 'debug-string-encoding', 'debug-code-units',
    'debug-pointer-aligned', 'debug-upper-bits', 'unreachable-code',
    'memory-out-of-bounds', 'other-known-trap', 'not-a-wasmtime-trap',
)
TRAP_MATCH = '''
    let private_variant = match error.downcast_ref::<wasmtime::Trap>() {
        Some(wasmtime::Trap::CannotEnterComponent) => "cannot-enter-component",
        Some(wasmtime::Trap::CannotLeaveComponent) => "cannot-leave-component",
        Some(wasmtime::Trap::CannotBlockSyncTask) => "cannot-block-sync-task",
        Some(wasmtime::Trap::NoAsyncResult) => "no-async-result",
        Some(wasmtime::Trap::AsyncDeadlock) => "async-deadlock",
        Some(wasmtime::Trap::UncaughtException) => "uncaught-exception",
        Some(wasmtime::Trap::InvalidChar) => "invalid-char",
        Some(wasmtime::Trap::StringOutOfBounds) => "string-out-of-bounds",
        Some(wasmtime::Trap::ListOutOfBounds) => "list-out-of-bounds",
        Some(wasmtime::Trap::InvalidDiscriminant) => "invalid-discriminant",
        Some(wasmtime::Trap::UnalignedPointer) => "unaligned-pointer",
        Some(wasmtime::Trap::DebugAssertStringEncodingFinished) => "debug-string-encoding",
        Some(wasmtime::Trap::DebugAssertEqualCodeUnits) => "debug-code-units",
        Some(wasmtime::Trap::DebugAssertPointerAligned) => "debug-pointer-aligned",
        Some(wasmtime::Trap::DebugAssertUpperBitsUnset) => "debug-upper-bits",
        Some(wasmtime::Trap::UnreachableCodeReached) => "unreachable-code",
        Some(wasmtime::Trap::MemoryOutOfBounds) => "memory-out-of-bounds",
        Some(_) => "other-known-trap",
        None => "not-a-wasmtime-trap",
    };
'''


def overlay_sources(root: Path, output: Path):
    require(all(digest(read_file(root / name)) == expected for name, expected in PREIMAGES.items()),
            'console-private-host-original-preimage')
    sources, overlays = frames.overlay_sources(root, output)
    path = overlays[0][0]
    text = read_file(path).decode()
    require(text.count(frames.OBSERVER) == 1, 'console-private-frame-observer-preimage')
    observer = TRAP_MATCH + frames.OBSERVER.replace(frames.PREFIX.decode().strip(), PREFIX.decode().strip())
    observer = observer.replace('"available": true,', '"trapVariant": private_variant, "available": true,', 1)
    observer = observer.replace('"available": false,', '"trapVariant": private_variant, "available": false,', 1)
    path.write_bytes(text.replace(frames.OBSERVER, observer, 1).encode())
    sources[frames.PATHS[0]]['private'] = digest(read_file(path))
    return sources, overlays


def capture(data: bytes):
    require(type(data) is bytes and len(data) <= 262144, 'console-private-stderr-bound')
    rows = [line[len(PREFIX):] for line in data.splitlines() if line.startswith(PREFIX)]
    require(len(rows) <= 16, 'console-private-record-bound')
    result, remaining = [], 32
    for row in rows:
        require(len(row) <= 8192, 'console-private-record-size')
        value = json.loads(row)
        require(isinstance(value, dict) and set(value) == {'trapVariant', 'available', 'truncated', 'frames'}
                and value['trapVariant'] in VARIANTS, 'console-private-closed-trap-variant')
        variant = value.pop('trapVariant')
        # Reuse the already reviewed exact numeric-frame validator. Neither a
        # symbol, arbitrary error text nor the surrounding stderr is retained.
        numeric = frames.numeric_frames(frames.PREFIX + json.dumps(value).encode() + b'\n')
        count = len(numeric['frames'])
        result.append({'trapVariant': variant, **numeric, 'frames': numeric['frames'][:remaining],
                       'truncated': numeric['truncated'] or count > remaining})
        remaining -= min(remaining, count)
    return {'status': 'observed' if rows else 'absent', 'records': result,
            'rawNodeOutputRetained': False, 'qualification': False, 'numericFrameLimit': 32}


def inventory_rows(raw: bytes):
    value = json.loads(raw)
    require(isinstance(value, dict) and 0 < len(value) <= 4096, 'console-private-original-inventory')
    result = {}
    for name, observed in value.items():
        row = {'path': name, **observed} if isinstance(observed, dict) else {}
        require(isinstance(row, dict) and set(row) == {'path', 'digest', 'size'}
                and isinstance(row['path'], str) and row['path'] not in result
                and not row['path'].startswith('/') and '\\' not in row['path']
                and ':' not in row['path'] and all(p not in {'', '.', '..'} for p in row['path'].split('/'))
                and re.fullmatch(r'sha256:[0-9a-f]{64}', row['digest']) is not None
                and type(row['size']) is int and 0 <= row['size'] <= 4 * 1024**2,
                'console-private-original-inventory-row')
        result[row['path']] = row
    return result


def authenticated_project(original: Path, output: Path):
    """Recreate only declared public metadata; never recover private DLL/source."""
    from tools.dotnet_guest.project import create
    from tools.dotnet_standard_console_fixture import declare
    from tools.rust_capsule_project import snapshot
    source = inventory_rows(read_file(original / 'source-inputs.json'))
    recipe = inventory_rows(read_file(original / 'recipe-inputs.json'))
    project = create(output, 'greeting')
    declare(project)
    candidate = snapshot(project)
    selected = {name: raw for name, raw in candidate.items()
                if name.startswith('wit/') or name in {'capsule-project.json', 'vendor/lsf/Cargo.toml'}}
    expected_wit = {name for name in source if name.startswith('wit/')}
    require({name for name in selected if name.startswith('wit/')} == expected_wit,
            'console-private-original-WIT-membership')
    for name, raw in selected.items():
        row = source.get(name)
        require(row is not None and row['digest'] == digest(raw) and row['size'] == len(raw),
                'console-private-original-public-source-byte')
    for name in ('examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json',
                 'tools/rust_capsule_build.py'):
        raw = read_file(ROOT / name)
        require(name in recipe and recipe[name]['digest'] == digest(raw) and recipe[name]['size'] == len(raw),
                'console-private-original-packaging-recipe-byte')
    return selected


def remaining(deadline: float, maximum: float = 30):
    value = deadline - time.monotonic()
    require(value > 0, 'console-private-original-deadline')
    return min(value, maximum)


def rebuild_public_package(original: Path, binaries: dict, output: Path, deadline: float):
    """Reconstruct authenticated public layers around the original component.

    The retained build observation authenticates the original package-inputs
    inventory digest even though the artifact omitted that inventory's bytes.
    Require that digest before any new package or signature is produced.
    """
    from tools.build_observation import build_environment
    from tools.build_process import run_bounded_result
    from tools.phase3_resource_identity import file_identity
    from tools.rust_capsule_project import fresh, inventory, read_json, write_json
    output = fresh(output)
    files = authenticated_project(original, output / 'public-project')
    complete = read_json(original / 'BUILD-COMPLETE.json')
    require(complete['componentDigest'] == COMPONENT['sha256']
            and file_identity(original / 'component.wasm', 16 * 1024**2) == COMPONENT
            and complete['observationDigest'] == digest(read_file(original / 'build-observation.json'))
            and complete['sourceDigest'] == digest(read_file(original / 'source-inputs.json')),
            'console-private-original-build-bindings')
    observed = read_json(original / 'build-observation.json')
    require(observed['componentDigest'] == COMPONENT['sha256'] and observed['componentSize'] == COMPONENT['bytes'],
            'console-private-original-observation-component')
    package_rows = [row for row in observed['materials'] if row['name'] == 'package-inputs']
    require(len(package_rows) == 1 and package_rows[0]['digest'] ==
            'sha256:22470ff1ceb04a38c8a58e8a38725e719ba96a219ecc01b29dae15e54311960c'
            and package_rows[0]['size'] == 1185, 'console-private-original-package-inventory-binding')
    project = json.loads(files['capsule-project.json'])
    input_path = output / 'contracts-input.json'
    write_json(input_path, {'world': project['world'], 'sources': [
        {'path': name, 'content': raw.decode('utf-8')} for name, raw in files.items() if name.startswith('wit/')]})
    derived = output / 'derived'
    environment = build_environment(output)
    result = run_bounded_result([str(binaries['capsule_contracts']), str(input_path), str(derived)],
                                output, environment, remaining(deadline), 65536)
    require(result.returncode == 0, 'console-private-original-contract-derivation')
    surface = read_json(derived / 'surface.json')
    require(set(surface['imports']) == {'latent:clock/monotonic@0.1.0',
            'latent:random/random@0.1.0', 'latent:log/log@0.1.0'}, 'console-private-exact-original-imports')
    artifact = fresh(output / 'reconstructed-build')
    for name in ('component.wasm', 'BUILD-COMPLETE.json', 'build-observation.json',
                 'source-inputs.json', 'recipe-inputs.json', 'compatibility-report.json'):
        shutil.copyfile(original / name, artifact / name)
    for name in ('contracts.json', 'wit-lock.json'):
        shutil.copyfile(derived / name, artifact / name)
    # Exact normal public manifest projection, authenticated by the original
    # package-inputs digest below, rather than a claimed new compilation.
    manifest = read_json(ROOT / 'examples/echo-contract/capsule.json')
    manifest['metadata'] = {'name': project['service'], 'tenant': project['tenant']}
    if project['tenant'] is None:
        del manifest['metadata']['tenant']
    manifest['component'] = {'digest': COMPONENT['sha256'], 'version': project['version'], 'world': project['world']}
    manifest['exports'] = surface['exports']
    manifest['imports'] = [{'contract': name, 'optional': False} for name in surface['imports']]
    manifest['execution'].update(limits=project['limits'], threading='single-threaded', snapshotEligible=False, fusionEligible=False)
    manifest['compatibility']['minimumFabricVersion'] = tomllib.loads(files['vendor/lsf/Cargo.toml'].decode())['workspace']['package']['version']
    write_json(artifact / 'capsule.json', manifest)
    layers = [('component.wasm', 'component', 'application/wasm'),
        ('capsule.json', 'capsule-manifest', 'application/vnd.latent.capsule.manifest.v1+json'),
        ('contracts.json', 'contracts', 'application/vnd.latent.contracts.v1+json'),
        ('wit-lock.json', 'wit-lock', 'application/vnd.latent.wit-lock.v1+json'),
        ('compatibility-report.json', 'asset', 'application/vnd.latent.guest.compatibility.v1+json')]
    for name, raw in files.items():
        if name.startswith('wit/'):
            path = artifact / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            layers.append((name, 'asset', 'text/plain'))
    write_json(artifact / 'package-source.json', {'formatVersion': 1, 'kind': 'capsule',
        'name': project['name'], 'version': project['version'], 'entrypoint': 'component.wasm', 'annotations': {},
        'layers': [{'path': name, 'source': name, 'role': role, 'mediaType': media} for name, role, media in layers]})
    raw_inventory = inventory({name: read_file(artifact / name, 16 * 1024**2)
                               for name in ('package-source.json', *(row[0] for row in layers))})
    require(digest(raw_inventory) == package_rows[0]['digest'] and len(raw_inventory) == package_rows[0]['size'],
            'console-private-reconstructed-package-inventory-mismatch')
    (artifact / 'package-inputs.json').write_bytes(raw_inventory)
    deployment = read_json(ROOT / 'examples/echo-contract/deployment.json')
    deployment['metadata'] = {'name': project['name'], 'tenant': project['tenant']}
    if project['tenant'] is None:
        del deployment['metadata']['tenant']
    deployment['spec'].update(service=project['service'], release=COMPONENT['sha256'], grants=[], resources=project['limits'])
    write_json(artifact / 'deployment.json', deployment)
    for arguments in (['build', artifact / 'package-source.json', artifact, artifact / 'package'],
                      ['inspect', artifact / 'package']):
        result = run_bounded_result([str(binaries['package']), *map(str, arguments)], output, environment, remaining(deadline), 65536)
        require(result.returncode == 0, 'console-private-normal-package-assembly')
    return artifact, {'qualification': False, 'newCompilation': False, 'originalComponent': COMPONENT,
        'publicMetadataReconstructed': True, 'originalPackageInputInventoryDigest': digest(raw_inventory),
        'originalPackageDigestClaimed': False}


def replay(artifacts: Path, binaries: dict, original_build: Path, output: Path, deadline: float):
    from tools.build_observation import build_environment
    from tools.build_process import run_bounded_result
    from tools.build_process_signals import owned_cancellation
    from tools.dotnet_guest.entropy_grants import grant as entropy_grant
    from tools.dotnet_standard_console_probe import configure as logging_configure, grant as logging_grant
    from tools.guest_runtime_grants import grant as runtime_grant
    from tools.phase2_operator_process import stopped_record
    from tools.phase2_operator_scenario import connect, stop
    from tools.phase3_resource_identity import file_identity
    from tools.phase3_resource_os import Probe
    from tools.rust_capsule_node import (RecordingClient, configure, deploy, call, assert_value,
                                        sample, provider_idle, delete_all)
    from tools.rust_capsule_project import TEMPLATES, fresh, read_json, write_json, inventory
    from tools.sdk_provider_scenario import start_provider
    output = fresh(output)
    record = {'qualification': False, 'status': 'incomplete', 'originalComponent': COMPONENT,
              'newCompilation': False, 'guestProbes': [], 'rawNodeOutputRetained': False}
    environment = build_environment(output)
    for name in TEMPLATES:
        if name == 'greeting': continue
        directory = artifacts / 'builds' / name
        manifest = read_json(directory / 'package-source.json')
        selected = {key: read_file(directory / key, 64 * 1024**2) for key in (
            'package-source.json', *(layer['source'] for layer in manifest['layers']))}
        require(inventory(selected) == read_file(directory / 'package-inputs.json'),
                'console-private-companion-package-inputs')
        result = run_bounded_result([str(binaries['package']), 'build', str(directory / 'package-source.json'),
            str(directory), str(directory / 'package')], output, environment, remaining(deadline), 65536)
        require(result.returncode == 0, 'console-private-companion-package')
    signed = output / 'signed'
    ordered = [original_build if name == 'greeting' else artifacts / 'builds' / name for name in TEMPLATES]
    result = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), *map(str, ordered)],
                                output, environment, remaining(deadline), 65536)
    require(result.returncode == 0, 'console-private-fresh-normal-signing')
    service = peer = client = None
    with tempfile.TemporaryDirectory(prefix='lsf-console-private-') as temporary, \
            owned_cancellation() as cancellation, ExitStack() as cleanup:
        work = Path(temporary)
        for name in ('client', 'node', 'peer'): (work / name).mkdir(mode=0o700)
        client = RecordingClient(binaries['latent'], work / 'client', cancellation, deadline,
            evidence=output / 'controls', invocation_timeout_millis=120000)
        peer, port = start_provider(client, work / 'peer', maximum_seconds=900)
        cleanup.callback(peer.close)
        config, settings = configure(work / 'node', signed, port, runtime_grants=True,
                                     language='dotnet', noncrypto_entropy=True)
        logging_configure(settings)
        config.write_bytes(json.dumps(settings, sort_keys=True, separators=(',', ':')).encode() + b'\n')
        service = connect(client, binaries['latentd'], work / 'node', config, 'examples', 1)
        cleanup.callback(service.close)
        accounting = Probe(service, file_identity(binaries['latentd']))
        targets, publications, observations = {}, {}, {'invocations': [], 'providerIdle': []}
        try:
            for name in TEMPLATES:
                source = signed / ('my-' + name)
                published = client.call('release', 'publish-package', source / 'package', '--evidence', source / 'evidence/index.json',
                    '--operation-id', 'console-private-publish-' + name, '--expected-generation', '0')
                publication = published['data']['operation']['publication']['id']
                publications[name] = publication
                targets[name] = deploy(client, source / 'deployment.json', publication)
            # Reuse the original explicit admission helpers and their unchanged
            # denials. Only the three original phases below enter guest code.
            runtime_grant(client, service, signed, targets, publications, observations, language='dotnet')
            targets['greeting'] = entropy_grant(client, service, signed / 'my-greeting/deployment.json',
                publications['greeting'], targets['greeting'], observations)
            logging_grant(client, service, signed, targets, publications, observations)
            target = targets['greeting']
            record['grants'] = target['grants']
            record['budget'] = target['budget']
            record['retiredSamples'], record['providerIdle'] = [], []
            for mode in ('entry', 'resource', 'write'):
                row = call(client, target, 'greeting', 'greet', ['console-phase:' + mode], 'dotnet-console-phase-' + mode)
                require(row['processReaped'] and row['response']['data']['resolvedRevision']['releaseDigest'] == COMPONENT['sha256']
                        and int(row['response']['data']['consumption']['outboundRequests']) == 0,
                        'console-private-original-component-retirement')
                if mode != 'write':
                    expected = 'console-phase:entry' if mode == 'entry' else 'console-phase:resource:Gr\u00fc\u00dfe'
                    assert_value(client, row, [{'ok': expected}])
                record['guestProbes'].append({'phase': mode, 'invocation': row})
                record['retiredSamples'].append(sample(client, accounting, 'console-private-' + mode, 5))
                record['providerIdle'].append(provider_idle(client))
            delete_all(client, [target['name'] for target in targets.values()])
            stop(client, service)
            record['shutdown'] = stopped_record(service)
            require(record['shutdown']['reaped'] and record['shutdown']['record']['clean'], 'console-private-clean-shutdown')
            peer.stop()
            record['peerReaped'] = peer.owner.finished
            record['status'] = 'observed'
        finally:
            if service is not None:
                if not service.owner.finished:
                    try:
                        service.stop()  # complete drains before ExitStack close.
                    except Exception:
                        record['shutdownIncomplete'] = True
                record['nodeReaped'] = service.owner.finished
                try:
                    record['privateTrapCapture'] = capture(bytes(service.buffers[1]))
                except (ValueError, TypeError, KeyError, RuntimeError):
                    record['privateTrapCapture'] = {'status': 'refused', 'rawNodeOutputRetained': False}
            write_json(output / 'observation.json', record)
    return record


def validate_reuse(value, binary: Path, sources: dict, native: dict, support: dict):
    from tools.phase3_resource_identity import file_identity
    require(isinstance(value, dict) and set(value) == {'qualification', 'sourceCommit', 'component',
        'sourceOverlays', 'privateHost', 'originalNativeInputs', 'observerPrefix', 'support', 'scope'}
        and value['qualification'] is False and value['sourceCommit'] == TESTED
        and value['component'] == COMPONENT and value['sourceOverlays'] == sources
        and value['originalNativeInputs'] == native and value['support'] == support
        and value['observerPrefix'] == PREFIX.decode().strip()
        and value['scope'] == 'private-diagnostic-only;not-production'
        and value['privateHost'] == file_identity(binary, 512 * 1024**2),
        'console-private-reuse-identity')
    return value['privateHost']


def diagnose(acquired: Path, output: Path, reuse_host: Path | None = None, reuse_identity: Path | None = None):
    from tools.build_observation import build_environment
    from tools.build_process import run_bounded_result
    from tools.phase3_resource_identity import file_identity
    from tools.qualify_dotnet_standard_console import inherited
    from tools.rust_capsule_project import fresh, write_json
    from tools import diagnose_go_timer_failure as host
    output = fresh(output)
    deadline = time.monotonic() + 600
    record = {'schemaVersion': 'latent.dotnet.private-console-trap.v1', 'qualification': False,
        'status': 'incomplete', 'stage': 'inputs', 'compiledComponentSource': TESTED,
        'currentPrivateHostOriginalSource': TESTED, 'originalComponent': COMPONENT,
        'observerHelper': file_identity(Path(__file__)),
        'publicErrorsChanged': False, 'newDotnetCompilation': False, 'rawNodeOutputRetained': False,
        'limits': {'overallSeconds': 600, 'registryFetchSeconds': 60, 'privateBuildSeconds': 450,
                   'replayReserveSeconds': 120, 'records': 16, 'numericFrames': 32}}
    try:
        environment = build_environment(output)
        head = run_bounded_result(['git', 'rev-parse', 'HEAD'], ROOT, environment, 10, 4096)
        require(head.returncode == 0 and head.stdout.decode().strip() == TESTED,
                'console-private-original-source-checkout')
        normal = acquired / 'dotnet-capsule-dependencies'
        original = acquired / 'dotnet-standard-console/build'
        binaries, _companions, inherited_inputs = inherited(normal)
        record['originalNativeInputs'] = inherited_inputs
        record['originalFailure'] = file_identity(acquired / 'dotnet-standard-console/node/controls/dotnet-console-phase-write.json')
        record['stage'] = 'original-public-package-reconstruction'
        artifact, package_proof = rebuild_public_package(original, binaries, output / 'public-package', deadline)
        record['originalPublicPackage'] = package_proof
        support_path = Path(__file__).with_name('console_diagnostic_support.py')
        require(digest(read_file(support_path)) ==
            'sha256:aaa83450477a6fcaa6bf5b132ca3fb69326dd0342daaa047f05388e5dc990d3e',
            'console-private-reviewed-build-support')
        # Three unchanged generic function bodies extracted from exact
        # 1c420914. No Fetch fixture import or source identity is used.
        import console_diagnostic_support as support
        overlays_root = fresh(output / 'overlays')
        sources, overlays = overlay_sources(ROOT, overlays_root)
        record['privateSourceOverlays'] = sources
        tools = {name: shutil.which(name) for name in ('cargo', 'bwrap', 'sudo', 'setpriv', 'env')}
        require(all(tools.values()), 'console-private-required-host-tools')
        context = host.frame_host_context()
        target, target_source = support.private_target(ROOT, output, os.environ)
        record['targetSource'] = target_source
        environment.update(CARGO_TARGET_DIR=str(target), CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0',
            CARGO_PROFILE_TEST_DEBUG='0', CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true', CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true',
            CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        require((reuse_host is None) == (reuse_identity is None), 'console-private-reuse-pair')
        if reuse_host is None:
            record['stage'] = 'locked-registry-hydration'
            registry = support.locked_registry_inputs(ROOT)
            build_remaining = deadline - time.monotonic() - 120
            require(build_remaining > 0, 'console-private-original-deadline')
            fetched = run_bounded_result([tools['cargo'], 'fetch', '--locked', '--target', registry['target']],
                ROOT, environment, min(60, build_remaining), 1048576)
            record['registryHydration'] = {**registry, 'exitCode': fetched.returncode,
                'privateDiagnostics': support.retain_private_cargo(fetched, output, os.environ, stage='fetch')}
            require(fetched.returncode == 0 and support.locked_registry_inputs(ROOT) == registry,
                    'console-private-locked-registry-inputs')
            record['stage'] = 'private-host-build'
            build_remaining = deadline - time.monotonic() - 120
            require(build_remaining > 0, 'console-private-original-deadline')
            built = run_bounded_result(frames.build_command(ROOT, overlays, environment, tools, context),
                ROOT, environment, min(450, build_remaining), 1048576)
            record['buildObservation'] = frames.private_build_observation(built)
            record['privateCompilerDiagnostics'] = support.retain_private_cargo(built, output, os.environ)
            require(built.returncode == 0 and record['buildObservation']['hostPreflight'] is not None,
                    'console-private-locked-host-build')
            private_host = output / 'private-latentd'
            shutil.copy2(target / 'debug/latentd', private_host)
            private_host.chmod(0o700)
        else:
            from tools.rust_capsule_project import read_json
            private_host = output / 'private-latentd'
            identity = read_json(reuse_identity)
            validate_reuse(identity, reuse_host, sources, inherited_inputs, file_identity(support_path))
            shutil.copyfile(reuse_host, private_host)
            private_host.chmod(0o700)
            record['privateHostReused'] = True
        record['privateHost'] = file_identity(private_host, 512 * 1024**2)
        found, carry = False, b''
        with private_host.open('rb') as source:
            while chunk := source.read(65536):
                window = carry + chunk
                found |= PREFIX in window
                carry = window[-len(PREFIX):]
        require(found and record['privateHost'] != inherited_inputs['binaries']['latentd'],
                'console-private-observer-binary-marker')
        write_json(output / 'private-host-identity.json', {'qualification': False,
            'sourceCommit': TESTED, 'component': COMPONENT, 'sourceOverlays': sources,
            'privateHost': record['privateHost'], 'originalNativeInputs': inherited_inputs,
            'observerPrefix': PREFIX.decode().strip(), 'support': file_identity(support_path),
            'scope': 'private-diagnostic-only;not-production'})
        record['stage'] = 'same-component-private-replay'
        require(time.monotonic() < deadline - 30, 'console-private-replay-deadline')
        record['replay'] = replay(normal, {**binaries, 'latentd': private_host}, artifact,
                                  output / 'node', deadline)
        require(inherited(normal)[2] == inherited_inputs
                and all(digest(read_file(ROOT / name)) == value['original'] for name, value in sources.items())
                and file_identity(original / 'component.wasm', 16 * 1024**2) == COMPONENT,
                'console-private-original-inputs-mutated')
        require(time.monotonic() < deadline, 'console-private-original-deadline')
        record.update(status='observed', stage='complete')
    except Exception as error:
        record['failureCategory'] = type(error).__name__
        record['guardReason'] = error.args[0] if isinstance(error, RuntimeError) and len(error.args) == 1 \
            and isinstance(error.args[0], str) and re.fullmatch(r'console-private-[a-zA-Z0-9-]{1,96}', error.args[0]) else 'other'
    finally:
        record['elapsedSeconds'] = round(time.monotonic() - (deadline - 600), 3)
        write_json(output / 'observation.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquired', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--reuse-private-host', type=Path)
    parser.add_argument('--reuse-private-host-identity', type=Path)
    arguments = parser.parse_args()
    value = diagnose(arguments.acquired.resolve(), arguments.output.resolve(),
                     arguments.reuse_private_host, arguments.reuse_private_host_identity)
    print(json.dumps({'status': value['status'], 'stage': value['stage'], 'qualification': False}))
