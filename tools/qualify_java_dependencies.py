#!/usr/bin/env python3
"""Bounded actual Java library capture, offline compilation and signed execution.

Resolution is a separate explicit network stage. Use --offline after acquisition
in a network-disabled host. Existing processor and installed frontend programmes
retain their independent acceptance boundaries.
"""
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
from tools.guest_runtime_grants import configure as runtime_config, grant
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_build import build
from tools.java_capsule_project import create, validate_sdk_inputs
from tools.java_dependency_authoring import edit, review, status
from tools.java_dependency_resolution import resolve
from tools.java_dependency_recovery import recover
from tools.phase2_operator_process import read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_annotation_processors import observe_idle
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, assert_value, call, deploy
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot

PRODUCTS = ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')
COORDINATES = ('org.apache.commons:commons-text:1.12.0', 'commons-codec:commons-codec:1.17.1')
TRANSITIVE = 'org.apache.commons:commons-lang3:3.14.0'


def fixture(root: Path, commands: Commands, gradle: str) -> dict:
    """Compile two outside-checkout JARs without executing library startup."""
    library = root / 'independent-library'
    source, classes = library / 'source/outside/owner', library / 'classes'
    source.mkdir(parents=True)
    classes.mkdir()
    (source / 'Child.java').write_text('''package outside.owner;
public final class Child {
    private Child() {}
    public static int increment(int value) { return value + 39; }
}
''', encoding='utf-8')
    (source / 'Arithmetic.java').write_text('''package outside.owner;
public final class Arithmetic {
    private Arithmetic() {}
    public static int increment(int value) { return Child.increment(value); }
    public static String resource() throws java.io.IOException {
        try (java.io.InputStream value = Arithmetic.class.getResourceAsStream("badge.txt")) {
            if (value == null) throw new java.io.IOException("captured-resource-not-visible");
            return new String(value.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        }
    }
    public static String loaderResource() throws java.io.IOException {
        ClassLoader loader = Arithmetic.class.getClassLoader();
        if (loader == null) throw new java.io.IOException("captured-loader-unavailable");
        try (java.io.InputStream missing = loader.getResourceAsStream("outside/owner/missing.txt")) {
            if (missing != null) throw new java.io.IOException("captured-loader-absence-incorrect");
        }
        try (java.io.InputStream first = loader.getResourceAsStream("outside/owner/badge.txt");
             java.io.InputStream second = loader.getResourceAsStream("outside/owner/badge.txt")) {
            if (first == null || second == null || first == second)
                throw new java.io.IOException("captured-loader-stream-owner-incorrect");
            int firstByte = first.read();
            if (firstByte != 'p' || second.read() != firstByte)
                throw new java.io.IOException("captured-loader-stream-position-incorrect");
            return "loader:" + (char) firstByte
                + new String(first.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        }
    }
}
''', encoding='utf-8')
    commands.run('independent-javac', 'javac', '--release', '17', '-proc:none', '-encoding', 'UTF-8',
                 '-d', classes, source / 'Child.java', source / 'Arithmetic.java')
    originals = {}
    for name, files in (
        ('child', {'outside/owner/Child.class': (classes / 'outside/owner/Child.class').read_bytes()}),
        ('primary', {'outside/owner/Arithmetic.class': (classes / 'outside/owner/Arithmetic.class').read_bytes(),
                     'outside/owner/badge.txt': b'private captured resource\n'}),
    ):
        jar = library / (name + '.jar')
        jar.write_bytes(deterministic_jar(files))
        originals[name] = {'path': str(jar), **file_identity(jar)}
    app = create(root / 'application', 'greeting')
    sdk = (app / 'sdk-lock.json').read_bytes()
    for coordinate in COORDINATES:
        edit(app, 'add', coordinate=coordinate)
    edit(app, 'add-local', local_id='outside-owner-child/2026.10.15', jar=library / 'child.jar')
    edit(app, 'add-local', local_id='outside-owner-primary/2026.10.15', jar=library / 'primary.jar',
         dependencies=('outside-owner-child/2026.10.15',))
    (app / 'src/dev/latent/app/Capsule.java').write_text('''package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.Result;
import org.apache.commons.text.similarity.LevenshteinDistance;
import org.apache.commons.codec.binary.Hex;
import org.apache.commons.lang3.StringUtils;
import outside.owner.Arithmetic;
public final class Capsule implements Bindings.Exports {
    private static int calls;
    private static byte[][] retained;
    public Result<String, String> greet(String name) {
        if (++calls != 1) return Result.err("activation-state-reused");
        if (name.isEmpty()) return Result.err("Please enter a name.");
        if (name.equals("resource")) {
            try { return Result.ok(Arithmetic.resource()); }
            catch (java.io.IOException failure) { return Result.err(failure.getMessage()); }
        }
        if (name.equals("resource-loader")) {
            try { return Result.ok(Arithmetic.loaderResource()); }
            catch (java.io.IOException failure) { return Result.err(failure.getMessage()); }
        }
        if (name.equals("throw")) throw new IllegalStateException("selected-library-error");
        if (name.equals("spin")) { while (true) calls++; }
        if (name.equals("heap")) {
            retained = new byte[8192][];
            for (int i = 0; i < retained.length; i++) retained[i] = new byte[4096];
            return Result.err("java-heap-limit-not-enforced");
        }
        int distance = LevenshteinDistance.getDefaultInstance().apply("kitten", "sitting");
        return Result.ok(Arithmetic.increment(distance) + "/" +
            Hex.encodeHexString(name.getBytes(java.nio.charset.StandardCharsets.UTF_8)) + "/" +
            StringUtils.reverse(name));
    }
}
''', encoding='utf-8')
    candidate = root / 'library-candidate.json'
    captured = resolve(app, candidate, gradle=gradle)
    by_id = {row['id']: row for row in captured['artifacts']}
    require(set(COORDINATES) | {TRANSITIVE, 'outside-owner-primary/2026.10.15',
            'outside-owner-child/2026.10.15'} <= by_id.keys(), 'java-library-selected-graph-incomplete')
    require(TRANSITIVE in by_id[COORDINATES[0]]['dependencies'], 'java-library-native-transitive-edge-missing')
    require(any(row['role'] == 'resource' for row in captured['artifacts']), 'java-library-resource-child-missing')
    review(app, candidate, digest(candidate.read_bytes()))
    for original in originals.values():
        Path(original['path']).unlink()
    require((app / 'sdk-lock.json').read_bytes() == sdk, 'java-library-capture-changed-sdk-lock')
    validate_sdk_inputs(snapshot(app))
    result = {'status': 'captured', 'scope': 'real native Maven resolution and compiled external local JARs',
              'sdkLockDigest': digest(sdk), 'applicationIdentity': digest(inventory(snapshot(app))), 'originalJars': originals,
              'capturedInputIdentity': status(app)['capturedInputIdentity'], 'originalJarsRemoved': True,
              'libraryStartupOnBuildHost': False, 'catalogueRegistration': False}
    write_json(root / 'capture.json', result)
    return result


def negative_inputs(app: Path, output: Path) -> list[dict]:
    """Exercise exact accepted bytes, preserving the original failure outcomes."""
    before = inventory(snapshot(app))
    verified = dependencies.verify_inputs(app, 'java')
    require(verified is not None, 'java-library-accepted-inputs-required')
    accepted = (app / dependencies.LOCK).read_bytes()
    records = []
    store = Store(app / 'dependency-inputs/objects', create=False)
    artifact = next(row for row in verified.lock['artifacts'] if row['id'] == TRANSITIVE)
    selected = store.path(artifact['original']['digest'])
    original = selected.read_bytes()
    for name, mutation in (('missing-transitive', None), ('tampered-transitive', b'changed same-name-version bytes')):
        if mutation is None:
            selected.unlink()
        else:
            selected.write_bytes(mutation)
        try:
            dependencies.verify_inputs(app, 'java')
        except DependencyError as error:
            expected = ('dependency-artifact-missing-resolve-explicitly' if mutation is None
                        else 'dependency-artifact-integrity')
            require(str(error) == expected, 'java-library-negative-wrong-failure')
            records.append({'case': name, 'status': 'known-failure', 'reason': expected})
        else:
            raise RuntimeError('java-library-corrupt-transitive-accepted')
        finally:
            selected.write_bytes(original)
        require((app / dependencies.LOCK).read_bytes() == accepted, 'java-library-negative-overwrote-accepted-lock')
    require(inventory(snapshot(app)) == before, 'java-library-negative-source-not-restored')
    write_json(output / 'negative-inputs.json', {'status': 'passed', 'cases': records})
    return records


def execute(root: Path, native: Path, native_identity: dict) -> dict:
    evidence = fresh(root / 'node')
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='java-libraries-node-') as temporary:
        work = Path(temporary)
        for name in ('client', 'node'):
            (work / name).mkdir()
        client = RecordingClient(native / 'latent', work / 'client', cancellation,
                                 time.monotonic() + 600, evidence=evidence / 'controls',
                                 invocation_timeout_millis=120000, control_timeout_millis=125000)
        config = configure_node(work / 'node', root / 'signed', 'examples')
        settings = read_json(config)
        settings['engine'] = {'javaGuest': True}
        settings['providers'] = {'formatVersion': 1, 'bindings': []}
        original_audit = dict(settings['audit'])
        runtime_config(settings, ('greeting',), language='java')
        settings['audit'] = original_audit
        settings['execution']['maximumWallTimeMillis'] = 120000
        settings['budgetProfile'] = {'mode': 'phase3', 'maximumOutboundRequests': 8,
                                    'maximumBlobReadBytes': 65536, 'maximumBlobWriteBytes': 65536}
        settings['capabilityPolicies'] = {'formatVersion': 1, 'maximumControlJobs': 2, 'store': {
            'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
            'maximumReadOwners': 64, 'maximumPageRecords': 16}}
        config.write_bytes(json.dumps(settings, separators=(',', ':')).encode())
        node = connect(client, native / 'latentd', work / 'node', config, 'examples', 1)
        try:
            observe_idle(client, evidence, 'before-publication')
            package = root / 'signed/my-greeting'
            unsigned = client.call('release', 'publish-package', package / 'package', '--operation-id',
                                   'unsigned-denied', '--expected-generation', '0', codes=(4,))
            require(unsigned['error']['code'] == 'permission-denied', 'java-library-unsigned-package-admitted')
            published = client.call('release', 'publish-package', package / 'package', '--evidence',
                package / 'evidence/index.json', '--operation-id', 'publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            targets = {'greeting': deploy(client, package / 'deployment.json', publication)}
            result = {'nativeTuple': native_identity, 'unsignedDenied': unsigned}
            grant(client, node, root / 'signed', targets, {'greeting': publication}, result, language='java')
            calls = []
            for ordinal, (argument, expected, code) in enumerate((
                ('SDK', [{'ok': '42/53444b/KDS'}], 0),
                ('resource', [{'ok': 'private captured resource\n'}], 0),
                ('resource-loader', [{'ok': 'loader:private captured resource\n'}], 0),
                ('', [{'err': 'Please enter a name.'}], 3),
                ('Ada', [{'ok': '42/416461/adA'}], 0),
            )):
                observed = call(client, targets['greeting'], 'greeting', 'greet', [argument], 'library-call-' + str(ordinal))
                assert_value(client, observed, expected, code)
                require(observed['processReaped'], 'java-library-invocation-owner-not-reaped')
                calls.append(observed)
                observe_idle(client, evidence, 'after-' + str(ordinal))
            recovery = recover(client, targets['greeting'], evidence)
            stop(client, node)
            shutdown = stopped_record(node)
            require(shutdown['record']['clean'] and shutdown['reaped'], 'java-library-node-shutdown-unconfirmed')
            result.update(status='passed', scope='signed captured Java code and exception/memory/fuel/cancellation recovery',
                          calls=calls, recovery=recovery, shutdown=shutdown)
            write_json(evidence / 'libraries-qualified.json', result)
            return result
        finally:
            node.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    boundary = parser.add_mutually_exclusive_group(required=True)
    boundary.add_argument('--resolve-only', action='store_true', help='Explicit acquisition; produces no runtime qualification')
    boundary.add_argument('--offline', action='store_true', help='Consume an already captured --resolve-only output')
    parser.add_argument('--native-directory', type=Path)
    parser.add_argument('--native-tuple', type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    parser.add_argument('--read-only-cache', type=Path)
    parser.add_argument('--gradle', default='gradle')
    args = parser.parse_args(argv)
    root = args.output.absolute()
    require(root != ROOT and ROOT not in root.parents, 'java-library-fixture-must-stay-outside-runtime')
    if args.offline:
        require(root.is_dir() and (root / 'capture.json').is_file(), 'java-library-explicit-acquisition-required')
    else:
        fresh(root)
    environment = build_environment(root)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    command_output = fresh(root / ('execution' if args.offline else 'acquisition'))
    commands = Commands(ROOT, command_output, environment, deadline_seconds=1800, command_seconds=60)
    qualifier_identity = file_identity(Path(__file__))
    recovery_identity = file_identity(Path(__file__).with_name('java_dependency_recovery.py'))
    stage = 'capture'
    try:
        captured = read_json(root / 'capture.json') if args.offline else fixture(root, commands, args.gradle)
        app = root / 'application'
        require(digest(inventory(snapshot(app))) == captured['applicationIdentity'], 'java-library-acquired-source-drift')
        require(status(app)['capturedInputIdentity'] == captured['capturedInputIdentity'], 'java-library-acquired-lock-drift')
        if args.resolve_only:
            print(json.dumps({'status': 'captured', 'runtimeQualification': False, 'output': str(root)}))
            return 0
        require(all(value is not None for value in (args.native_directory, args.native_tuple,
                args.wasi_sdk, args.read_only_cache)), 'java-library-native-and-offline-compiler-inputs-required')
        stage = 'native-inputs'
        products = {name: args.native_directory / name for name in PRODUCTS}
        native_identity = ordinary_tuple(args.native_tuple, products)
        selected = fresh(root / 'selected-native')
        for name, original in products.items():
            shutil.copyfile(original, selected / name)
            (selected / name).chmod(0o700)
        require(ordinary_tuple(args.native_tuple, {name: selected / name for name in PRODUCTS}) == native_identity,
                'java-library-native-capture-mutated')
        stage = 'negative-inputs'
        negatives = negative_inputs(app, root)
        stage = 'offline-compile'
        built = build(app, root / 'build', selected / 'capsule_contracts', selected / 'package',
            'https://github.com/KirilsTurkins/latent-service-fabric', args.wasi_sdk,
            gradle=args.gradle, read_only_cache=args.read_only_cache)
        stage = 'isolated-fixture-signing'
        commands.run('sign-library-fixture', selected / 'capsule_authoring', 'demo-sign', root / 'signed', built)
        stage = 'signed-node'
        execution = execute(root, selected, native_identity)
        stage = 'final-integrity'
        require(ordinary_tuple(args.native_tuple, products) == native_identity, 'java-library-original-native-products-mutated')
        require(ordinary_tuple(args.native_tuple, {name: selected / name for name in PRODUCTS}) == native_identity,
                'java-library-selected-native-products-mutated')
        require(file_identity(Path(__file__)) == qualifier_identity, 'java-library-qualifier-mutated')
        require(file_identity(Path(__file__).with_name('java_dependency_recovery.py')) == recovery_identity,
                'java-library-recovery-qualifier-mutated')
        require(digest(inventory(snapshot(app))) == captured['applicationIdentity'], 'java-library-source-mutated-after-compilation')
        result = {'status': 'passed', 'scope': execution['scope'], 'capture': file_identity(root / 'capture.json'),
            'nativeTuple': native_identity, 'qualifier': qualifier_identity, 'recoveryQualifier': recovery_identity,
            'negativeInputs': negatives,
            'component': file_identity(built / 'component.wasm'),
            'execution': file_identity(root / 'node/libraries-qualified.json'), 'commands': commands.records,
            'remainingAcceptance': ['authenticated-private-feed', 'installed-update-remove-watch',
                'approved-processor-containment']}
        write_json(root / 'qualification.json', result)
        print(json.dumps({'status': 'passed', 'receipt': str(root / 'qualification.json')}))
        return 0
    except BaseException as error:
        write_json(root / 'FAILED.json', {'status': 'failed', 'stage': stage, 'commands': commands.records,
            'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__})
        raise


if __name__ == '__main__':
    raise SystemExit(main())
