"""Native authenticated npm acquisition followed by offline signed lifecycle."""
from __future__ import annotations
import argparse
import base64
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import application_dependencies as dependencies
from tools.application_dependency_store import directory_files
from tools.build_observation import build_environment
from tools.build_snapshot import canonical
from tools.npm_private_registry_fixture import TOKEN_SLOT, CONDITION, VERSIONS, archive, packages, server
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_typescript_dependencies import prepared_native
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, write_json
from tools.typescript_dependency_authoring import source_files
from tools.typescript_guest.build import build
from tools.typescript_guest.project import create

MATERIALS = ('tools/qualify_npm_private_dependencies.py', 'tools/npm_private_registry_fixture.py',
    'tools/typescript_registry_tls.py', 'tools/typescript_application_dependencies.py',
    'tools/npm_lock_authoring.py', 'tools/typescript_dependency_authoring.py',
    'tools/run_rust_capsule_workflow.py')


def frozen(prepared):
    products, identity = prepared_native(prepared)
    receipt = read_json(prepared / 'qualification.json')
    companions = [prepared / 'builds' / name for name in TEMPLATES if name != 'greeting']
    require(all(read_json(path / 'BUILD-COMPLETE.json') == receipt['builds'][path.name]
                for path in companions), 'private-npm-frozen-companion-drift')
    return receipt, products, companions, identity


def author(commands, stage, *arguments, token=None, expected=0, confidential=()):
    ordinal = len(commands.records)
    previous = commands.environment.pop(TOKEN_SLOT, None)
    if token is not None:
        commands.environment[TOKEN_SLOT] = token
    try:
        try:
            try:
                commands.run(stage, sys.executable, ROOT / 'tools/typescript_capsule.py', *arguments)
            except ValueError:
                require(len(commands.records) == ordinal + 1
                        and commands.records[-1]['exitCode'] == expected and expected != 0,
                        'private-npm-unexpected-native-command-failure')
            require(commands.records[-1]['exitCode'] == expected, 'private-npm-native-command-outcome')
        finally:
            # Always sanitize retained command streams, including unexpected failures.
            exposed = False
            for stream in ('stdout', 'stderr'):
                path = commands.output / 'logs' / f'{ordinal:02d}-{stage}.{stream}.txt'
                if path.is_file() and any(secret in read_file(path) for secret in confidential):
                    path.write_bytes(b'private-command-output-redacted\n')
                    exposed = True
            require(not exposed, 'private-npm-public-command-secret')
    finally:
        commands.environment.pop(TOKEN_SLOT, None)
        if previous is not None:
            commands.environment[TOKEN_SLOT] = previous


def accepted(app):
    return {name: read_file(app / name) for name in (dependencies.MANIFEST, dependencies.LOCK,
        'package.json', 'package-lock.json', 'npm-resolved.lock.json', 'sdk-lock.json')}


def capture_phase(commands, app, candidate, policy, node, npm, token, confidential, *, condition=True):
    author(commands, candidate.stem + '-lock', 'lock', app, '--node', node, '--npm', npm,
           '--registry-config', policy, token=token, confidential=confidential)
    author(commands, candidate.stem + '-resolve', 'resolve', app, '--candidate', candidate,
           '--node', node, '--npm', npm, '--registry-config', policy,
           *(('--condition', CONDITION) if condition else ()), token=token, confidential=confidential)
    lock = read_json(candidate, dependencies.MAX_LOCK)
    require(not lock['executableInputs'], 'private-npm-unexpected-generator')
    author(commands, candidate.stem + '-wrong-review', 'review-lock', app, '--candidate', candidate,
           '--expect', 'sha256:' + '0'*64, expected=1, confidential=confidential)
    author(commands, candidate.stem + '-review', 'review-lock', app, '--candidate', candidate,
           '--expect', digest(read_file(candidate)), confidential=confidential)
    author(commands, candidate.stem + '-verify', 'dependencies', app, confidential=confidential)
    return lock


def integrity_controls(commands, app, lock, confidential):
    """The ordinary accepted-lock consumer must refuse damaged owned inputs."""
    from tools.application_dependency_store import Store
    before = accepted(app)
    selected = next(row for row in lock['artifacts']
                    if row['metadata'].get('assetType') == 'selected-node-modules'
                    and row['role'] == 'application')
    entry = selected['files'][0]
    store = Store(app / 'dependency-inputs/objects', create=False)
    path = store.path(entry['digest'])
    raw = store.get(entry['digest'], entry['size'])
    rows = []
    for case in ('missing-cas-object', 'tampered-cas-object', 'changed-public-ca'):
        ca = app / 'registry-trust/roots.pem'
        original_ca = read_file(ca)
        try:
            if case == 'missing-cas-object':
                path.unlink()
            elif case == 'tampered-cas-object':
                path.write_bytes(raw + b'changed-owned-object')
            else:
                ca.write_bytes(original_ca + b'\n')
            author(commands, case, 'dependencies', app, expected=1, confidential=confidential)
            require(accepted(app) == before, 'private-npm-integrity-replaced-accepted-lock')
        finally:
            if case == 'changed-public-ca':
                ca.write_bytes(original_ca)
            else:
                path.write_bytes(raw)
        author(commands, case + '-restored', 'dependencies', app, confidential=confidential)
        rows.append({'case': case, 'acceptedLockPreserved': True, 'exactRestorationVerified': True})
    return rows


def preserved(app, target, lock, confidential):
    files = source_files(app)
    files.update({'dependency-inputs/objects/' + name: raw
                  for name, raw in directory_files(app / 'dependency-inputs/objects').items()})
    require(all(secret not in raw for raw in files.values() for secret in confidential), 'private-npm-secret-captured')
    target.mkdir(mode=0o700)
    for name, raw in files.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    verified = dependencies.verify_inputs(target, 'typescript')
    require(verified is not None and verified.lock == lock, 'private-npm-preserved-closure-drift')
    return target


def capture(output, commands, node, npm):
    nonce = secrets.token_hex(12)
    root_name, _ = packages(nonce, VERSIONS[0], 'root')
    leaf_name, _ = packages(nonce, VERSIONS[0], 'leaf')
    phases, controls, identities = [], [], []
    with tempfile.TemporaryDirectory(prefix='lsf-private-npm-acquisition-') as temporary:
        owned = Path(temporary)
        app = create(owned / 'application', 'greeting')
        sdk = read_file(app / 'sdk-lock.json')
        require(all(nonce.encode() not in raw for name, raw in source_files(app).items()
                    if name.startswith('vendor/lsf/')), 'private-npm-coordinate-already-in-sdk')
        original_source = read_file(app / 'src/main.ts')
        hook = b'  greet(name) {'
        require(original_source.count(hook) == 1, 'private-npm-original-template-required')
        selected = b'import { describe } from "' + root_name.encode() + b'";\n' + original_source
        selected = selected.replace(hook, hook + b'\n    if (name.startsWith("private-npm:")) return describe(name.slice(12));')
        (app / 'src/main.ts').write_bytes(selected)
        token, wrong = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with server(owned, commands, nonce, token) as (feed, endpoint, certificate, key):
            confidential = (token.encode(), wrong.encode(), key,
                base64.b64encode(token.encode()), base64.b64encode(wrong.encode()))
            (app / 'registry-trust').mkdir()
            (app / 'registry-trust/roots.pem').write_bytes(certificate)
            declaration = {'registries': [{'scope': root_name.split('/')[0], 'url': endpoint,
                'authorizationEnv': TOKEN_SLOT}], 'tlsTrust': {'caFile': 'registry-trust/roots.pem'}}
            policy = owned / 'policy.json'
            policy.write_bytes(canonical(declaration))
            author(commands, 'private-npm-normal-add', 'add', app, root_name, '--version', VERSIONS[0],
                   confidential=confidential)
            for ordinal, phase in enumerate(('initial', 'updated', 'removed')):
                version = VERSIONS[min(ordinal, 1)]
                condition = ordinal == 0
                if ordinal:
                    previous = read_file(app / dependencies.LOCK)
                    arguments = ('update', app, root_name, '--version', version) if phase == 'updated' else ('remove', app, root_name)
                    author(commands, phase + '-normal-edit', *arguments, confidential=confidential)
                    author(commands, phase + '-stale-selection', 'dependencies', app, expected=1, confidential=confidential)
                    require(read_file(app / dependencies.LOCK) == previous, 'private-npm-stale-selection-replaced-lock')
                    if phase == 'removed':
                        (app / 'src/main.ts').write_bytes(original_source)
                candidate = output / (phase + '-candidate.json')
                lock = capture_phase(commands, app, candidate, policy, node, npm, token, confidential, condition=condition)
                graph = read_json(app / 'npm-resolved.lock.json')
                rows = [row for row in graph['nodes'] if row['location'] in {
                    'node_modules/' + root_name, 'node_modules/' + leaf_name}]
                require((not rows) if phase == 'removed' else
                    (len(rows) == 2 and all(row['version'] == version and row['selected'] for row in rows)),
                    'private-npm-native-selected-transitive-closure')
                require(graph['selection']['conditions'] == ([CONDITION] if condition else [])
                    and graph['fetchTrust']['caFile'] == 'registry-trust/roots.pem', 'private-npm-condition-and-trust-selection')
                if rows:
                    parent = next(row for row in rows if row['location'] == 'node_modules/' + root_name)
                    require(any(edge['name'] == leaf_name and edge['selected'] == 'node_modules/' + leaf_name
                                for edge in parent['dependencies']), 'private-npm-transitive-edge-required')
                    require(all(row['ignoredLifecycleScripts'] == ['install', 'postinstall', 'preinstall', 'prepare']
                                for row in rows), 'private-npm-lifecycle-hooks-not-accounted')
                if phase == 'initial':
                    baseline = accepted(app)
                    controls.extend(integrity_controls(commands, app, lock, confidential))
                    for case, selected_token, trusted in (('missing-credential', None, True),
                            ('wrong-credential', wrong, True), ('untrusted-certificate', token, False)):
                        bad_policy = json.loads(json.dumps(declaration))
                        if selected_token is None:
                            bad_policy['registries'][0].pop('authorizationEnv')
                        if not trusted:
                            bad_policy.pop('tlsTrust')
                        selected_policy = owned / (case + '.json')
                        selected_policy.write_bytes(canonical(bad_policy))
                        failed = output / (case + '-candidate.json')
                        start, handshakes = len(feed.observations), feed.handshake_failures
                        author(commands, case, 'resolve', app, '--candidate', failed, '--node', node, '--npm', npm,
                            '--registry-config', selected_policy, '--condition', CONDITION, token=selected_token,
                            expected=1, confidential=confidential)
                        observations = feed.observations[start:]
                        require(not failed.exists() and accepted(app) == baseline
                            and not any(row['authorized'] for row in observations)
                            and (any(row['status'] == 401 for row in observations) if trusted else
                                 not observations and feed.handshake_failures > handshakes),
                            'private-npm-native-negative-accepted')
                        failure = read_json(failed.with_name(failed.name + '.failed.json'))
                        require(failure['automaticReplay'] is False and failure['compilerExecution'] is False,
                                'private-npm-negative-authority')
                        controls.append({'case': case, 'peerRequests': len(observations),
                            'tlsHandshakeFailures': feed.handshake_failures-handshakes, 'acceptedLockPreserved': True})
                    asset = '/tarballs/root-' + VERSIONS[0] + '.tgz'
                    _, files = packages(nonce, VERSIONS[0], 'root')
                    files['selected.mjs'] += b'\n// changed source at the same selected version\n'
                    original_asset, start = feed.assets[asset], len(feed.observations)
                    try:
                        with feed.lock:
                            feed.assets[asset] = ('private-tarball', archive(files))
                        failed = output / 'changed-checksum-candidate.json'
                        author(commands, 'changed-checksum', 'resolve', app, '--candidate', failed,
                            '--node', node, '--npm', npm, '--registry-config', policy, '--condition', CONDITION,
                            token=token, expected=1, confidential=confidential)
                        require(not failed.exists() and accepted(app) == baseline and any(
                            row['asset'] == 'private-tarball' and row['authorized'] and row['status'] == 200
                            for row in feed.observations[start:]), 'private-npm-checksum-mutation-accepted')
                        controls.append({'case': 'changed-tarball-same-version', 'acceptedLockPreserved': True})
                    finally:
                        with feed.lock:
                            feed.assets[asset] = original_asset
                phases.append((preserved(app, output / (phase + '-project'), lock, confidential),
                               lock, version, phase == 'removed', 'enabled' if condition else 'default'))
                identities.append({'phase': phase, 'version': version, 'removed': phase == 'removed',
                    'sourceDigest': digest(inventory(source_files(app))),
                    'nativeGraphDigest': digest(read_file(app / 'npm-resolved.lock.json')),
                    'acceptedLockDigest': digest(read_file(app / dependencies.LOCK)),
                    'selection': graph['selection'], 'publicTrust': graph['fetchTrust'],
                    'packages': rows})
                require(read_file(app / 'sdk-lock.json') == sdk, 'private-npm-sdk-lock-mutated')
            observations = list(feed.observations)
            require(any(row['asset'] == 'private-tarball' and row['authorized'] and row['status'] == 200
                        for row in observations), 'private-npm-authenticated-acquisition-not-observed')
    return phases, {'status': 'passed', 'nonce': nonce, 'packages': [root_name, leaf_name],
        'versions': list(VERSIONS), 'phases': identities, 'controls': controls, 'requests': observations,
        'peerPhysicallyReaped': True, 'originalPackagesUnavailableBeforeBuild': True,
        'credentialsCaptured': False, 'privateKeyCaptured': False, 'sdkLockDigest': digest(sdk)}


def qualify(prepared, output, tools):
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=2400, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'original-native-products'
    try:
        receipt, products, companions, native_identity = frozen(prepared)
        node = Path(shutil.which('node') or 'missing-node').resolve(strict=True)
        npm = Path(shutil.which('npm') or 'missing-npm').resolve(strict=True)
        original_tools = {'node': file_identity(node), 'npm': file_identity(npm)}
        stage = 'actual-authenticated-native-acquisition'
        phases, acquired = capture(output, commands, node, npm)
        write_json(output / 'capture.json', acquired)
        builds, nodes = [], []
        for ordinal, (app, lock, version, removed, condition) in enumerate(phases):
            stage = 'offline-build-' + str(ordinal)
            before = inventory(source_files(app))
            artifact = build(app, output / ('build-' + str(ordinal)), products['capsule_contracts'], products['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools)
            require(before == inventory(source_files(app)) and dependencies.verify_inputs(app, 'typescript').lock == lock,
                    'private-npm-offline-build-mutated-inputs')
            require(read_json(artifact / 'application-dependencies.json')['networkResolution'] is False,
                    'private-npm-offline-compiler-required')
            compiler_inputs = read_file(artifact / 'compiler-inputs.json')
            require(read_file(prepared / 'builds/greeting/compiler-inputs.json') == compiler_inputs,
                    'private-npm-normal-compiler-inputs-changed')
            if ordinal == 0:
                rebuilt = build(app, output / 'offline-rebuild', products['capsule_contracts'], products['package'],
                    'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools)
                require(read_json(artifact / 'BUILD-COMPLETE.json')['componentDigest']
                        == read_json(rebuilt / 'BUILD-COMPLETE.json')['componentDigest'], 'private-npm-offline-component-not-identical')
            stage = 'sign-and-enforced-node-' + str(ordinal)
            require(frozen(prepared)[0] == receipt, 'private-npm-original-inputs-drift')
            signed = output / ('signed-' + str(ordinal))
            commands.run('private-npm-sign-' + str(ordinal), products['capsule_authoring'], 'demo-sign', signed, artifact, *companions)
            write_json(signed / 'private-npm-probe.json', {'nonce': acquired['nonce'], 'version': version,
                       'removed': removed, 'condition': condition})
            node_result = node_workflow(products['latent'], products['latentd'], signed, output / ('node-' + str(ordinal)),
                                       language='typescript', captured_npm_private=True)
            require(node_result['status'] == 'passed' and node_result['capturedNpmPrivate']['status'] == 'passed'
                    and len(node_result['capturedNpmPrivate']['cases']) == 3, 'private-npm-actual-signed-programme-required')
            builds.append(read_json(artifact / 'BUILD-COMPLETE.json'))
            nodes.append(file_identity(output / ('node-' + str(ordinal)) / 'workflow.json'))
        require(frozen(prepared)[3] == native_identity
                and original_tools == {'node': file_identity(node), 'npm': file_identity(npm)}
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and time.monotonic() < commands.deadline, 'private-npm-final-inputs-drift')
        result = {'schemaVersion': 'latent.npm.private-dependencies.qualification.v1', 'status': 'passed',
            'capture': acquired, 'builds': builds, 'nodeReceipts': nodes, 'materials': materials,
            'preparedSourceIdentityDigest': receipt['sourceIdentityDigest'], 'nativeBinaries': receipt['binaries'],
            'hermetic': False, 'cleanHost': False, 'publisherAuthenticated': False,
            'releasePublication': 'not-performed', 'generatorQualification': 'separate', 'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage, 'errorCategory': type(error).__name__,
                                              'materials': materials, 'fullTicketQualification': False})
        except Exception:
            # A diagnostic write cannot replace the original acquisition or cleanup failure.
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-qualification', type=Path, required=True)
    parser.add_argument('--tools', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    qualify(arguments.native_qualification, arguments.output, arguments.tools)
