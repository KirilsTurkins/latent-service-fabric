#!/usr/bin/env python3
"""Capture real npm libraries, then compile and execute their closure offline."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.build_snapshot import digest
from tools.phase2_operator_process import read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import NODE_ID, configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, assert_value, call, deploy
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot
from tools.typescript_dependency_authoring import status
from tools.typescript_dependency_fixture import install
from tools.typescript_guest.build import build
from tools.typescript_guest.project import create

PRODUCTS = ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')


def capture(root: Path) -> dict:
    app = create(root / 'application', 'greeting')
    sdk = (app / 'sdk-lock.json').read_bytes()
    result = install(app, root / 'outside')
    source = app / 'src/main.ts'
    original = source.read_text(encoding='utf-8')
    require(original.count('  greet(name) {') == 1, 'typescript-library-fixture-source-shape')
    source.write_text(original.replace('export const api:', 'let calls = 0;\nexport const api:')
        .replace('  greet(name) {', '  greet(name) {\n    if (++calls !== 1) throw "activation-state-reused";'),
        encoding='utf-8')
    require((app / 'sdk-lock.json').read_bytes() == sdk, 'typescript-library-sdk-lock-changed')
    result.update(status='captured', runtimeQualification=False, catalogueRegistration=False,
        libraryStartupOnBuildHost=False, sdkLockDigest=digest(sdk),
        applicationIdentity=digest(inventory(snapshot(app))), capturedInputs=status(app),
        qualifier=file_identity(Path(__file__)))
    write_json(root / 'capture.json', result)
    return result


def negative_inputs(app: Path) -> list[dict]:
    before = inventory(snapshot(app))
    accepted = (app / dependencies.LOCK).read_bytes()
    verified = dependencies.verify_inputs(app, 'typescript')
    require(verified is not None, 'typescript-library-reviewed-closure-required')
    transitive = next(row for row in verified.lock['artifacts'] if
        row.get('metadata', {}).get('nativeLocation') == 'node_modules/@jridgewell/resolve-uri')
    selected = Store(app / 'dependency-inputs/objects', create=False).path(transitive['original']['digest'])
    original = selected.read_bytes()
    results = []
    for name, mutation, reason in (
        ('missing-original-transitive', None, 'dependency-artifact-missing-resolve-explicitly'),
        ('tampered-original-transitive', b'changed same-name-version bytes', 'dependency-artifact-integrity'),
    ):
        selected.unlink() if mutation is None else selected.write_bytes(mutation)
        try:
            dependencies.verify_inputs(app, 'typescript')
        except DependencyError as error:
            require(str(error) == reason, 'typescript-library-negative-wrong-reason')
            results.append({'case': name, 'status': 'known-failure', 'reason': reason})
        else:
            raise ValueError('typescript-library-corrupt-transitive-accepted')
        finally:
            selected.write_bytes(original)
        require((app / dependencies.LOCK).read_bytes() == accepted, 'typescript-library-accepted-lock-overwritten')
    require(inventory(snapshot(app)) == before, 'typescript-library-negative-input-not-restored')
    return results


def idle(client, output: Path, label: str) -> dict:
    deadline = time.monotonic() + 3
    for ordinal in range(64):
        value = client.call('node', 'get', NODE_ID)['data']['inventory']
        topology, cells = value['topology'], value['cellCapacity']
        require(topology['available'] and topology['complete'] and cells
                and all(row['observationAvailable'] for row in cells), 'typescript-library-owner-observation-unavailable')
        require(all(int(row['activeCount']) == 0 and int(row['configuredCount']) == 0
            for row in topology['entries'] if row['ownership'] == 'service-resident'), 'typescript-library-resident-owner')
        if (all(int(row['active']) == 0 and int(row['quarantined']) == 0 for row in cells)
                and int(value['queueDepth']) == 0 and all(int(count) == 0 for count in value['quotas']['usage'].values())
                and all(int(row['activeCount']) == 0 for row in topology['entries'] if row['ownership'] == 'activation-scoped')):
            record = {'phase': label, 'observations': ordinal + 1, 'inventory': value}
            write_json(output / (label + '-idle.json'), record)
            return record
        require(time.monotonic() < deadline, 'typescript-library-owner-reclamation-deadline')
        time.sleep(0.01)
    raise ValueError('typescript-library-owner-observation-limit')


def execute(root: Path, native: Path) -> dict:
    evidence = fresh(root / 'node')
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='typescript-libraries-node-') as temporary:
        work = Path(temporary)
        (work / 'client').mkdir()
        (work / 'node').mkdir()
        client = RecordingClient(native / 'latent', work / 'client', cancellation, time.monotonic() + 600,
            evidence=evidence / 'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
        config = configure_node(work / 'node', root / 'signed', 'examples')
        settings = read_json(config)
        settings['cells'][0]['maximumMemoryBytes'] = 134217728
        settings['execution']['maximumWallTimeMillis'] = 120000
        config.write_bytes(json.dumps(settings, separators=(',', ':')).encode())
        node = connect(client, native / 'latentd', work / 'node', config, 'examples', 1)
        try:
            idle(client, evidence, 'before-publication')
            package = root / 'signed/my-greeting'
            denied = client.call('release', 'publish-package', package / 'package', '--operation-id',
                'unsigned-denied', '--expected-generation', '0', codes=(4,))
            require(denied['error']['code'] == 'permission-denied', 'typescript-library-unsigned-package-admitted')
            published = client.call('release', 'publish-package', package / 'package', '--evidence',
                package / 'evidence/index.json', '--operation-id', 'publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, package / 'deployment.json', publication)
            calls = []
            for ordinal, (argument, expected, code) in enumerate((
                ('SDK', [{'ok': 'Hello, SDK!'}], 0),
                ('', [{'err': 'Please enter a name.'}], 3),
                ('Ada', [{'ok': 'Hello, Ada!'}], 0),
            )):
                observed = call(client, target, 'greeting', 'greet', [argument], 'typescript-library-' + str(ordinal))
                assert_value(client, observed, expected, code)
                require(observed['processReaped'], 'typescript-library-invocation-owner-not-reaped')
                calls.append(observed)
                idle(client, evidence, 'after-' + str(ordinal))
            stop(client, node)
            shutdown = stopped_record(node)
            require(shutdown['record']['clean'] and shutdown['reaped'], 'typescript-library-node-shutdown-unconfirmed')
            result = {'status': 'passed', 'scope': 'signed public-sync npm ESM/CJS/transitive/resource and fresh-state execution',
                      'unsignedDenied': denied, 'calls': calls, 'shutdown': shutdown}
            write_json(evidence / 'libraries-qualified.json', result)
            return result
        finally:
            node.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    boundary = parser.add_mutually_exclusive_group(required=True)
    boundary.add_argument('--resolve-only', action='store_true')
    boundary.add_argument('--offline', action='store_true')
    parser.add_argument('--tools', type=Path)
    parser.add_argument('--native-directory', type=Path)
    parser.add_argument('--native-tuple', type=Path)
    args = parser.parse_args(argv)
    root = args.output.absolute()
    require(root != ROOT and ROOT not in root.parents, 'typescript-library-output-must-stay-outside-checkout')
    if args.resolve_only:
        fresh(root)
    else:
        require((root / 'capture.json').is_file(), 'typescript-library-explicit-capture-required')
    commands = Commands(ROOT, fresh(root / ('execution' if args.offline else 'acquisition')),
        build_environment(root), deadline_seconds=1800, command_seconds=120)
    owner = file_identity(Path(__file__))
    stage = 'capture'
    try:
        captured = capture(root) if args.resolve_only else read_json(root / 'capture.json')
        app = root / 'application'
        require(digest(inventory(snapshot(app))) == captured['applicationIdentity'], 'typescript-library-source-drift')
        require(status(app)['capturedInputIdentity'] == captured['capturedInputs']['capturedInputIdentity'],
                'typescript-library-closure-drift')
        if args.resolve_only:
            print(json.dumps({'status': 'captured', 'runtimeQualification': False}))
            return 0
        require(all(value is not None for value in (args.tools, args.native_directory, args.native_tuple)),
                'typescript-library-native-and-compiler-inputs-required')
        stage = 'native-inputs'
        products = {name: args.native_directory / name for name in PRODUCTS}
        native_identity = ordinary_tuple(args.native_tuple, products)
        selected = fresh(root / 'selected-native')
        for name, original in products.items():
            shutil.copyfile(original, selected / name)
            (selected / name).chmod(0o700)
        require(ordinary_tuple(args.native_tuple, {name: selected / name for name in PRODUCTS}) == native_identity,
                'typescript-library-native-capture-changed')
        stage = 'negative-inputs'
        negative = negative_inputs(app)
        stage = 'offline-component'
        built = build(app, root / 'build', selected / 'capsule_contracts', selected / 'package',
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=args.tools)
        stage = 'explicit-fixture-signing'
        commands.run('sign-typescript-library-fixture', selected / 'capsule_authoring', 'demo-sign', root / 'signed', built)
        stage = 'signed-node'
        execution = execute(root, selected)
        stage = 'final-integrity'
        require(ordinary_tuple(args.native_tuple, products) == native_identity, 'typescript-library-native-products-mutated')
        require(file_identity(Path(__file__)) == owner, 'typescript-library-qualifier-mutated')
        require(digest(inventory(snapshot(app))) == captured['applicationIdentity'], 'typescript-library-final-source-drift')
        result = {'status': 'passed', 'scope': execution['scope'], 'capture': file_identity(root / 'capture.json'),
            'sourceRecipe': json.loads((built / 'recipe-inputs.json').read_bytes()),
            'nativeTuple': native_identity, 'qualifier': owner, 'negativeInputs': negative,
            'component': file_identity(built / 'component.wasm'), 'commands': commands.records,
            'execution': file_identity(root / 'node/libraries-qualified.json'),
            'remainingAcceptance': ['authenticated-private-registry', 'installed-update-remove-watch',
                'memory-fuel-cancellation-and-native-runtime-paths', 'explicit-generator-containment']}
        write_json(root / 'qualification.json', result)
        print(json.dumps({'status': 'passed', 'receipt': str(root / 'qualification.json')}))
        return 0
    except BaseException as error:
        write_json(root / 'FAILED.json', {'status': 'failed', 'stage': stage, 'commands': commands.records,
            'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
