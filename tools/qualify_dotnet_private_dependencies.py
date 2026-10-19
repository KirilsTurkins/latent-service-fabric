"""Actual authenticated NuGet capture, offline lifecycle and signed components.

Reuses the exact five native products and four companion builds from the
preceding ordinary .NET qualification. Private fixture keys never enter the
application, compiler source capture, public receipts or uploaded products.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import secrets
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies, dotnet_capsule
from tools.application_dependency_store import DependencyError, Store, directory_files
from tools.build_observation import build_environment
from tools.build_snapshot import canonical
from tools.dotnet_dependency_authoring import source_files
from tools.dotnet_guest.build import build
from tools.dotnet_guest.project import create
from tools.dotnet_private_feed_fixture import (TOKEN_SLOT, VERSIONS, credential, edit_source,
    libraries, server)
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run as node_workflow
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, write_json

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
COMPANIONS = ('word-count', 'shipping', 'http-status', 'recovery')
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'
MATERIALS = ('tools/qualify_dotnet_private_dependencies.py', 'tools/dotnet_private_feed_fixture.py',
             'tools/dotnet_registry_tls.py', 'tools/run_rust_capsule_workflow.py')


def prepared_inputs(prepared):
    receipt = read_json(prepared / 'qualification.json')
    before = inputs('dotnet')
    require(receipt['status'] == 'passed' and 'applicationDependencies' in receipt
            and read_json(prepared / 'source-inputs.json') == before
            and read_file(prepared / 'source-inputs.json') == read_file(prepared / 'source-inputs-after.json')
            and digest(read_file(prepared / 'source-inputs.json')) == receipt['sourceIdentityDigest'],
            'private-NuGet-exact-prepared-source-required')
    require(set(receipt['binaries']) == set(PRODUCTS), 'private-NuGet-five-native-products-required')
    products = {name: prepared / 'native-binaries' / name.replace('/', '-') for name in PRODUCTS}
    require(all(file_identity(path, 512 * 1024 * 1024) == receipt['binaries'][name]
                for name, path in products.items()), 'private-NuGet-native-products-changed')
    require(all(read_json(prepared / 'builds' / name / 'BUILD-COMPLETE.json') == receipt['builds'][name]
                for name in COMPANIONS), 'private-NuGet-companion-build-changed')
    return before, receipt, products


def author(*arguments):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = dotnet_capsule.main([str(value) for value in arguments])
    return code, out.getvalue(), err.getvalue()


def accepted(app):
    return {name: read_file(app / name) for name in (dependencies.MANIFEST, dependencies.LOCK,
        'packages.lock.json', 'nuget-resolved.lock.json', 'sdk-lock.json')}


def reviewed(app, candidate, policy, dotnet, tools, secrets_):
    code, out, err = author('resolve', app, '--candidate', candidate, '--dotnet', dotnet,
                            '--tools', tools, '--feed-config', policy, '--update-lock')
    require(code == 0 and not err, 'private-NuGet-normal-resolution-failed')
    require(all(secret not in (out + err).encode() for secret in secrets_), 'private-NuGet-public-secret')
    lock = read_json(candidate, dependencies.MAX_LOCK)
    require(not lock['executableInputs'], 'private-NuGet-unexpected-executable-package')
    code, out, err = author('review-lock', app, '--candidate', candidate, '--expect', digest(read_file(candidate)))
    require(code == 0 and not err and all(secret not in out.encode() for secret in secrets_),
            'private-NuGet-exact-review-failed')
    code, _out, err = author('dependencies', app)
    require(code == 0 and not err, 'private-NuGet-reviewed-graph-not-verified')
    return lock


def closed_graph(lock, payloads, main, child, version):
    rows = {row['id']: row for row in lock['artifacts']}
    require(set(rows) == {main + '/' + version, child + '/' + version}, 'private-NuGet-selected-private-closure')
    require(rows[main + '/' + version]['dependencies'] == [child + '/' + version],
            'private-NuGet-transitive-edge-required')
    for identity in (main, child):
        raw = payloads[(identity, version)]
        require(rows[identity + '/' + version]['role'] == 'application'
                and rows[identity + '/' + version]['original'] == {'digest': digest(raw), 'size': len(raw)},
                'private-NuGet-original-package-identity')


def preserved(app, target, expected, secrets_):
    """Copy only verified source plus bounded immutable CAS, not authoring state."""
    files = source_files(app)
    files.update({'dependency-inputs/objects/' + name: raw for name, raw
                  in directory_files(app / 'dependency-inputs/objects').items()})
    require(all(secret not in raw for raw in files.values() for secret in secrets_),
            'private-NuGet-secret-captured')
    target.mkdir(mode=0o700)
    for name, raw in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    actual = dependencies.verify_inputs(target, 'dotnet')
    require(actual is not None and actual.lock == expected, 'private-NuGet-preserved-source-not-verified')
    return target


def integrity_controls(app, lock):
    original = accepted(app)
    store = Store(app / 'dependency-inputs/objects', create=False)
    item = lock['artifacts'][0]['original']
    path = store.path(item['digest'])
    raw = store.get(**item)
    controls = []
    for mode in ('missing-original', 'tampered-original', 'changed-public-ca'):
        target = app / 'feed-trust/public-roots.pem' if mode == 'changed-public-ca' else path
        previous = read_file(target)
        try:
            if mode == 'missing-original':
                target.unlink()
            else:
                target.write_bytes(previous + b'changed')
            try:
                dependencies.verify_inputs(app, 'dotnet')
            except DependencyError:
                pass
            else:
                raise ValueError('private-NuGet-integrity-negative-accepted')
        finally:
            target.write_bytes(previous)
        require(accepted(app) == original and store.get(**item) == raw,
                'private-NuGet-integrity-control-mutated-lock')
        controls.append({'case': mode, 'status': 'refused-before-compiler'})
    return controls


def capture(root, tools, commands):
    app = create(root / 'authoring-project', 'greeting')
    from tools.dotnet_guest.entropy_grants import declare
    declare(app)
    sdk = read_file(app / 'sdk-lock.json')
    original_source = edit_source(app)
    nonce = secrets.token_hex(12)
    main, child = ('outside.private.' + nonce + '.' + role for role in ('main', 'leaf'))
    token, wrong = 'fixture-' + secrets.token_hex(24), 'incorrect-' + secrets.token_hex(24)
    controls, phases = [], []
    with tempfile.TemporaryDirectory(prefix='lsf-private-nuget-peer-') as temporary:
        owned = Path(temporary)
        payloads = libraries(owned, app, tools, nonce)
        # The normal maintained compiler owns the resolver executable selection.
        from tools.dotnet_guest.compiler import Compiler
        (owned / 'compiler-identity').mkdir(mode=0o700)
        compiler = Compiler(tools, Commands(app, owned / 'compiler-identity', build_environment(owned)),
                            app / 'vendor/lsf', offline=True, captured=True)
        dotnet = compiler.dotnet
        (owned / 'certificate-evidence').mkdir(mode=0o700)
        peer_commands = Commands(owned, owned / 'certificate-evidence', build_environment(owned))
        with server(owned, peer_commands, payloads, token) as (feed, endpoint, certificate, key):
            confidential = (token.encode(), wrong.encode(), key)
            ca = app / 'feed-trust/public-roots.pem'
            ca.parent.mkdir(mode=0o700)
            ca.write_bytes(read_file(Path('/etc/ssl/certs/ca-certificates.crt'), 512 * 1024) + b'\n' + certificate)
            declaration = {'sources': [{'name': 'private-fixture', 'url': endpoint + '/index.json',
                'patterns': ['Outside.Private.' + nonce + '.*'], 'username': 'fixture', 'authorizationEnv': TOKEN_SLOT}],
                'tlsTrust': {'caFile': 'feed-trust/public-roots.pem'}}
            policy = owned / 'feed-policy.json'
            policy.write_bytes(canonical(declaration))
            code, _out, err = author('add', app, main, '--version', VERSIONS[0])
            require(code == 0 and not err, 'private-NuGet-normal-add-failed')
            with credential(token):
                lock = reviewed(app, root / 'initial-candidate.json', policy, dotnet, tools, confidential)
            closed_graph(lock, payloads, main, child, VERSIONS[0])
            original = accepted(app)
            for case, selected_token, trusted in (('missing-credential', None, True),
                    ('wrong-credential', wrong, True), ('untrusted-certificate', token, False)):
                selected = owned / (case + '.json')
                selected.write_bytes(canonical(declaration if trusted else {'sources': declaration['sources']}))
                candidate = root / (case + '-candidate.json')
                start = len(feed.observations)
                with credential(selected_token):
                    code, out, err = author('resolve', app, '--candidate', candidate, '--dotnet', dotnet,
                        '--tools', tools, '--feed-config', selected, '--update-lock')
                require(code == 1 and not candidate.exists() and accepted(app) == original
                        and all(secret not in (out + err).encode() for secret in confidential),
                        'private-NuGet-native-negative-accepted')
                failed = read_json(candidate.with_name(candidate.name + '.failed.json'))
                require(failed['automaticReplay'] is False and failed['compilerExecution'] is False,
                        'private-NuGet-negative-authority')
                observed = feed.observations[start:]
                require(not any(row['authorized'] for row in observed)
                        and (trusted or not observed), 'private-NuGet-negative-authorized-request')
                controls.append({'case': case, 'status': 'known-native-resolution-failure',
                                 'peerRequests': len(observed), 'acceptedLockPreserved': True})
            controls.extend(integrity_controls(app, lock))
            phases.append((preserved(app, root / 'initial-project', lock, confidential), lock, VERSIONS[0], False))
            # An explicit native editor changes declarations; stale accepted
            # material must refuse until a new exact candidate is reviewed.
            for phase, version in (('updated', VERSIONS[1]), ('removed', VERSIONS[1])):
                args = ('update', app, main, '--version', version) if phase == 'updated' else ('remove', app, main)
                code, _out, err = author(*args)
                require(code == 0 and not err, 'private-NuGet-normal-edit-failed')
                code, _out, _err = author('dependencies', app)
                require(code == 1 and read_file(app / dependencies.LOCK) == original[dependencies.LOCK],
                        'private-NuGet-stale-declarations-accepted')
                if phase == 'removed':
                    edit_source(app, original_source)
                    policy.write_bytes(canonical({'sources': []}))
                with credential(token):
                    lock = reviewed(app, root / (phase + '-candidate.json'), policy, dotnet, tools, confidential)
                if phase == 'updated':
                    closed_graph(lock, payloads, main, child, version)
                else:
                    require(not lock['artifacts'] and not lock['executableInputs'], 'private-NuGet-removal-retained-package')
                original = accepted(app)
                phases.append((preserved(app, root / (phase + '-project'), lock, confidential), lock, version, phase == 'removed'))
            observations = list(feed.observations)
            require(any(row['authorized'] and row['asset'] == 'package' and row['status'] == 200
                        for row in observations), 'private-NuGet-no-authenticated-package')
        compiler.check_unchanged()
        require(read_file(app / 'sdk-lock.json') == sdk, 'private-NuGet-sdk-lock-changed')
        # All original archives/libraries and the private TLS key disappear
        # when this owned temporary peer scope exits, before any app build.
    return phases, {'status': 'passed', 'nonce': nonce, 'packages': [main, child],
        'versions': list(VERSIONS), 'controls': controls, 'requests': observations,
        'peerPhysicallyReaped': True, 'originalPackagesUnavailableBeforeBuild': True,
        'credentialsCaptured': False, 'privateKeyCaptured': False, 'sdkLockDigest': digest(sdk)}


def qualify(prepared, output, tools):
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=2400, command_seconds=900)
    material = {name: file_identity(ROOT / name) for name in MATERIALS}
    stage = 'prepared-inputs'
    try:
        before, receipt, products = prepared_inputs(prepared)
        stage = 'authenticated-native-capture-and-lifecycle'
        phases, captured = capture(output, tools, commands)
        write_json(output / 'capture.json', captured)
        builds, nodes = [], []
        for ordinal, (app, lock, version, removed) in enumerate(phases):
            stage = 'offline-component-build-' + str(ordinal)
            observed = inventory(source_files(app))
            artifact = build(app, output / ('build-' + str(ordinal)), products['examples/capsule_contracts'],
                products['examples/package'], REPOSITORY, tools=tools, offline=True)
            require(inventory(source_files(app)) == observed and dependencies.verify_inputs(app, 'dotnet').lock == lock,
                    'private-NuGet-offline-build-changed-source')
            containment = read_json(artifact / 'compiler-containment.json')
            require(containment['network'] == 'denied' and containment['credentials'] == 'not-inherited',
                    'private-NuGet-offline-compiler-not-contained')
            if ordinal == 0:
                rebuilt = build(app, output / 'offline-rebuild', products['examples/capsule_contracts'],
                    products['examples/package'], REPOSITORY, tools=tools, offline=True)
                require(read_json(artifact / 'BUILD-COMPLETE.json')['componentDigest']
                        == read_json(rebuilt / 'BUILD-COMPLETE.json')['componentDigest'],
                        'private-NuGet-offline-component-not-identical')
            stage = 'normal-sign-and-enforced-node-' + str(ordinal)
            require(prepared_inputs(prepared)[:2] == (before, receipt), 'private-NuGet-prepared-input-drift')
            signed = output / ('signed-' + str(ordinal))
            commands.run('private-NuGet-sign-' + str(ordinal), products['examples/capsule_authoring'], 'demo-sign',
                signed, artifact, *(prepared / 'builds' / name for name in COMPANIONS))
            write_json(signed / 'private-nuget-probe.json', {'nonce': captured['nonce'], 'version': version, 'removed': removed})
            node = node_workflow(products['latent'], products['latentd'], signed, output / ('node-' + str(ordinal)),
                language='dotnet', noncrypto_entropy=True, captured_dotnet_private=True)
            require(node['status'] == 'passed' and node['capturedDotnetPrivate']['status'] == 'passed'
                    and len(node['capturedDotnetPrivate']['cases']) == 3, 'private-NuGet-signed-node-not-qualified')
            builds.append(read_json(artifact / 'BUILD-COMPLETE.json'))
            nodes.append(file_identity(output / ('node-' + str(ordinal)) / 'workflow.json'))
        require(before == inputs('dotnet') and prepared_inputs(prepared)[:2] == (before, receipt)
                and material == {name: file_identity(ROOT / name) for name in MATERIALS}
                and time.monotonic() < commands.deadline, 'private-NuGet-qualification-input-drift')
        result = {'formatVersion': 1, 'status': 'passed', 'capture': captured, 'builds': builds, 'nodeReceipts': nodes,
            'materials': material, 'preparedSourceIdentityDigest': receipt['sourceIdentityDigest'],
            'nativeBinaries': receipt['binaries'], 'hermetic': False, 'cleanHost': False,
            'publisherAuthenticated': False, 'releasePublication': 'not-performed',
            'reflectionQualification': 'not-covered', 'fullTicketQualification': False}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException as error:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'stage': stage,
                       'errorCategory': type(error).__name__, 'materials': material, 'fullTicketQualification': False})
        except Exception:
            pass  # Public diagnostics cannot replace the original qualification failure.
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-qualification', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    args = parser.parse_args()
    result = qualify(args.prepared_qualification.resolve(), args.output.resolve(), args.tools.resolve())
    print(json.dumps({'status': result['status']}))
