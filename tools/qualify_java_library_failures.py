#!/usr/bin/env python3
"""Actual captured-JAR native/reflection negatives and a signed ordinary call.

This programme retains compiler observations separately from compatibility
attribution. A failed compile alone never establishes elimination or reachability
of another method, and an unknown compatibility report remains unknown.
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

from tools import application_dependencies as dependencies, guest_compatibility
from tools.application_dependency_store import Store
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.build_snapshot import digest
from tools.guest_runtime_grants import configure as runtime_config, grant
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_build import build
from tools.java_capsule_project import create, validate_sdk_inputs
from tools.java_dependency_authoring import edit, review, status
from tools.java_dependency_resolution import resolve
from tools.phase2_operator_process import read_json, require, stopped_record, write_json
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_annotation_processors import observe_idle
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, assert_value, call, deploy
from tools.rust_capsule_project import ROOT, fresh, inventory, snapshot

PRODUCTS = ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')
LOCAL_ID = 'outside-runtime-owner/2026.10.16'
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'


def fixture(root: Path, commands: Commands, gradle: str) -> tuple[Path, str, dict]:
    library = fresh(root / 'independent-library')
    source, classes = library / 'source/outside/owner', library / 'classes'
    source.mkdir(parents=True)
    classes.mkdir()
    java = source / 'Surface.java'
    java.write_text('''package outside.owner;
public final class Surface {
    private Surface() {}
    public static String pure(String name) { return "Captured " + name; }
    public static native int nativeValue();
    public static String reflection() {
        return Surface.class.getGenericSuperclass().getTypeName();
    }
    public static void dynamicLoad(String library) { System.loadLibrary(library); }
}
''', encoding='utf-8')
    commands.run('independent-javac', 'javac', '--release', '17', '-proc:none', '-encoding', 'UTF-8',
                 '-d', classes, java)
    bytecode = commands.run('independent-javap', 'javap', '-p', '-s', '-classpath', classes,
                            'outside.owner.Surface')
    require('public static native int nativeValue();' in bytecode.decode('utf-8'),
            'java-library-native-method-not-compiled')
    native_source = library / 'native.c'
    native_source.write_text('int Java_outside_owner_Surface_nativeValue(void *env, void *owner) { return 42; }\n',
                             encoding='utf-8')
    native_library = library / 'liboutside.so'
    commands.run('independent-native-library', 'cc', '-shared', '-fPIC', '-nostdlib',
                 '-Wl,--no-undefined', '-o', native_library, native_source)
    require(native_library.read_bytes().startswith(b'\x7fELF'), 'java-library-native-elf-required')
    jar = library / 'original.jar'
    jar.write_bytes(deterministic_jar({
        'outside/owner/Surface.class': (classes / 'outside/owner/Surface.class').read_bytes(),
        'outside/owner/native/liboutside.so': native_library.read_bytes(),
        'outside/owner/proof.txt': b'unchanged native and reflection JAR\n',
    }))
    original = {'jar': file_identity(jar), 'nativeLibrary': file_identity(native_library),
                'javap': digest(bytecode)}
    app = create(root / 'application', 'greeting')
    capsule = app / 'src/dev/latent/app/Capsule.java'
    source_text = capsule.read_text(encoding='utf-8')
    require('"Hello, " + trimmed + "!"' in source_text, 'java-library-greeting-template-drift')
    edit(app, 'add-local', local_id=LOCAL_ID, jar=jar)
    candidate = root / 'candidate.json'
    resolve(app, candidate, gradle=gradle)
    review(app, candidate, digest(candidate.read_bytes()))
    verified = dependencies.verify_inputs(app, 'java')
    artifact = next(row for row in verified.lock['artifacts'] if row['id'] == LOCAL_ID)
    require(artifact['original']['digest'] == original['jar']['sha256'], 'java-library-original-jar-drift')
    require(Store(app / 'dependency-inputs/objects', create=False).get(
        artifact['original']['digest'], artifact['original']['size']) == jar.read_bytes(),
        'java-library-captured-original-jar-drift')
    native_resources = [row for row in verified.lock['artifacts'] if row['role'] == 'resource'
        and row['metadata'].get('jar') == LOCAL_ID
        and row['metadata'].get('path') == 'outside/owner/native/liboutside.so']
    require(len(native_resources) == 1
            and native_resources[0]['original']['digest'] == original['nativeLibrary']['sha256']
            and native_resources[0]['original']['size'] == original['nativeLibrary']['bytes'],
            'java-library-native-resource-not-captured')
    # The build must consume captured bytes, including the native resource;
    # neither the original JAR nor its source/classes/native output survives.
    shutil.rmtree(library)
    validate_sdk_inputs(snapshot(app))
    captured = {'status': 'captured', 'original': original, 'libraryStartupOnBuildHost': False,
                'hostNativeLibraryLoaded': False, 'originalInputsRemoved': True,
                'catalogueRegistration': False, 'capturedInputIdentity': status(app)['capturedInputIdentity'],
                'sdkLockDigest': digest((app / 'sdk-lock.json').read_bytes())}
    write_json(root / 'capture.json', captured)
    return app, source_text, captured


def compiler_negative(app: Path, output: Path, case: str, contracts: Path, packager: Path,
                      wasi_sdk: Path, parameters: dict) -> dict:
    before = inventory(snapshot(app))
    try:
        build(app, output, contracts, packager, REPOSITORY, wasi_sdk, **parameters)
    except ValueError as error:
        require(str(error) == 'Java compiler stage failed: java-to-c; see retained log',
                'java-library-negative-did-not-reach-native-compiler')
    else:
        raise RuntimeError('java-library-unsupported-case-compiled-' + case)
    failure = read_json(output / 'BUILD-FAILED.json')
    require(failure['stage'] == 'compile' and not (output / 'BUILD-COMPLETE.json').exists(),
            'java-library-negative-failure-stage')
    records = [row for row in failure['commands'] if row['stage'] == 'java-to-c']
    require(len(records) == 1 and records[0]['exitCode'] not in (None, 0),
            'java-library-negative-native-exit-required')
    logs = list((output / 'compiler-logs').glob('*-java-to-c.log'))
    require(len(logs) == 1, 'java-library-negative-compiler-log-required')
    text = logs[0].read_text(encoding='utf-8')
    if case == 'native-method':
        require('nativeValue' in text and 'native' in text.lower(),
                'java-library-native-diagnostic-missing')
    else:
        require('Method java.lang.Class.getGenericSuperclass()Ljava/lang/reflect/Type; was not found' in text,
                'java-library-reflection-diagnostic-missing')
    report = guest_compatibility.read((output / 'compatibility-report.json').read_bytes())
    require(report['sourceDigest'] == digest((output / 'source-inputs.json').read_bytes())
            and report['componentDigest'] is None,
            'java-library-negative-diagnostic-source-drift')
    require(not any(row['classification'] == 'unsupported-eliminated' for row in report['findings']),
            'java-library-failure-invented-elimination')
    attribution = guest_compatibility.read((output / 'compatibility-java-compiler-report.json').read_bytes())
    classification, symbol = (
        ('target-incompatible', 'outside.owner.Surface.nativeValue') if case == 'native-method'
        else ('missing-runtime-port', 'java.lang.Class.getGenericSuperclass'))
    require(attribution['sourceDigest'] == report['sourceDigest'] and attribution['componentDigest'] is None
            and attribution['authority'] == 'none' and attribution['status'] == 'blocked'
            and any(row['classification'] == classification and row.get('symbol') == symbol
                    and row['evidence'] == 'compiler' and row.get('ownerIssue') == 741
                    for row in attribution['findings']), 'java-library-negative-attribution-missing')
    require(not any(row['classification'] in {'unsupported-eliminated', 'missing-grant', 'denied-grant'}
                    for row in attribution['findings']), 'java-library-negative-attribution-widened')
    require(inventory(snapshot(app)) == before, 'java-library-negative-mutated-inputs')
    return {'case': case, 'status': 'known-compiler-failure', 'failure': failure,
            'compilerLog': file_identity(logs[0]), 'compatibility': report, 'compilerAttribution': attribution,
            'sourceInputs': file_identity(output / 'source-inputs.json'),
            'compilerInputs': file_identity(output / 'compiler-inputs.json')}


def execute(root: Path, native: Path, native_identity: dict) -> dict:
    evidence = fresh(root / 'node')
    with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='java-library-negatives-node-') as owned:
        work = Path(owned)
        for name in ('client', 'node'):
            (work / name).mkdir()
        client = RecordingClient(native / 'latent', work / 'client', cancellation,
                                 time.monotonic() + 180, evidence=evidence / 'controls')
        config = configure_node(work / 'node', root / 'signed', 'examples')
        settings = read_json(config)
        settings['engine'] = {'javaGuest': True}
        settings['providers'] = {'formatVersion': 1, 'bindings': []}
        audit = dict(settings['audit'])
        runtime_config(settings, ('greeting',), language='java')
        settings['audit'] = audit
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
                ('Ada', [{'ok': 'Captured Ada'}], 0), ('', [{'err': 'Please enter a name.'}], 3),
                ('SDK', [{'ok': 'Captured SDK'}], 0),
            )):
                observed = call(client, targets['greeting'], 'greeting', 'greet', [argument],
                                'library-negative-positive-' + str(ordinal))
                assert_value(client, observed, expected, code)
                require(observed['processReaped'], 'java-library-positive-owner-not-reaped')
                calls.append(observed)
                observe_idle(client, evidence, 'after-' + str(ordinal))
            stop(client, node)
            shutdown = stopped_record(node)
            require(shutdown['record']['clean'] and shutdown['reaped'], 'java-library-positive-node-shutdown-unconfirmed')
            result.update(status='passed', calls=calls, shutdown=shutdown,
                scope='signed ordinary entry from the same original JAR containing unused native/reflection operations')
            write_json(evidence / 'ordinary-qualified.json', result)
            return result
        finally:
            node.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'native-directory', 'native-tuple', 'wasi-sdk', 'read-only-cache'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--gradle', default='gradle')
    args = parser.parse_args(argv)
    require(args.output.absolute() != ROOT and ROOT not in args.output.absolute().parents,
            'java-library-negative-fixture-must-be-outside-runtime')
    root = fresh(args.output)
    products = {name: args.native_directory / name for name in PRODUCTS}
    native_identity = ordinary_tuple(args.native_tuple, products)
    native = fresh(root / 'native-products')
    for name, binary in products.items():
        shutil.copyfile(binary, native / name)
        (native / name).chmod(0o700)
    products = {name: native / name for name in PRODUCTS}
    require(ordinary_tuple(args.native_tuple, products) == native_identity, 'java-library-native-copy-drift')
    environment = build_environment(root)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, root, environment, deadline_seconds=1800, command_seconds=60)
    stage = 'outside-jar-capture'
    try:
        app, template, captured = fixture(root, commands, args.gradle)
        capsule = app / 'src/dev/latent/app/Capsule.java'
        parameters = dict(gradle=args.gradle, timeout=900, read_only_cache=args.read_only_cache)
        negatives = []
        for case, expression in (
            ('native-method', 'Integer.toString(outside.owner.Surface.nativeValue())'),
            ('generic-reflection', 'outside.owner.Surface.reflection()'),
        ):
            stage = case
            capsule.write_text(template.replace('"Hello, " + trimmed + "!"', expression), encoding='utf-8')
            negatives.append(compiler_negative(app, root / case, case, products['capsule_contracts'],
                                              products['package'], args.wasi_sdk, parameters))
            print(json.dumps({'stage': stage, 'status': 'known-compiler-failure'}), flush=True)
        stage = 'same-jar-ordinary-build'
        capsule.write_text(template.replace('"Hello, " + trimmed + "!"', 'outside.owner.Surface.pure(trimmed)'),
                           encoding='utf-8')
        before = inventory(snapshot(app))
        built = build(app, root / 'ordinary', products['capsule_contracts'], products['package'],
                      REPOSITORY, args.wasi_sdk, **parameters)
        require(inventory(snapshot(app)) == before, 'java-library-ordinary-mutated-inputs')
        stage = 'fixture-signing'
        commands.run('sign-fixture', products['capsule_authoring'], 'demo-sign', root / 'signed', built)
        stage = 'signed-ordinary-node'
        actual = execute(root, native, native_identity)
        require(ordinary_tuple(args.native_tuple, products) == native_identity, 'java-library-native-products-changed')
        require(time.monotonic() < commands.deadline, 'java-library-negative-programme-deadline')
        require(digest((app / 'sdk-lock.json').read_bytes()) == captured['sdkLockDigest'],
                'java-library-negative-sdk-lock-drift')
        write_json(root / 'qualification.json', {
            'schemaVersion': 'lsf.java.library.compiler-negatives.v1', 'status': 'passed',
            'scope': 'actual captured-JAR compiler negatives and signed ordinary same-JAR entry; no elimination claim',
            'capture': captured, 'nativeTuple': native_identity, 'negatives': negatives,
            'ordinaryComponent': file_identity(built / 'component.wasm'), 'ordinaryExecution': actual,
            'commands': commands.records,
        })
        print(json.dumps({'status': 'passed', 'receipt': str(root / 'qualification.json')}), flush=True)
    except BaseException as error:
        write_json(root / 'FAILED.json', {'status': 'failed', 'stage': stage, 'commands': commands.records,
            'reason': str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__})
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
