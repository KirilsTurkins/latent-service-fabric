"""Two unchanged published clients through the same ordinary HTTP profile."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import application_dependencies as inputs
from tools.application_dependency_store import Store
from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, build
from tools.java_dependency_authoring import edit, review
from tools.java_standard_http_library import SOURCE as FIRST_SOURCE, compiler_cache, qualify as first_client
from tools.java_standard_http_node import run as provider_controls
from tools.java_standard_http_project import project as standard_project
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_private_http import PRODUCTS, ordinary_tuple, verify_node
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

SOURCE = 'examples/java-david-webb/Capsule.java'
PRIMARY = 'com.goebl:david-webb:1.3.0'
CHILD = 'org.json:json:20080701'
# Published immutable-version Maven checksum sidecars, additional to normal
# SHA256 capture/CAS/review. These never replace the accepted lock's identities.
PUBLISHED_CHECKSUMS = {
    PRIMARY: 'eac1af2022b5b52d49b72faf043f3cd39bfe9607',
    CHILD: 'd652f102185530c93b66158b1859f35d45687258',
}
MAX_SECONDS = 2400


def selected_jars(candidate):
    jars = [row for row in candidate['artifacts']
            if row['metadata'].get('scope') == 'selected-runtime']
    selected = {row['id']: row for row in jars}
    require(len(jars) == 2 and set(selected) == {PRIMARY, CHILD}
            and selected[PRIMARY]['dependencies'] == [CHILD]
            and selected[CHILD]['dependencies'] == [], 'java-webb-reviewed-closure-changed')
    require(all(row['role'] == 'application' and row['format'] == 'file'
                and row['metadata']['coordinates'] == row['id']
                and row['mount'].endswith('.jar') for row in jars), 'java-webb-reviewed-jar-kind')
    return selected


def project(directory):
    app = standard_project(directory)
    source = read_file(ROOT / SOURCE)
    (app / 'src/dev/latent/app/Capsule.java').write_bytes(source)
    lock = read_json(app / 'sdk-lock.json')
    lock['template'].update(name='java-david-webb', sourceDigest=digest(source))
    (app / 'sdk-lock.json').write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    edit(app, 'add', coordinate=PRIMARY)
    return app


def resolve_review(commands, app, candidate):
    sdk = read_file(app / 'sdk-lock.json')
    commands.run('webb-native-resolve', sys.executable, ROOT / 'tools/java_capsule.py',
                 'resolve', app, '--candidate', candidate, '--gradle', 'gradle')
    raw = read_file(candidate, inputs.MAX_LOCK)
    selected = selected_jars(read_json(candidate))
    store = Store(app / 'dependency-inputs/objects', create=False)
    identities = {}
    for name, row in selected.items():
        data = store.get(**row['original'])
        require(hashlib.sha1(data, usedforsecurity=False).hexdigest() == PUBLISHED_CHECKSUMS[name],
                'java-webb-published-original-changed-review-required')
        identities[name] = row['original']
    expected = digest(raw)
    review(app, candidate, expected)
    verified = inputs.verify_inputs(app, 'java')
    require(read_file(app / 'sdk-lock.json') == sdk and verified is not None
            and selected_jars(verified.lock) == selected, 'java-webb-reviewed-sdk-or-closure-drift')
    return {'coordinate': PRIMARY, 'transitiveCoordinate': CHILD,
            'candidateDigest': expected, 'acceptedLockDigest': digest(read_file(app / inputs.LOCK)),
            'originalJars': identities, 'normalDependencyReview': True,
            'nativeAcquisition': 'owned-temporary-Gradle-workspace-destroyed-on-resolver-return',
            'sdkLockDigest': digest(sdk)}


def execute(commands, binaries, wasi_sdk, output, *, read_only_cache=None):
    """No native build; use already authenticated products and one deadline."""
    output = fresh(output)
    before = {name: file_identity(ROOT / name) for name in
              (*dict.fromkeys(RECIPE), SOURCE, FIRST_SOURCE, 'tools/qualify_java_published_http.py',
               'tools/java_standard_http_node.py', 'tools/java_standard_http_library.py',
               'tools/qualify_java_private_http.py', 'tools/qualify_java_server_lifecycle.py')}
    products = {name: file_identity(path) for name, path in binaries.items()}
    cache = compiler_cache(commands, wasi_sdk, fresh(output / 'compiler'), read_only_cache)
    aliases = dict(binaries, **{'examples/' + name: binaries[name]
                              for name in ('package', 'capsule_contracts', 'capsule_authoring')})
    first = first_client(commands, aliases, wasi_sdk, output / 'http-request', read_only_cache=cache)
    verify_node(read_json(output / 'http-request/provider/qualification.json'))
    app = project(output / 'webb-application')
    capture = resolve_review(commands, app, output / 'webb-candidate.json')
    captured = inputs.verify_inputs(app, 'java')
    source = inventory(snapshot(app))
    from tools.guest_dependency_inputs import capture_source
    captured_source = inventory(capture_source(app, 'java').files)
    remaining = min(900, commands.deadline - time.monotonic())
    require(remaining > 0, 'java-published-http-original-deadline-expired')
    artifact = build(app, output / 'webb-build', binaries['capsule_contracts'], binaries['package'],
        'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
        timeout=remaining, read_only_cache=cache)
    require(inventory(snapshot(app)) == source and inputs.verify_inputs(app, 'java').lock == captured.lock
            and read_file(artifact / 'source-inputs.json') == captured_source,
            'java-webb-built-source-or-lock-drift')
    classpath = read_json(artifact / 'java-classpath.json')
    selected = {row['id']: row for row in classpath['artifacts']}
    require(set(selected) == {PRIMARY, CHILD}
            and all(selected[name]['originalDigest'] == capture['originalJars'][name]['digest']
                    for name in selected), 'java-webb-compiled-original-jar-drift')
    recipe = read_json(artifact / 'recipe-inputs.json')
    require(recipe == {name: {'digest': before[name]['sha256'], 'size': before[name]['bytes']}
                       for name in RECIPE}
            and not any('compatibility-catalogue/' in name for name in recipe),
            'java-webb-recipe-or-catalogue-input')
    node = provider_controls(artifact, {name: binaries[name] for name in
        ('latent', 'latentd', 'capsule_authoring')}, output / 'webb-node', deadline=commands.deadline)
    verify_node(node)
    # Both clients really compile against the same current tool distribution.
    require(read_file(output / 'http-request/build/compiler-inputs.json', 8 * 1024**2)
            == read_file(artifact / 'compiler-inputs.json', 8 * 1024**2),
            'java-published-http-compiler-closure-drift')
    require(before == {name: file_identity(ROOT / name) for name in before}
            and products == {name: file_identity(path) for name, path in binaries.items()}
            and time.monotonic() < commands.deadline, 'java-published-http-final-material-drift')
    result = {'schemaVersion': 'latent.java.published-http.qualification.v1', 'status': 'passed',
        'materials': before, 'nativeProducts': products, 'httpRequest': first,
        'webb': {'capture': capture, 'classpath': classpath,
                 'component': file_identity(artifact / 'component.wasm'),
                 'sourceInputs': file_identity(artifact / 'source-inputs.json'),
                 'recipeInputs': file_identity(artifact / 'recipe-inputs.json'),
                 'compilerInputs': file_identity(artifact / 'compiler-inputs.json'),
                 'runtimeProfile': file_identity(artifact / 'http-client-profile.json'),
                 'providerReceipt': file_identity(output / 'webb-node/qualification.json'),
                 'cases': node['cases'], 'peer': node['peer'], 'shutdown': node['shutdown']},
        'publishedClientInvocations': 26, 'applicationTransportInjected': False,
        'full688Qualification': False, 'full741Qualification': False,
        'limitations': ['Plain HTTP synchronous factories; no HTTPS or asynchronous worker claim.',
            'Explicit ordinary zero phase-timeout settings preserve the enclosing activation deadline.',
            'No publisher-authenticated release or allocator/kernel upper-bound claim.']}
    write_json(output / 'qualification.json', result)
    return result


def qualify(output, native, native_tuple, wasi_sdk, read_only_cache):
    require(sys.platform == 'linux', 'java-published-http-linux-required')
    require(output != ROOT and ROOT not in output.parents, 'java-published-http-outside-source-required')
    output = fresh(output)
    environment = build_environment(output)
    if 'JAVA_HOME' in os.environ:
        environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output / 'commands'), environment,
                        deadline_seconds=MAX_SECONDS, command_seconds=300)
    binaries = {name: native / name for name in PRODUCTS}
    native_source = ordinary_tuple(native_tuple, binaries)
    native_before = file_identity(native_tuple)
    try:
        result = execute(commands, binaries, wasi_sdk, output / 'campaign', read_only_cache=read_only_cache)
        require(file_identity(native_tuple) == native_before, 'java-published-http-native-tuple-drift')
        result['nativeSource'] = native_source
        write_json(output / 'qualification.json', result)
        return result
    except BaseException:
        try:
            write_json(output / 'FAILED.json', {'status': 'failed', 'full688Qualification': False,
                                               'full741Qualification': False})
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
    result = qualify(*(getattr(args, name).resolve() for name in
        ('output', 'native', 'native_tuple', 'wasi_sdk', 'read_only_cache')))
    print(json.dumps({'status': result['status']}))
