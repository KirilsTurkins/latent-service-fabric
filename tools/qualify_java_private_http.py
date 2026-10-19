#!/usr/bin/env python3
"""Captured outside local HTTP JARs through the ordinary signed provider gate."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as inputs
from tools.application_dependency_store import DependencyError, Store
from tools.build_observation import build_environment
from tools.java_application_dependencies import deterministic_jar
from tools.java_capsule_build import RECIPE, build
from tools.java_dependency_authoring import edit, review
from tools.java_dependency_resolution import resolve
from tools.guest_dependency_inputs import capture_source
from tools.java_standard_http_node import run as provider_controls
from tools.java_standard_http_project import project as standard_project
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_server_lifecycle import ordinary_tuple
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

IDENTITIES = (('outside.http.primary/1.0.7', 'outside.http.child/1.0.7'),
              ('tenant.example.unlisted-client/2026.10.19', 'different.owner.helper/4.2.1'))
RESOURCE = b'captured private HTTP helper\n'
PRODUCTS = ('latent', 'latentd', 'capsule_authoring', 'capsule_contracts', 'package')
MAX_SECONDS = 2400
MAX_BUILD_SECONDS = 900
EXPECTED_CASES = ('json', 'http404', 'http500', 'truncated', 'oversized', 'forbidden',
                  'early', 'redirect', 'post', 'uncertain', 'alternate-denied', 'direct-factory', 'fresh')
LIBRARY = '''package outside.http;
import java.io.IOException;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.Proxy;
import java.net.URL;
public final class Client implements AutoCloseable {
    private final HttpURLConnection connection;
    private Client(HttpURLConnection connection) { this.connection = connection; }
    public static Client open(String endpoint, boolean direct) throws IOException {
        Child.beforeRequest();
        URL url = new URL(endpoint);
        return new Client((HttpURLConnection) (direct ? url.openConnection(Proxy.NO_PROXY) : url.openConnection()));
    }
    public void post(byte[] bytes) throws IOException {
        connection.setRequestMethod("POST"); connection.setDoOutput(true);
        connection.setRequestProperty("Content-Type", "application/octet-stream");
        connection.setFixedLengthStreamingMode((long) bytes.length);
        try (var output = connection.getOutputStream()) { output.write(bytes); }
    }
    public void header(String name, String value) { connection.setRequestProperty(name, value); }
    public int status() throws IOException { return connection.getResponseCode(); }
    public InputStream stream() throws IOException {
        return status() >= 400 ? connection.getErrorStream() : connection.getInputStream();
    }
    public String body() throws IOException {
        try (InputStream input = stream()) {
            return new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8);
        }
    }
    @Override public void close() { connection.disconnect(); }
}
'''
CHILD = '''package outside.http;
public final class Child {
    private Child() {}
    public static void beforeRequest() throws java.io.IOException {
        try (var stream = Child.class.getResourceAsStream("badge.txt")) {
            if (stream == null || !new String(stream.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8)
                    .equals("captured private HTTP helper\\n")) {
                throw new java.io.IOException("captured-private-http-resource-mismatch");
            }
        }
    }
}
'''
APPLICATION = '''package dev.latent.app;
import dev.latent.generated.Bindings;
import dev.latent.guest.client.HttpFailure;
import outside.http.Client;
public final class Capsule implements Bindings.Exports {
    private static int calls;
    public String run(Long which, String endpoint) {
        int invocation = ++calls;
        try (Client request = Client.open(endpoint, which == 4)) {
            if (which == 1) request.post(new byte[] {0, 1, 2, 3});
            if (which == 3) request.header("Authorization", "must-not-leave-guest");
            int status = request.status();
            if (which != 2) return invocation + ":" + status + ":" + request.body();
            try (var input = request.stream()) { return invocation + ":early:" + input.read(new byte[4]); }
        } catch (Exception failure) {
            Throwable cause = failure;
            for (int n = 0; n < 8; n++) {
                if (cause instanceof HttpFailure typed) return invocation + ":transport:" + typed.code();
                if (cause.getCause() == null || cause.getCause() == cause) break;
                cause = cause.getCause();
            }
            return invocation + ":io-error";
        }
    }
}
'''


def make_jars(root, commands):
    """Only the explicit acquisition phase runs javac; no library startup runs."""
    source, classes = root / 'source/outside/http', root / 'classes'
    source.mkdir(parents=True)
    classes.mkdir()
    (source / 'Client.java').write_text(LIBRARY, encoding='utf-8')
    (source / 'Child.java').write_text(CHILD, encoding='utf-8')
    commands.run('private-http-javac', 'javac', '--release', '17', '-proc:none', '-encoding', 'UTF-8',
                 '-d', classes, source / 'Child.java', source / 'Client.java')
    jars = {}
    for name, members in (
        ('child', {'outside/http/Child.class': read_file(classes / 'outside/http/Child.class'),
                   'outside/http/badge.txt': RESOURCE}),
        ('primary', {'outside/http/Client.class': read_file(classes / 'outside/http/Client.class')}),
    ):
        path = root / (name + '.jar')
        with path.open('xb') as stream:
            stream.write(deterministic_jar(members))
        jars[name] = path
    return jars


def capture(root, jars, identities):
    require(identities in IDENTITIES and len(set(identities)) == 2, 'java-private-http-fixture-identity')
    app = standard_project(root / 'application')
    source = APPLICATION.encode('utf-8')
    (app / 'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app / 'sdk-lock.json')
    lock['template'].update(name='java-private-http', sourceDigest=digest(source))
    (app / 'sdk-lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    sdk = read_file(app / 'sdk-lock.json')
    primary, child = identities
    edit(app, 'add-local', local_id=child, jar=jars['child'])
    edit(app, 'add-local', local_id=primary, jar=jars['primary'], dependencies=(child,))
    candidate = root / 'capture.candidate.json'
    selected = resolve(app, candidate)
    by_id = {row['id']: row for row in selected['artifacts'] if row['role'] == 'application'}
    require(set(by_id) == set(identities) and by_id[primary]['dependencies'] == [child],
            'java-private-http-transitive-graph')
    review(app, candidate, digest(read_file(candidate)))
    require(read_file(app / 'sdk-lock.json') == sdk, 'java-private-http-sdk-drift')
    inputs.verify_inputs(app, 'java')
    return app, {'identities': list(identities), 'candidateDigest': digest(read_file(candidate)),
                 'acceptedLockDigest': digest(read_file(app / inputs.LOCK)), 'sdkLockDigest': digest(sdk),
                 'originalJars': {name: file_identity(path) for name, path in jars.items()},
                 'resourceDigest': digest(RESOURCE), 'normalDependencyReview': True}


def negative_inputs(app):
    verified = inputs.verify_inputs(app, 'java')
    accepted = read_file(app / inputs.LOCK)
    store = Store(app / 'dependency-inputs/objects', create=False)
    child = next(row for row in verified.lock['artifacts'] if row['id'] == IDENTITIES[0][1])
    path = store.path(child['original']['digest'])
    original = read_file(path)
    rows = []
    for name, mutation, expected in (
        ('missing-transitive', None, 'dependency-artifact-missing-resolve-explicitly'),
        ('tampered-transitive', b'changed same-identity child bytes', 'dependency-artifact-integrity'),
    ):
        if mutation is None:
            path.unlink()
        else:
            path.write_bytes(mutation)
        try:
            try:
                inputs.verify_inputs(app, 'java')
            except DependencyError as error:
                require(str(error) == expected, 'java-private-http-wrong-integrity-refusal')
            else:
                raise ValueError('java-private-http-invalid-transitive-accepted')
        finally:
            path.write_bytes(original)
        require(read_file(app / inputs.LOCK) == accepted, 'java-private-http-negative-changed-accepted-lock')
        rows.append({'case': name, 'reason': expected, 'acceptedLockPreserved': True})
    inputs.verify_inputs(app, 'java')
    return rows


def verify_node(node):
    require(node['status'] == 'passed' and node['cases'] == list(EXPECTED_CASES)
            and node['shutdown']['reaped'] is True and node['shutdown']['record']['clean'] is True
            and node['peerReaped'] is True
            and all(type(node['peer'][key]) is int for key in
                    ('startedRequests', 'rejectedRequests', 'committedMutations'))
            and node['peer']['startedRequests'] == 11 and node['peer']['rejectedRequests'] == 0
            and node['peer']['committedMutations'] == 1
            and all(row['role'] == 'primary' for row in node['peer']['requests']),
            'java-private-http-signed-provider-incomplete')


def qualify(output, native, native_tuple, wasi_sdk, read_only_cache):
    require(sys.platform == 'linux', 'java-private-http-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'java-private-http-outside-source-required')
    output = fresh(output)
    deadline = time.monotonic() + MAX_SECONDS
    environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output / 'acquisition'), environment,
                        deadline_seconds=MAX_SECONDS, command_seconds=60)
    commands.deadline = deadline
    materials = {name: file_identity(ROOT / name) for name in
                 (*dict.fromkeys(RECIPE), 'tools/qualify_java_private_http.py', 'tools/java_standard_http_node.py')}
    binaries = {name: native / name for name in PRODUCTS}
    before = {name: file_identity(path) for name, path in binaries.items()}
    native_source = ordinary_tuple(native_tuple, binaries)
    native_receipt = file_identity(native_tuple)
    rows, phase = [], 'outside-jar-acquisition'
    try:
        library = fresh(output / 'original-library')
        jars = make_jars(library, commands)
        projects = []
        for ordinal, identities in enumerate(IDENTITIES):
            root = fresh(output / ('variant-' + str(ordinal)))
            app, captured = capture(root, jars, identities)
            projects.append((root, app, captured))
        require(len({captured['sdkLockDigest'] for _, _, captured in projects}) == 1
                and len({identity for _, _, captured in projects for identity in captured['identities']}) == 4,
                'java-private-http-varied-identity-or-sdk-drift')
        negatives = negative_inputs(projects[0][1])
        shutil.rmtree(library)
        require(not library.exists(), 'java-private-http-originals-not-removed')
        compiler_inputs = None
        for ordinal, (root, app, captured) in enumerate(projects):
            phase = 'variant-' + str(ordinal) + '-offline-build'
            source = inventory(snapshot(app))
            captured_source = inventory(capture_source(app, 'java').files)
            remaining = min(MAX_BUILD_SECONDS, deadline - time.monotonic())
            require(remaining > 0, 'java-private-http-original-deadline-expired')
            artifact = build(app, root / 'build', binaries['capsule_contracts'], binaries['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
                timeout=remaining, read_only_cache=read_only_cache)
            require(not library.exists() and inventory(snapshot(app)) == source,
                    'java-private-http-original-or-reviewed-source-drift')
            require(read_file(artifact / 'source-inputs.json') == captured_source,
                    'java-private-http-compiled-source-drift')
            classpath = read_json(artifact / 'java-classpath.json')
            selected = {row['id']: row for row in classpath['artifacts']}
            require(set(selected) == set(captured['identities']), 'java-private-http-compiled-classpath')
            for name, identity in zip(('primary', 'child'), captured['identities'], strict=True):
                require(selected[identity]['originalDigest'] == captured['originalJars'][name]['sha256'],
                        'java-private-http-compiled-original-jar')
            require(any(row['owner'] == captured['identities'][1]
                        and row['path'] == 'outside/http/badge.txt' for row in classpath['resources']),
                    'java-private-http-compiled-transitive-resource')
            recipe = read_json(artifact / 'recipe-inputs.json')
            require(recipe == {name: {'digest': materials[name]['sha256'], 'size': materials[name]['bytes']}
                              for name in RECIPE}
                    and not any('compatibility-catalogue/' in name for name in recipe),
                    'java-private-http-catalogue-data-input')
            actual_compiler = read_file(artifact / 'compiler-inputs.json', 8 * 1024 * 1024)
            require(compiler_inputs is None or compiler_inputs == actual_compiler,
                    'java-private-http-compiler-input-drift')
            compiler_inputs = actual_compiler
            phase = 'variant-' + str(ordinal) + '-signed-provider'
            node = provider_controls(artifact, {name: binaries[name] for name in
                ('latent', 'latentd', 'capsule_authoring')}, root / 'node', deadline=deadline)
            verify_node(node)
            rows.append({'ordinal': ordinal, 'capture': captured, 'originalsRemovedBeforeBuild': True,
                'component': file_identity(artifact / 'component.wasm'),
                'sourceInputs': file_identity(artifact / 'source-inputs.json'),
                'recipeInputs': file_identity(artifact / 'recipe-inputs.json'),
                'compilerInputs': file_identity(artifact / 'compiler-inputs.json'),
                'runtimeProfile': file_identity(artifact / 'http-client-profile.json'),
                'providerReceipt': file_identity(root / 'node/qualification.json'),
                'cases': node['cases'], 'shutdown': node['shutdown'], 'peer': node['peer'],
                'catalogueDataInputs': [], 'applicationTransportInjected': False})
        require(materials == {name: file_identity(ROOT / name) for name in materials}
                and before == {name: file_identity(path) for name, path in binaries.items()}
                and native_receipt == file_identity(native_tuple)
                and time.monotonic() < deadline, 'java-private-http-final-material-drift')
        result = {'schemaVersion': 'latent.java.private-http.qualification.v1', 'status': 'passed',
            'materials': materials, 'nativeProducts': before, 'nativeSource': native_source,
            'variants': rows, 'negativeControls': negatives,
            'privateHttpInvocations': 26, 'libraryStartupOnBuildHost': False,
            'publishedSecondClientQualified': False, 'fullTicketQualification': False,
            'limitations': ['Plain HTTP synchronous URLConnection profile; no new HTTPS or phase-timeout semantics.',
                'Historical native products stay source-attributed; no new native host compilation claim.',
                'Sampled native RSS is not an allocator/kernel upper-bound proof.']}
        write_json(output / 'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'phase': phase,
                'completedVariants': len(rows), 'fullTicketQualification': False})
        except Exception:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--native-tuple', type=Path, required=True)
    parser.add_argument('--wasi-sdk', type=Path, required=True)
    parser.add_argument('--read-only-cache', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.output.resolve(), args.native.resolve(),
        args.native_tuple.resolve(), args.wasi_sdk.resolve(), args.read_only_cache.resolve())['status']}))
