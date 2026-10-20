"""One language's ordinary scratch refusal packet on its existing signed pipeline."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.native_runtime.verify import relative
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_scratch_fixture import CASES, LANGUAGES, project

PRODUCTS = ('latent', 'latentd', 'examples/package', 'examples/capsule_contracts', 'examples/capsule_authoring')
HELPERS = ('tools/qualify_sdk_scratch.py', 'tools/sdk_scratch_fixture.py',
    'tools/sdk_scratch_probe.py', 'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py')
REPOSITORY = 'https://github.com/KirilsTurkins/latent-service-fabric'


def current_inputs(language):
    require(language in LANGUAGES, 'scratch-language')
    if language == 'java':
        from tools.qualify_java_capsules import inputs
        return inputs()
    from tools.qualify_rust_capsules import inputs
    return inputs(language)


def package_identity(directory, marker):
    """Bind the exact public signer inputs through the original build observation."""
    for name, field in (('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
            ('build-observation.json', 'observationDigest')):
        require(file_identity(directory/name, 64*1024*1024)['sha256'] == marker[field],
                'scratch-observed-companion-bytes-changed')
    declared = read_json(directory/'package-source.json')
    layers = declared.get('layers')
    require(type(layers) is list and 1 <= len(layers) <= 128, 'scratch-companion-layer-bound')
    names = ['package-source.json', *(relative(row['source']) for row in layers)]
    require(len(names) == len(set(names)), 'scratch-companion-duplicate-layer')
    observed = {name: read_file(directory/name, 64*1024*1024) for name in names}
    require(sum(map(len, observed.values())) <= 128*1024*1024, 'scratch-companion-total-bound')
    package = inventory(observed)
    require(read_file(directory/'package-inputs.json') == package, 'scratch-companion-package-inputs-changed')
    materials = read_json(directory/'build-observation.json')['materials']
    bound = [row for row in materials if row['name'] == 'package-inputs']
    require(bound == [{'name': 'package-inputs', 'digest': digest(package), 'size': len(package)}],
            'scratch-companion-package-not-observed')
    return {name: {'sha256': digest(raw), 'bytes': len(raw)} for name, raw in observed.items()}


def prepared(directory, language, native_directory=None):
    receipt_path = directory/'qualification.json'
    receipt = read_json(receipt_path)
    require(receipt.get('schemaVersion') == 'latent.'+language+'-capsule.qualification.v1'
            and receipt.get('status') == 'passed' and 'applicationDependencies' not in receipt,
            'scratch-original-normal-qualification-required')
    source = directory/'source-inputs.json'
    require(digest(read_file(source, 16*1024*1024)) == receipt['sourceIdentityDigest']
            and read_json(source, 16*1024*1024) == current_inputs(language),
            'scratch-original-source-mismatch')
    binaries = {name: (directory/'native-binaries'/name.replace('/', '-') if native_directory is None
        else native_directory/name) for name in PRODUCTS}
    identities = {name: file_identity(path, 512*1024*1024) for name, path in binaries.items()}
    require(all(identities[name] == receipt['binaries'][name] for name in PRODUCTS),
            'scratch-original-native-tuple-mismatch')
    companions, signed_inputs = {}, {}
    for template in TEMPLATES:
        if template == 'greeting': continue
        location = directory/'builds'/template
        marker = read_json(location/'BUILD-COMPLETE.json')
        require(marker == receipt['builds'][template], 'scratch-original-companion-marker-mismatch')
        signed_inputs[template] = package_identity(location, marker)
        companions[template] = location
    node_path = directory/'node/workflow.json'
    require(file_identity(node_path)['sha256'] == receipt['node']['receiptDigest'],
            'scratch-original-node-receipt-changed')
    node = read_json(node_path, 1024*1024)
    require(node['status'] == 'passed' and node['language'] == language
            and type(node['invocations']) is list and 27 <= len(node['invocations']) <= 48
            and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
            'scratch-original-normal-node-required')
    return binaries, companions, {'qualification': file_identity(receipt_path),
        'sourceInputs': file_identity(source, 16*1024*1024), 'binaries': identities,
        'companions': signed_inputs, 'node': file_identity(node_path),
        'originalInvocations': len(node['invocations'])}


def bundle(directory, language, output, native_directory=None):
    """Export the normal public products only; no compiler cache, keys or private peers."""
    output = output.absolute()
    binaries, companions, before = prepared(directory, language, native_directory)
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'scratch-bundle-outside-checkout')
    output = fresh(output)
    selected = {'qualification.json': directory/'qualification.json',
        'source-inputs.json': directory/'source-inputs.json', 'node/workflow.json': directory/'node/workflow.json'}
    selected.update({'native-binaries/'+name.replace('/', '-'): path for name, path in binaries.items()})
    for template, location in companions.items():
        names = {*before['companions'][template], 'package-inputs.json', 'BUILD-COMPLETE.json',
            'build-observation.json', 'source-inputs.json', 'deployment.json'}
        selected.update({'builds/'+template+'/'+name: location/name for name in names})
    require(len(selected) <= 1024, 'scratch-bundle-file-bound')
    total = 0
    for name, source in sorted(selected.items()):
        maximum = 512*1024*1024 if name.startswith('native-binaries/') else 64*1024*1024
        raw = read_file(source, maximum)
        total += len(raw)
        require(total <= 1024*1024*1024, 'scratch-bundle-total-byte-bound')
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if name.startswith('native-binaries/') and os.name == 'posix': target.chmod(0o700)
    require(prepared(directory, language, native_directory)[2] == before
            and prepared(output, language)[2] == before, 'scratch-bundle-copy-or-source-changed')
    result = {'status': 'passed', 'language': language, 'files': len(selected), 'bytes': total,
        'originalNormalProducts': before, 'privateCredentialsExported': False, 'compilerCachesExported': False}
    write_json(output/'scratch-bundle.json', result)
    return result


def build_component(language, app, destination, binaries, *, tools=None, wasi_sdk=None):
    args = (app, destination, binaries['examples/capsule_contracts'], binaries['examples/package'], REPOSITORY)
    if language == 'rust':
        from tools.rust_capsule_build import build
        return build(*args, offline=True)
    if language == 'c':
        from tools.c_capsule_build import build
        selected = {name: shutil.which(name) for name in ('zig', 'wit-bindgen', 'wasm-tools')}
        require(all(selected.values()), 'scratch-pinned-c-compiler-tools-required')
        return build(*args, installed={name: Path(value).resolve(strict=True) for name, value in selected.items()})
    if language == 'go':
        from tools.go_capsule_build import build
        return build(*args)
    if language == 'java':
        from tools.java_capsule_build import build
        require(wasi_sdk is not None, 'scratch-java-wasi-sdk-required')
        return build(*args, wasi_sdk)
    from tools.dotnet_guest.build import build
    require(tools is not None, 'scratch-dotnet-compiler-tools-required')
    return build(*args, tools=tools, offline=True)


def locked_dependencies(language, app, commands):
    """Seed the whole owned lock, including native and target-specific resolver rows."""
    if language != 'rust':
        return None
    before = inventory(snapshot(app))
    commands.run('scratch-locked-dependency-download', 'cargo', 'fetch', '--locked',
                 '--manifest-path', app/'Cargo.toml')
    require(inventory(snapshot(app)) == before, 'scratch-locked-download-mutated-source')
    return {'lock': file_identity(app/'Cargo.lock'), 'compilerExecution': False,
            'subsequentBuildOffline': True, 'sourceUnchanged': True}


def execution_report(language, artifact, node):
    from tools import guest_compatibility as compatibility
    from tools.sdk_scratch_probe import refusal
    original = compatibility.read(read_file(artifact/'compatibility-report.json'))
    releases = [row for row in node['releaseSet']['releases'] if row['name'] == 'my-greeting']
    require(original['language'] == language and len(releases) == 1
            and releases[0]['componentDigest'] == original['componentDigest'], 'scratch-report-signed-component-mismatch')
    observed = node.get('standardScratchRefusal', {})
    require(observed.get('status') == 'passed' and observed.get('language') == language
            and [row['mode'] for row in observed['cases']] == list(CASES[language]),
            'scratch-report-actual-cases-required')
    operations = {'rust': ('std::fs::File::open', 'std::fs::OpenOptions::open', 'std::fs::create_dir'),
        'c': ('fopen(read)', 'fopen(create)', 'tmpfile'), 'go': ('os.Open', 'os.OpenFile', 'os.CreateTemp'),
        'java': ('java.io.FileInputStream', 'java.io.FileOutputStream', 'java.io.File.createTempFile'),
        'dotnet': ('System.IO.File.OpenRead', 'System.IO.File.Open', 'System.IO.Path.GetTempFileName')}
    findings = list(original['findings'])
    for row, operation in zip(observed['cases'], operations[language]):
        call = row['invocation']
        require(call['processReaped'] and call['exitCode'] == 0 and call['response']['outcomeKnown'] is True,
                'scratch-report-caught-component-result-required')
        result = refusal(language, call['decoded'])
        require(row['observation'] == result, 'scratch-report-category-recheck')
        findings.append(compatibility.finding('unsupported-reached' if result['unsupported'] else 'unresolved-behavior',
            'invocation', 'actual-component', operation=operation, owner_issue=681,
            source_digest=original['sourceDigest'], symbol='greet'))
    # The deliberate fixture trap is not evidence for a standard API's cause.
    findings.append(compatibility.finding('unresolved-behavior', 'invocation', 'actual-component',
        operation='explicit-scratch-fixture-trap', owner_issue=681, source_digest=original['sourceDigest'], symbol='greet'))
    return compatibility.report(language, original['sourceDigest'], original['componentDigest'],
        original['runtimeProfile'], original['inputs'], findings, omitted=original['omittedFindings'])


def qualify(language, output, native_qualification, *, native_directory=None, tools=None, wasi_sdk=None):
    require(language in LANGUAGES and sys.platform == 'linux' and sys.version_info >= (3, 13)
            and os.geteuid() != 0, 'scratch-owning-unprivileged-linux-python313-required')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'scratch-output-outside-checkout-required')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT/name) for name in HELPERS}
    record = {'schemaVersion': 'latent.standard-scratch-refusal.v1', 'status': 'in-progress',
        'language': language, 'materials': materials, 'filesystemGrantsAdded': False,
        'scratchStorageImplemented': False, 'sixLanguageQualification': False,
        'fullTicketQualification': False, 'publisherAuthenticated': False, 'releasePublished': False}
    stage = 'original-products'
    try:
        binaries, companions, inherited = prepared(native_qualification, language, native_directory)
        record['inherited'] = inherited
        if os.name == 'posix':
            # Artifact restoration drops executable modes. Only the five files
            # already checked against the original normal receipt are enabled.
            for binary in binaries.values(): binary.chmod(0o700)
        stage = 'ordinary-standard-source'
        app, fixture = project(language, output/'application')
        record['fixture'] = fixture
        before = inventory(snapshot(app))
        stage = 'locked-fixture-dependency-download'
        record['dependencyPreparation'] = locked_dependencies(language, app, commands)
        stage = 'normal-component-build'
        artifact = build_component(language, app, output/'build', binaries, tools=tools, wasi_sdk=wasi_sdk)
        require(read_file(artifact/'source-inputs.json') == before, 'scratch-actual-compiled-source-mismatch')
        marker = read_json(artifact/'BUILD-COMPLETE.json')
        record['build'] = marker
        package_identity(artifact, marker)
        stage = 'normal-demo-sign'
        commands.run('scratch-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        stage = 'actual-signed-standard-api-results'
        node = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node',
            language=language, standard_scratch_refusal=True)
        require(node['status'] == 'passed' and node['standardScratchRefusal']['status'] == 'passed'
                and len(node['invocations']) == inherited['originalInvocations']+6
                and len(node['standardScratchRefusal']['cases']) == 3
                and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
                'scratch-original-and-six-new-signed-outcomes-required')
        report = execution_report(language, artifact, node)
        write_json(output/'compatibility-execution-report.json', report)
        stage = 'final-integrity'
        require(prepared(native_qualification, language, native_directory)[2] == inherited
                and materials == {name: file_identity(ROOT/name) for name in HELPERS}
                and inventory(snapshot(app)) == before, 'scratch-observed-inputs-changed')
        record.update(status='passed', workflow=file_identity(output/'node/workflow.json'),
            invocations=len(node['invocations']), scratch=node['standardScratchRefusal'],
            compatibilityReportIdentity=report['identity'],
            component=file_identity(artifact/'component.wasm', 64*1024*1024), commands=commands.records)
        write_json(output/'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=LANGUAGES, required=True)
    parser.add_argument('--export-bundle', action='store_true')
    for name in ('output', 'native-qualification', 'native-directory', 'tools', 'wasi-sdk'):
        parser.add_argument('--'+name, type=Path, required=name in ('output', 'native-qualification'))
    args = parser.parse_args()
    if args.export_bundle:
        result = bundle(args.native_qualification, args.language, args.output, args.native_directory)
    else:
        result = qualify(args.language, args.output, args.native_qualification,
            native_directory=args.native_directory, tools=args.tools, wasi_sdk=args.wasi_sdk)
    print(json.dumps({'status': result['status']}))
