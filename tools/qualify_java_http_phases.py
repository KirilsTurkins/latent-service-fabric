"""One fresh captured Java phase component using authenticated V7 native products."""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as inputs
from tools.application_dependency_store import Store
from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, FIBER_IO_PROFILE, build
from tools.java_dependency_authoring import review
from tools.java_guest.c_failure_context import FIXTURE_SOURCES
from tools.java_http_client import PHASE_PROFILE_ID
from tools.java_http_phase_fixture import project, SOURCE, WORLD
from tools.java_http_phase_node import run as node_controls
from tools.java_phase_native_products import native_products, verify_prepared
from tools.java_standard_http_library import COORDINATE, ORIGINAL_JAR, compiler_cache
from tools.qualify_java_published_http import PRIMARY, CHILD, PUBLISHED_CHECKSUMS, selected_jars
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

MAX_SECONDS = 1800
MATERIALS = tuple(dict.fromkeys((*RECIPE, SOURCE, WORLD,
    'tools/java_http_phase_fixture.py', 'tools/java_http_phase_node.py',
    'tools/qualify_java_http_phases.py', 'tools/java_phase_native_products.py',
    'tools/java_replay_materials.py', 'tools/java_standard_http_library.py',
    'tools/qualify_java_published_http.py', 'tools/java_standard_http_project.py',
    'tools/java_http_fiber_node.py', 'tools/java_standard_http_node.py',
    'tools/standard_http/peer.py', 'tools/standard_http/protocol.py',
    'tools/standard_http/vectors.py', 'tools/standard_http/observations.py',
    'tools/rust_capsule_node.py', 'tools/phase3_resource_identity.py',
    'tools/phase3_resource_profile.py', 'tools/phase3_resource_os.py',
    'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
    'tools/guest_runtime_profiles.py', 'tools/static_api/node.py')))


def selected_clients(candidate):
    """Validate the reviewed public fixture, never an application eligibility list."""
    from tools.java_resource_artifacts import PROFILE, resource_selection, resource_metadata
    rows = candidate['artifacts'];by_id = {row['id']: row for row in rows}
    require(len(rows) == len(by_id) <= inputs.MAX_ARTIFACTS, 'java-phase-duplicate-artifact')
    row = by_id.get(COORDINATE)
    require(row is not None and row['role'] == 'application' and row['format'] == 'file'
        and row['metadata'].get('scope') == 'selected-runtime'
        and row['metadata']['coordinates'] == COORDINATE and row['mount'].endswith('.jar')
        and row['original']['digest'] == ORIGINAL_JAR, 'java-phase-request-jar-drift')
    owned = []
    selection = row['metadata'].get('resourceSelection')
    if selection is not None:
        require(type(selection) is dict and selection.get('profile') == PROFILE
            and selection.get('release') == 25 and type(selection.get('entries')) is list
            and len(selection['entries']) <= inputs.MAX_ARTIFACTS, 'java-phase-resource-selection')
        entries = selection['entries']
        require(all(type(item) is dict and set(item) ==
            {'artifact', 'path', 'originalEntry', 'selectedVersion', 'digest', 'size'} for item in entries),
            'java-phase-resource-entry')
        require(selection == resource_selection(COORDINATE, ORIGINAL_JAR,
            [{key: value for key, value in item.items() if key != 'artifact'} for item in entries], 25),
            'java-phase-resource-selection-drift')
        for item in entries:
            name = item['artifact'];child = by_id.get(name)
            require(name not in owned and child is not None and child['role'] == 'resource'
                and child['format'] == 'file' and child['dependencies'] == []
                and child['mount'] == 'dependencies/java/resources/'+name.split(':', 1)[1]+'.bin'
                and child['metadata'] == resource_metadata(COORDINATE, ORIGINAL_JAR, item, 25)
                and child['original'] == {'digest': item['digest'], 'size': item['size']},
                'java-phase-owned-resource-drift')
            owned.append(name)
    require(row['dependencies'] == owned, 'java-phase-request-transitive-edge-drift')
    projected = {'artifacts': [item for item in rows if item['id'] not in [COORDINATE, *owned]]}
    webb = selected_jars(projected)
    return {**webb, COORDINATE: row}


def resolve_review(commands, app, candidate):
    sdk = read_file(app/'sdk-lock.json')
    commands.run('phase-clients-native-resolve', sys.executable, ROOT/'tools/java_capsule.py',
        'resolve', app, '--candidate', candidate, '--gradle', 'gradle')
    selected = selected_clients(read_json(candidate));store = Store(app/'dependency-inputs/objects', create=False)
    for name, row in selected.items():
        data = store.get(**row['original'])
        if name in PUBLISHED_CHECKSUMS:
            require(hashlib.sha1(data, usedforsecurity=False).hexdigest() == PUBLISHED_CHECKSUMS[name],
                    'java-phase-published-webb-jar-drift')
        else:
            require(digest(data) == ORIGINAL_JAR, 'java-phase-published-request-jar-drift')
    expected = digest(read_file(candidate, inputs.MAX_LOCK));review(app, candidate, expected)
    verified = inputs.verify_inputs(app, 'java')
    require(verified is not None and selected_clients(verified.lock) == selected
        and read_file(app/'sdk-lock.json') == sdk, 'java-phase-reviewed-closure-or-sdk-drift')
    return {'runtimeCoordinates': [PRIMARY, CHILD, COORDINATE], 'candidateDigest': expected,
        'acceptedLockDigest': digest(read_file(app/inputs.LOCK)),
        'originalJars': {name: row['original'] for name, row in selected.items()},
        'normalDependencyReview': True, 'sdkLockDigest': digest(sdk)}


def native_source(prepared):
    record = read_json(prepared/'native-products.json')
    current = source_identity(ROOT)
    require(current == record['source'], 'java-phase-current-native-production-source-drift')
    selected = {name: identity for name, identity in record['materials'].items()
        if name.startswith(('wit/', 'schemas/', 'examples/echo-contract/wit/'))
        or name == '.cargo/managed-guest.toml'}
    actual = {'.cargo/managed-guest.toml': file_identity(ROOT/'.cargo/managed-guest.toml')}
    for directory, maximum_files, maximum_bytes in (
            ('wit', 2048, 8*1024**2), ('schemas', 256, 4*1024**2),
            ('examples/echo-contract/wit', 128, 1024**2)):
        observed = inventory(ROOT/directory, maximum_files=maximum_files,
            maximum_bytes=maximum_bytes, deadline=time.monotonic()+30)
        actual.update({directory+'/'+row['path']: {key: row[key] for key in ('sha256', 'bytes')}
                       for row in observed['files']})
    require(len(selected) == 107 and selected == actual,
            'java-phase-current-native-auxiliary-input-drift')
    return {'native': current, 'auxiliaryInputs': selected, 'equalToCompiledProducer': True}


def execute(commands, binaries, wasi_sdk, output):
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in MATERIALS}
    products = {name: file_identity(path) for name, path in binaries.items()}
    stage = 'project'
    try:
        app = project(output/'application')
        stage = 'normal-resolve-review'
        captured = resolve_review(commands, app, output/'candidate.json')
        stage = 'compiler-cache'
        cache = compiler_cache(commands, wasi_sdk, output, None)
        stage = 'offline-phase-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 0, 'java-phase-original-build-deadline')
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
            timeout=remaining, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE,
            failure_contexts=FIXTURE_SOURCES)
        classpath = read_json(artifact/'java-classpath.json')
        actual = {row['id']: row['originalDigest'] for row in classpath['artifacts']}
        require(set(actual) == set(captured['originalJars'])
            and all(actual.get(name) == identity['digest'] for name, identity in captured['originalJars'].items()),
                'java-phase-actual-classpath-drift')
        profile = read_json(artifact/'http-client-profile.json')
        require(profile['profile'] == PHASE_PROFILE_ID
            and profile['componentDigest'] == digest(read_file(artifact/'component.wasm')),
            'java-phase-actual-selected-profile-drift')
        stage = 'signed-client-and-phase-controls'
        result = node_controls(artifact, {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output/'node', deadline=commands.deadline)
        require(result['status'] == 'passed' and len(result['cases']) == 16, 'java-phase-incomplete-node-programme')
        after = {name: file_identity(ROOT/name) for name in before}
        product_after = {name: file_identity(path) for name, path in binaries.items()}
        require(before == after and products == product_after and time.monotonic() < commands.deadline,
                'java-phase-final-source-or-product-drift')
        final = {'schemaVersion': 'latent.java.http-phase-campaign.v1', 'status': 'passed',
            'materials': before, 'nativeProducts': products, 'libraries': captured,
            'artifact': {name: file_identity(artifact/name) for name in ('component.wasm', 'BUILD-COMPLETE.json',
                'source-inputs.json', 'recipe-inputs.json', 'compiler-inputs.json', 'build-observation.json',
                'http-client-profile.json', 'runtime-profile.json', 'java-classpath.json')},
            'nodeReceipt': file_identity(output/'node/qualification.json'),
            'invocations': 16, 'authorityDenials': 2, 'httpContacts': 13,
            'full688Qualified': False, 'full741Qualified': False,
            'limitations': ['Explicit plain-HTTP phase profile only; HTTPS still catchably unsupported.',
                'Finite two ordinary clients and operation/root timeout-cancellation boundaries.',
                'No cross-tenant, optional transport SPI, whole runtime or release qualification.']}
        write_json(output/'final-materials.json', {'materials': after, 'nativeProducts': product_after})
        write_json(output/'qualification.json', final)
        return final
    except BaseException:
        try: write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'full688Qualified': False})
        except Exception: pass
        raise


def run(output, prepared, wasi_sdk):
    history = verify_prepared(prepared);source = native_source(prepared)
    output = fresh(output);environment = build_environment(output)
    if 'JAVA_HOME' in os.environ: environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output/'commands'), environment,
        deadline_seconds=MAX_SECONDS, command_seconds=300)
    result = execute(commands, native_products(prepared), wasi_sdk, output/'campaign')
    require(history == verify_prepared(prepared) and source == native_source(prepared),
            'java-phase-final-prepared-source-drift')
    result.update(schemaVersion='latent.java.http-phase-replay.v1', nativeSource=history,
        nativeProductionSourceProof=source, nativeRecompiledByConsumer=False,
        fixtureSource=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip())
    write_json(output/'qualification.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--wasi-sdk', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(sys.platform == 'linux' and output != ROOT and ROOT not in output.parents,
            'java-phase-owned-linux-output-required')
    run(output, args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))
