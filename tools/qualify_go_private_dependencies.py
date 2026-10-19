"""Authenticated native Go proxy capture followed by offline signed lifecycle."""
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

from tools import application_dependencies as dependencies, go_application_dependencies as native
from tools.application_dependency_store import directory_files
from tools.build_observation import build_environment
from tools.build_snapshot import canonical
from tools.go_capsule_build import build
from tools.go_capsule_project import create
from tools.go_dependency_authoring import source_files
from tools.go_private_proxy_fixture import TOKEN_SLOT, TAG, VERSIONS, archive, assets, expected, module_sources, server
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_go_standard_http import NATIVE_NAMES
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, write_json

MATERIALS = ('tools/qualify_go_private_dependencies.py', 'tools/go_private_proxy_fixture.py',
             'tools/go_proxy_tls.py', 'tools/go_application_dependencies.py',
             'tools/go_native_authoring.py', 'tools/go_dependency_authoring.py',
             'tools/run_rust_capsule_workflow.py')


def frozen(prepared):
    receipt = read_json(prepared / 'qualification.json')
    require(receipt['schemaVersion'] == 'latent.go-capsule.qualification.v1' and receipt['status'] == 'passed'
            and read_json(prepared / 'source-inputs.json') == inputs('go')
            and read_file(prepared / 'source-inputs.json') == read_file(prepared / 'source-inputs-after.json')
            and digest(read_file(prepared / 'source-inputs.json')) == receipt['sourceIdentityDigest'],
            'private-Go-current-normal-source-required')
    products = {name: prepared / 'native-binaries' / key.replace('/', '-') for name, key in NATIVE_NAMES.items()}
    require(all(file_identity(path) == receipt['binaries'][NATIVE_NAMES[name]] for name, path in products.items()),
            'private-Go-frozen-native-product-drift')
    companions = [prepared / 'builds' / name for name in TEMPLATES if name != 'greeting']
    require(all(read_json(path / 'BUILD-COMPLETE.json') == receipt['builds'][path.name] for path in companions),
            'private-Go-frozen-companion-drift')
    return receipt, products, companions


def author(commands, stage, *arguments, token=None, expected=0, confidential=()):
    ordinal = len(commands.records)
    previous = commands.environment.pop(TOKEN_SLOT, None)
    if token is not None:
        commands.environment[TOKEN_SLOT] = token
    try:
        try:
            commands.run(stage, sys.executable, ROOT / 'tools/go_capsule.py', *arguments)
        except ValueError:
            require(len(commands.records) == ordinal + 1
                    and commands.records[-1]['exitCode'] == expected and expected != 0,
                    'private-Go-unexpected-native-command-failure')
        require(commands.records[-1]['exitCode'] == expected, 'private-Go-native-command-outcome')
        for stream in ('stdout', 'stderr'):
            raw = read_file(commands.output / 'logs' / f'{ordinal:02d}-{stage}.{stream}.txt')
            require(all(secret not in raw for secret in confidential), 'private-Go-public-command-secret')
    finally:
        commands.environment.pop(TOKEN_SLOT, None)
        if previous is not None:
            commands.environment[TOKEN_SLOT] = previous


def sdk_assets(owned, commands, go):
    """Fetch only the immutable SDK module through its ordinary Go checksum verifier."""
    source = owned / 'sdk-public-source'
    source.mkdir()
    for name in ('go.mod', 'go.sum'):
        (source / name).write_bytes(read_file(ROOT / 'sdk/go-guest/runtime-deps' / name))
    locked = read_json(ROOT / 'sdk/go-guest/runtime-deps/dependencies.lock.json')['modules']
    expected = native.sums(read_file(source / 'go.sum'))
    before_root, before_environment = commands.root, dict(commands.environment)
    commands.root = source
    commands.environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', GOFLAGS='-mod=readonly',
        GOPROXY='https://proxy.golang.org', GOSUMDB='sum.golang.org', GOAUTH='off', CGO_ENABLED='0',
        HOME=str(owned / 'sdk-home'), USERPROFILE=str(owned / 'sdk-home'),
        GOMODCACHE=str(owned / 'sdk-modules'), GOCACHE=str(owned / 'sdk-cache'))
    try:
        downloads = native.json_stream(commands.run('private-Go-immutable-sdk-download', go, 'mod', 'download', '-json', 'all'))
        require({(row['Path'], row['Version']) for row in downloads}
                == {(row['path'], row['version']) for row in locked}, 'private-Go-exact-sdk-module-set')
        result = {}
        for row in downloads:
            native.verify_download(row, expected)
            for field in ('Info', 'GoMod', 'Zip'):
                path = Path(row[field])
                name = path.relative_to(owned / 'sdk-modules/cache/download').as_posix()
                result['/' + name] = ('immutable-sdk', read_file(path, 32 * 1024 * 1024))
        return result
    finally:
        commands.root = before_root
        commands.environment.clear()
        commands.environment.update(before_environment)



def native_reference(app, go, commands, output, nonce, version):
    """Compile only this owned ordinary fixture using its already captured downloads."""
    from tools.application_dependencies import prepare
    from tools.build_process import run_bounded
    from tools.go_application_dependencies import configure
    from tools.guest_dependency_inputs import capture_source
    original_go = file_identity(go)
    observed = capture_source(app, 'go')
    deadline = min(commands.deadline, time.monotonic() + 120)
    with tempfile.TemporaryDirectory(prefix='lsf-private-Go-reference-') as temporary:
        root = Path(temporary)
        work = root / 'project'
        work.mkdir()
        for name, raw in observed.files.items():
            destination = work / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        closure = prepare(observed.dependency_root, work, root, 'go')
        require(closure is not None, 'private-Go-reference-captured-closure')
        selected = configure(closure, work)
        for name, raw in directory_files(Path(selected['downloadCache'])).items():
            destination = root / 'modules/cache/download' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
        environment = build_environment(root)
        environment.update(GOTOOLCHAIN='local', GOWORK='off', GOENV='off', CGO_ENABLED='0',
            GOOS='linux', GOARCH='amd64', GOCACHE=str(root / 'cache'), GOMODCACHE=str(root / 'modules'),
            GOPROXY='off', GOSUMDB='off', GONOPROXY='none', GONOSUMDB='none', GOPRIVATE='',
            GOAUTH='off', GOFLAGS='-mod=readonly -tags=' + TAG)
        identity = 'private.example.test/' + nonce + '/root'
        source = ('package main\nimport ("fmt"; "os"; ordinary "' + identity
                  + '")\nfunc main() { if len(os.Args) != 2 { panic("argument") }; fmt.Print(ordinary.Describe(os.Args[1])) }\n').encode()
        harness, binary = root / 'main.go', root / 'reference'
        harness.write_bytes(source)
        def command(arguments, maximum):
            remaining = min(maximum, deadline - time.monotonic())
            require(remaining > 0, 'private-Go-reference-original-deadline')
            return run_bounded(arguments, work, environment, remaining, 65536)
        command([str(go), 'build', '-mod=readonly', '-trimpath', '-o', str(binary), str(harness)], 100)
        cases = []
        for text in ('alpha', 'Gr\u00fc\u00dfe', 'fresh-state'):
            raw = command([str(binary), text], 5).stdout
            require(raw == expected(nonce, version, text, 'linux').encode(), 'private-Go-reference-result')
            cases.append({'expectedDigest': digest(raw), 'freshProcess': True})
        result = {'status': 'passed', 'guestExecution': False, 'scope': 'owned-private-library-native-reference',
            'networkResolution': False, 'sourceDigest': digest(source), 'nativeGo': original_go,
            'binary': file_identity(binary), 'dependencyIdentity': closure.identity, 'cases': cases}
        closure.check_unchanged()
        observed.check_unchanged()
    require(file_identity(go) == original_go, 'private-Go-reference-compiler-drift')
    write_json(output, result)
    return result


def accepted(app):
    return {name: read_file(app / name) for name in (dependencies.MANIFEST, dependencies.LOCK,
        'go.mod', 'go.sum', 'go-resolved.lock.json', 'sdk-lock.json')}


def capture_phase(commands, app, candidate, policy, go, token, confidential):
    author(commands, candidate.stem + '-lock', 'lock', app, '--go', go, '--proxy-config', policy,
           '--tag', TAG, token=token, confidential=confidential)
    author(commands, candidate.stem + '-resolve', 'resolve', app, '--candidate', candidate, '--go', go,
           '--proxy-config', policy, '--tag', TAG, token=token, confidential=confidential)
    lock = read_json(candidate, dependencies.MAX_LOCK)
    require(not lock['executableInputs'], 'private-Go-unexpected-generator')
    author(commands, candidate.stem + '-review', 'review-lock', app, '--candidate', candidate,
           '--expect', digest(read_file(candidate)), confidential=confidential)
    author(commands, candidate.stem + '-verify', 'dependencies', app, confidential=confidential)
    return lock



def integrity_controls(commands, app, lock, confidential):
    """The ordinary accepted-lock consumer must refuse damaged owned inputs."""
    from tools.application_dependency_store import Store
    before = accepted(app)
    selected = next(row for row in lock['artifacts']
                    if row['metadata'].get('assetType') == 'selected-module-source'
                    and row['role'] == 'application')
    entry = selected['files'][0]
    store = Store(app / 'dependency-inputs/objects', create=False)
    path = store.path(entry['digest'])
    raw = store.get(entry['digest'], entry['size'])
    rows = []
    for case in ('missing-cas-object', 'tampered-cas-object', 'changed-public-ca'):
        ca = app / 'proxy-trust/roots.pem'
        original_ca = read_file(ca)
        try:
            if case == 'missing-cas-object':
                path.unlink()
            elif case == 'tampered-cas-object':
                path.write_bytes(raw + b'changed-owned-object')
            else:
                ca.write_bytes(original_ca + b'\n')
            author(commands, case, 'dependencies', app, expected=1, confidential=confidential)
            require(accepted(app) == before, 'private-Go-integrity-replaced-accepted-lock')
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
    require(all(secret not in raw for raw in files.values() for secret in confidential), 'private-Go-secret-captured')
    target.mkdir(mode=0o700)
    for name, raw in files.items():
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(raw)
    verified = dependencies.verify_inputs(target, 'go')
    require(verified is not None and verified.lock == lock, 'private-Go-preserved-closure-drift')
    return target


def capture(output, commands, go):
    nonce = secrets.token_hex(12)
    root_module = 'private.example.test/' + nonce + '/root'
    child_module = 'private.example.test/' + nonce + '/leaf'
    phases, controls, identities, references = [], [], [], []
    with tempfile.TemporaryDirectory(prefix='lsf-private-Go-acquisition-') as temporary:
        owned = Path(temporary)
        app = create(owned / 'application', 'greeting')
        sdk = read_file(app / 'sdk-lock.json')
        require(all(nonce.encode() not in raw for name, raw in source_files(app).items()
                    if name.startswith('vendor/lsf/')), 'private-Go-package-was-already-in-sdk')
        original_source = read_file(app / 'src/main.go')
        hook = b'func Greet(name string) wit.Result[string, string] {'
        require(original_source.count(hook) == 1 and original_source.count(b'import (') == 1,
                'private-Go-original-template-required')
        selected = original_source.replace(b'import (', b'import (\n    ordinary "' + root_module.encode() + b'"')
        selected = selected.replace(hook, hook + b'\n    if strings.HasPrefix(name, "private-go:") {\n'
            b'        return wit.Ok[string, string](ordinary.Describe(strings.TrimPrefix(name, "private-go:")))\n    }')
        (app / 'src/main.go').write_bytes(selected)
        payloads = {**sdk_assets(owned, commands, go), **assets(nonce)}
        token, wrong = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with server(owned, commands, payloads, token) as (feed, endpoint, certificate, key):
            confidential = (token.encode(), wrong.encode(), key,
                base64.b64encode(('fixture:' + token).encode()), base64.b64encode(('fixture:' + wrong).encode()))
            (app / 'proxy-trust').mkdir()
            (app / 'proxy-trust/roots.pem').write_bytes(
                read_file(Path('/etc/ssl/certs/ca-certificates.crt'), 512 * 1024) + b'\n' + certificate)
            declaration = {'proxy': endpoint, 'sumdb': 'off', 'private': ['private.example.test/' + nonce + '/*'],
                'authorizationEnv': TOKEN_SLOT, 'username': 'fixture',
                'tlsTrust': {'caFile': 'proxy-trust/roots.pem'}}
            policy = owned / 'policy.json'
            policy.write_bytes(canonical(declaration))
            author(commands, 'private-Go-normal-add', 'add', app, root_module, '--version', VERSIONS[0],
                   '--go', go, confidential=confidential)
            for ordinal, phase in enumerate(('initial', 'updated', 'removed')):
                version = VERSIONS[min(ordinal, 1)]
                if ordinal:
                    previous = read_file(app / dependencies.LOCK)
                    arguments = ('update', app, root_module, '--version', version) if phase == 'updated' else ('remove', app, root_module)
                    author(commands, phase + '-normal-edit', *arguments, '--go', go, confidential=confidential)
                    author(commands, phase + '-stale-selection', 'dependencies', app, expected=1, confidential=confidential)
                    require(read_file(app / dependencies.LOCK) == previous, 'private-Go-stale-selection-replaced-accepted-lock')
                    if phase == 'removed':
                        (app / 'src/main.go').write_bytes(original_source)
                candidate = output / (phase + '-candidate.json')
                lock = capture_phase(commands, app, candidate, policy, go, token, confidential)
                rows = [row for row in lock['artifacts'] if row['metadata'].get('module') in {root_module, child_module}]
                require((not rows) if phase == 'removed' else
                    (len(rows) == 2 and all(row['metadata']['version'] == version and row['role'] == 'application'
                                           and row['metadata']['assetType'] == 'selected-module-source' for row in rows)),
                    'private-Go-native-selected-private-closure')
                if rows:
                    parent = next(row for row in rows if row['metadata']['module'] == root_module)
                    child = next(row for row in rows if row['metadata']['module'] == child_module)
                    require(child['id'] in parent['dependencies'], 'private-Go-transitive-edge-required')
                graph = read_json(app / 'go-resolved.lock.json')
                require(graph['selection']['tags'] == [TAG] and graph['fetchTrust']['caFile'] == 'proxy-trust/roots.pem',
                        'private-Go-native-tag-and-trust-selection')
                if phase == 'initial':
                    baseline = accepted(app)
                    controls.extend(integrity_controls(commands, app, lock, confidential))
                    for case, selected_token, trusted in (('missing-credential', None, True),
                            ('wrong-credential', wrong, True), ('untrusted-certificate', token, False)):
                        bad_policy = dict(declaration)
                        if selected_token is None:
                            bad_policy.pop('authorizationEnv')
                        if not trusted:
                            bad_policy.pop('tlsTrust')
                        selected_policy = owned / (case + '.json')
                        selected_policy.write_bytes(canonical(bad_policy))
                        failed = output / (case + '-candidate.json')
                        start = len(feed.observations)
                        handshake_start = feed.handshake_failures
                        author(commands, case, 'resolve', app, '--candidate', failed, '--go', go,
                               '--proxy-config', selected_policy, '--tag', TAG, token=selected_token,
                               expected=1, confidential=confidential)
                        observations = feed.observations[start:]
                        require(not failed.exists() and accepted(app) == baseline
                                and not any(row['authorized'] for row in observations)
                                and (any(row['status'] == 401 for row in observations) if trusted else
                                     not observations and feed.handshake_failures > handshake_start),
                                'private-Go-native-negative-accepted')
                        failure = read_json(failed.with_name(failed.name + '.failed.json'))
                        require(failure['automaticReplay'] is False and failure['compilerExecution'] is False,
                                'private-Go-negative-authority')
                        controls.append({'case': case, 'peerRequests': len(observations),
                            'tlsHandshakeFailures': feed.handshake_failures - handshake_start, 'acceptedLockPreserved': True})
                    asset = '/' + root_module + '/@v/' + VERSIONS[0] + '.zip'
                    identity, files = module_sources(nonce, VERSIONS[0], 'root')
                    files['value.go'] += b'\n// different source at the same selected version\n'
                    original_asset = feed.assets[asset]
                    checksum_start = len(feed.observations)
                    try:
                        with feed.lock:
                            feed.assets[asset] = ('private-zip', archive(identity, VERSIONS[0], files))
                        failed = output / 'changed-checksum-candidate.json'
                        author(commands, 'changed-checksum', 'resolve', app, '--candidate', failed, '--go', go,
                               '--proxy-config', policy, '--tag', TAG, token=token, expected=1, confidential=confidential)
                        require(not failed.exists() and accepted(app) == baseline and any(
                            row['asset'] == 'private-zip' and row['authorized'] and row['status'] == 200
                            for row in feed.observations[checksum_start:]), 'private-Go-changed-source-checksum-accepted')
                        controls.append({'case': 'changed-source-same-version', 'acceptedLockPreserved': True})
                    finally:
                        with feed.lock:
                            feed.assets[asset] = original_asset
                if phase != 'removed':
                    references.append(native_reference(app, go, commands, output / (phase + '-native-reference.json'), nonce, version))
                phases.append((preserved(app, output / (phase + '-project'), lock, confidential),
                               lock, version, phase == 'removed'))
                identities.append({'phase': phase, 'version': version, 'removed': phase == 'removed',
                    'sourceDigest': digest(inventory(source_files(app))),
                    'nativeGraphDigest': digest(read_file(app / 'go-resolved.lock.json')),
                    'manifestDigest': digest(read_file(app / dependencies.MANIFEST)),
                    'acceptedLockDigest': digest(read_file(app / dependencies.LOCK)),
                    'selection': graph['selection'], 'publicTrust': graph['fetchTrust'],
                    'packages': [{'identity': row['metadata']['module'], 'version': row['metadata']['version'],
                                  'original': row['original'], 'treeDigest': row['treeDigest'],
                                  'dependencies': row['dependencies']} for row in rows]})
                require(read_file(app / 'sdk-lock.json') == sdk, 'private-Go-sdk-lock-mutated')
            observations = list(feed.observations)
            require(any(row['asset'] == 'private-zip' and row['authorized'] and row['status'] == 200
                        for row in observations), 'private-Go-authenticated-acquisition-not-observed')
    return phases, {'status': 'passed', 'nonce': nonce, 'packages': [root_module, child_module],
        'versions': list(VERSIONS), 'phases': identities, 'nativeReferences': references, 'controls': controls, 'requests': observations,
        'peerPhysicallyReaped': True, 'originalPackagesUnavailableBeforeBuild': True,
        'credentialsCaptured': False, 'privateKeyCaptured': False, 'sdkLockDigest': digest(sdk)}


def qualify(prepared, output):
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1800, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'original-native-products'
    try:
        receipt, products, companions = frozen(prepared)
        go = Path(shutil.which('go') or 'missing-go').resolve(strict=True)
        original_go = file_identity(go)
        stage = 'actual-authenticated-native-acquisition'
        phases, acquired = capture(output, commands, go)
        write_json(output / 'capture.json', acquired)
        builds, nodes = [], []
        for ordinal, (app, lock, version, removed) in enumerate(phases):
            stage = 'offline-build-' + str(ordinal)
            before = inventory(source_files(app))
            artifact = build(app, output / ('build-' + str(ordinal)), products['capsule_contracts'], products['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric')
            require(before == inventory(source_files(app)) and dependencies.verify_inputs(app, 'go').lock == lock,
                    'private-Go-offline-build-mutated-inputs')
            require(read_json(artifact / 'application-dependencies.json')['networkResolution'] is False,
                    'private-Go-offline-compiler-required')
            if ordinal == 0:
                rebuilt = build(app, output / 'offline-rebuild', products['capsule_contracts'], products['package'],
                    'https://github.com/KirilsTurkins/latent-service-fabric')
                require(read_json(artifact / 'BUILD-COMPLETE.json')['componentDigest']
                        == read_json(rebuilt / 'BUILD-COMPLETE.json')['componentDigest'], 'private-Go-offline-component-not-identical')
            stage = 'sign-and-enforced-node-' + str(ordinal)
            require(frozen(prepared)[0] == receipt, 'private-Go-original-inputs-drift')
            signed = output / ('signed-' + str(ordinal))
            commands.run('private-Go-sign-' + str(ordinal), products['capsule_authoring'], 'demo-sign', signed, artifact, *companions)
            write_json(signed / 'private-go-probe.json', {'nonce': acquired['nonce'], 'version': version, 'removed': removed})
            node = node_workflow(products['latent'], products['latentd'], signed, output / ('node-' + str(ordinal)),
                                 language='go', captured_go_private=True)
            require(node['status'] == 'passed' and node['capturedGoPrivate']['status'] == 'passed'
                    and len(node['capturedGoPrivate']['cases']) == 3, 'private-Go-actual-signed-programme-required')
            builds.append(read_json(artifact / 'BUILD-COMPLETE.json'))
            nodes.append(file_identity(output / ('node-' + str(ordinal)) / 'workflow.json'))
        require(frozen(prepared)[0] == receipt and original_go == file_identity(go)
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS}
                and time.monotonic() < commands.deadline, 'private-Go-final-inputs-drift')
        result = {'schemaVersion': 'latent.go.private-dependencies.qualification.v1', 'status': 'passed',
            'capture': acquired, 'builds': builds, 'nodeReceipts': nodes, 'materials': materials,
            'preparedSourceIdentityDigest': receipt['sourceIdentityDigest'], 'nativeBinaries': receipt['binaries'],
            'hermetic': False, 'cleanHost': False, 'publisherAuthenticated': False,
            'releasePublication': 'not-performed', 'generatorQualification': 'separate', 'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage, 'errorCategory': type(error).__name__,
                                          'materials': materials, 'fullTicketQualification': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-qualification', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = qualify(args.native_qualification.resolve(), args.output.resolve())
    print(json.dumps({'status': result['status']}))
