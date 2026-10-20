"""Build only two clock probes against authenticated existing engine/native inputs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.go_entropy_replay_inputs import NoRedirect, Remote
from tools.replay_typescript_standard_entropy import NORMAL, historical, package_inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.typescript_guest.build import build
from tools.typescript_guest.runtime_profile import CLOCK_PROFILE
from tools.typescript_standard_clock_fixture import closed_project, selected_project

ENGINE = {'sha256': 'sha256:c2394ccbcb7f39bf6264fd6b2208349a7d072a82d61074629b14c51ad9e88fa7', 'bytes': 10146325}
ENGINE_RECEIPT = 'sha256:385624cf28f1b700bd8364c77549a5dda34dbe6735fcf21ac86f140f8b24715c'
ENGINE_ARTIFACT = 12223506878
ENGINE_MEMBERS = {'_temp/typescript-native-engine/engine.wasm': ('engine.wasm', ENGINE['bytes']),
                  '_temp/typescript-native-engine/engine-input.json': ('engine-input.json', 6936)}


def engine_selection(entries):
    names = [entry.filename for entry in entries]
    require(len(names) == len(set(names)) <= 65536, 'typescript-clock-engine-unique-index')
    selected = [entry for entry in entries if entry.filename in ENGINE_MEMBERS]
    require(len(selected) == 2, 'typescript-clock-engine-fixed-members')
    for entry in selected:
        require(not entry.is_dir() and not stat.S_ISLNK(entry.external_attr >> 16) and not entry.flag_bits & 1
                and entry.file_size == ENGINE_MEMBERS[entry.filename][1], 'typescript-clock-engine-member-shape')
    return selected


def acquire_engine(output):
    output = fresh(output)
    credential = os.environ.get('GH_TOKEN')
    require(type(credential) is str and 0 < len(credential) <= 4096, 'typescript-clock-engine-read-credential')
    endpoint = f'https://api.github.com/repos/KirilsTurkins/latent-service-fabric/actions/artifacts/{ENGINE_ARTIFACT}'
    headers = {'Authorization': 'Bearer '+credential, 'Accept': 'application/vnd.github+json'}
    with urllib.request.urlopen(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
        require(response.status == 200, 'typescript-clock-engine-metadata-status')
        raw = response.read(65537)
    require(len(raw) <= 65536, 'typescript-clock-engine-metadata-bound')
    metadata = json.loads(raw)
    require(metadata['id'] == ENGINE_ARTIFACT and metadata['workflow_run']['id'] == 39319524998
            and metadata['workflow_run']['head_sha'] == '02fbe2f9ed5c2cec6f568ebc7cce99216a12631e'
            and not metadata['expired'] and type(metadata['size_in_bytes']) is int
            and 0 < metadata['size_in_bytes'] <= 256*1024**2, 'typescript-clock-engine-original-artifact')
    try:
        urllib.request.build_opener(NoRedirect).open(urllib.request.Request(endpoint+'/zip', headers=headers), timeout=30)
    except urllib.error.HTTPError as error:
        require(error.code == 302, 'typescript-clock-engine-download-redirect')
        url = error.headers['Location']
    else:
        raise ValueError('typescript-clock-engine-redirect-required')
    parsed = urllib.parse.urlsplit(url)
    require(parsed.scheme == 'https' and parsed.hostname is not None and parsed.username is None
            and (parsed.hostname.endswith('.blob.core.windows.net') or parsed.hostname.endswith('.githubusercontent.com')),
            'typescript-clock-engine-download-origin')
    del credential, headers
    remote = Remote(url, metadata['size_in_bytes'], maximum_requests=64)
    with zipfile.ZipFile(remote) as archive:
        for item in engine_selection(archive.infolist()):
            name, size = ENGINE_MEMBERS[item.filename]
            with archive.open(item) as source, (output/name).open('xb') as target:
                written = 0
                while raw := source.read(1024**2):
                    written += len(raw)
                    require(written <= size, 'typescript-clock-engine-decompression-bound')
                    target.write(raw)
            require(written == size, 'typescript-clock-engine-exact-member-size')
    _core, _receipt, identity = engine_inputs(output)
    record = {'originalRun': 39319524998, 'artifactId': ENGINE_ARTIFACT,
        'rangeRequests': remote.requests, 'networkBytes': remote.network_bytes, 'selected': identity,
        'completeArchiveDownloaded': False, 'credentialsRetained': False}
    write_json(output/'acquisition.json', record)
    return record


def engine_inputs(directory):
    core, receipt = directory/'engine.wasm', directory/'engine-input.json'
    require(file_identity(core, 16*1024**2) == ENGINE and digest(read_file(receipt)) == ENGINE_RECEIPT,
            'typescript-clock-authenticated-original-engine')
    document = read_json(receipt)
    require(document['profile'] == CLOCK_PROFILE and document['coreDigest'] == ENGINE['sha256']
            and document['coreBytes'] == ENGINE['bytes'] and len(document['sdkInputs']) == 31,
            'typescript-clock-exact-original-engine-envelope')
    for row in document['sdkInputs']:
        name = row['path']
        require(type(name) is str and name.startswith(('sdk/typescript-guest/', 'tools/typescript_guest/', 'wit/platform/'))
                and ':' not in name and '\\' not in name and all(p not in {'', '.', '..'} for p in name.split('/')),
                'typescript-clock-engine-SDK-path')
        raw = read_file(ROOT/name)
        require({'digest': digest(raw), 'size': len(raw)} == {key: row[key] for key in ('digest', 'size')},
                'typescript-clock-original-engine-SDK-changed')
    return core, receipt, {'engine': ENGINE, 'receipt': file_identity(receipt), 'SDKInputs': 31,
        'rebuilt': False, 'receiptRebound': False, 'originalRun': 39319524998, 'originalArtifact': 12223506878}


def companions(acquired, products, receipt, commands):
    selected, markers = {}, {}
    for name in TEMPLATES:
        if name in {'greeting', 'word-count'}: continue
        directory = acquired/(NORMAL+'builds/'+name)
        marker = read_json(directory/'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][name] and marker['packageAssembled'] is True,
                'typescript-clock-historical-companion-marker')
        for filename, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'), ('build-observation.json', 'observationDigest')):
            require(digest(read_file(directory/filename, 64*1024**2)) == marker[field],
                    'typescript-clock-historical-companion-bytes')
        original = package_inputs(directory)
        commands.run('package-companion-'+name, products['examples/package'], 'build', directory/'package-source.json', directory, directory/'package')
        require(package_inputs(directory) == original, 'typescript-clock-historical-companion-changed')
        selected[name], markers[name] = directory, {'originalMarker': marker, 'packageInputs': original}
    return selected, markers


def snapshot_controls(project, core, envelope, products, tools, output):
    from tools.qualify_typescript_dependency_refusals import CASES, observed_refusal
    source = project/'src/main.ts'
    original = read_file(source)
    before = inventory(snapshot(project))
    rows = []
    for label, prefix in (('direct', b'Date.now();\n'), ('reference', b'const startupClock = Date.now; startupClock();\n')):
        source.write_bytes(prefix+original)
        selected = inventory(snapshot(project))
        artifact = output/('snapshot-'+label)
        try:
            completed = run_bounded_result([sys.executable, '-B', str(ROOT/'tools/typescript_capsule.py'), 'build', str(project),
                '--tools', str(tools), '--contracts-tool', str(products['examples/capsule_contracts']),
                '--packager', str(products['examples/package']), '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
                '--runtime-engine', str(core), '--runtime-engine-receipt', str(envelope), '--output', str(artifact)],
                cwd=ROOT, env=build_environment(output), timeout_seconds=300, max_output_bytes=4*1024**2)
            observed = observed_refusal(artifact, next(row for row in CASES if row[0] == 'snapshot-clock'), completed)
            require(inventory(snapshot(project)) == selected and read_file(artifact/'source-inputs.json') == selected,
                    'typescript-clock-snapshot-project-changed')
            rows.append({**observed, 'observationForm': label, 'sourceDigest': digest(selected),
                         'failedBuild': file_identity(artifact/'BUILD-FAILED.json')})
        finally:
            source.write_bytes(original)
        require(inventory(snapshot(project)) == before, 'typescript-clock-snapshot-original-not-restored')
    return rows


def qualify(acquired, engine, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'typescript-clock-Linux-Python313')
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.standard-clock-qualification.v1', 'status': 'incomplete',
        'newCompilerProducts': 2, 'nativeProductsRebuilt': False, 'engineRebuilt': False,
        'normalReceiptRewritten': False, 'fullTicketQualification': False, 'publisherAuthenticated': False}
    stage = 'historical-native-and-engine'
    try:
        products, normal, inherited = historical(acquired)
        core, envelope, original_engine = engine_inputs(engine)
        record.update(inherited=inherited, originalEngine=original_engine)
        commands = Commands(ROOT, output, build_environment(output))
        stage = 'historical-companions'
        builds, old = companions(acquired, products, normal, commands)
        record['historicalCompanions'] = old
        stage = 'normal-outside-npm-capture'
        app, captured = selected_project(output/'project-greeting', output/'outside-owned-clock-modules')
        closed = closed_project(output/'project-word-count')
        write_json(output/'capture.json', captured)
        fresh_builds = {}
        for name, project in (('greeting', app), ('word-count', closed)):
            stage = 'fresh-clock-component-'+name
            before = inventory(snapshot(project))
            options = {'runtime_engine': core, 'runtime_engine_receipt': envelope} if name == 'greeting' else {}
            builds[name] = build(project, output/('build-'+name), products['examples/capsule_contracts'],
                products['examples/package'], 'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, **options)
            require(inventory(snapshot(project)) == before and read_file(builds[name]/'source-inputs.json') == before,
                    'typescript-clock-fresh-project-changed')
            bundle = read_json(builds[name]/'bundle-selected-inputs.json') if name == 'greeting' else None
            if bundle is not None:
                require(bundle['standardClockProfile'] == 'lsf-standard-clock-native-v1',
                        'typescript-clock-actual-selected-bundle')
            fresh_builds[name] = read_json(builds[name]/'BUILD-COMPLETE.json')
        record['freshBuilds'] = fresh_builds
        stage = 'actual-selected-engine-snapshot-refusals'
        record['snapshotRefusals'] = snapshot_controls(app, core, envelope, products, tools, output)
        stage = 'fresh-normal-demo-signing'
        commands.run('clock-demo-sign', products['examples/capsule_authoring'], 'demo-sign', output/'signed', *(builds[name] for name in TEMPLATES))
        stage = 'signed-original-and-clock-programme'
        node = run(products['latent'], products['latentd'], output/'signed', output/'node', language='typescript', standard_typescript_clocks=True)
        require(node['status'] == 'passed' and len(node['invocations']) == 47
                and len(node['typescriptClockAuthority']['denials']) == 3
                and len(node['typescriptStandardClocks']['cases']) == 13
                and len(node['typescriptStandardClocks']['recovery']) == 2
                and all(row['processReaped'] for row in node['invocations'])
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'typescript-clock-all-original-and-new-outcomes')
        require(historical(acquired)[2] == inherited and engine_inputs(engine)[2] == original_engine,
                'typescript-clock-final-inherited-inputs-changed')
        record.update(status='passed', outcomes=47, workflow=file_identity(output/'node/workflow.json'), commands=commands.records)
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acquire-engine', action='store_true')
    for name in ('acquired', 'engine', 'tools', 'output'): parser.add_argument('--'+name, type=Path)
    args = parser.parse_args()
    if args.acquire_engine:
        if args.engine is None or any(value is not None for value in (args.acquired, args.tools, args.output)):
            parser.error('--acquire-engine requires only --engine')
        acquire_engine(args.engine)
        print(json.dumps({'status': 'acquired'}))
    else:
        if any(value is None for value in (args.acquired, args.engine, args.tools, args.output)):
            parser.error('qualification requires --acquired --engine --tools --output')
        print(json.dumps({'status': qualify(args.acquired, args.engine, args.tools, args.output)['status']}))
