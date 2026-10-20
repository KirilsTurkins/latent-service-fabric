"""Fresh Java filesystems on exact retained helpers and a separately bound host."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import java_replay_materials as historical
from tools import dotnet_byte_host_acquisition as acquisition
from tools.java_capsule_build import build, RECIPE
from tools.java_capsule_project import create
from tools.java_guest import filesystem
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import execution_report, package_identity
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_scratch_fixture import project
from tools.sdk_scratch_probe import JAVA_ARGUMENTS

PRODUCTION = '759b86c139473cbe06a0b51298ac13ea234cbffe'
MATERIALS = (*RECIPE, 'tools/sdk_scratch_fixture.py', 'tools/sdk_scratch_probe.py',
    'tools/qualify_sdk_scratch.py', 'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py')


def production_inputs():
    result = subprocess.run(['git', 'diff', '--exit-code', PRODUCTION, '--',
        *sorted(set(MATERIALS) | {'sdk/java-guest', 'wit', 'schemas'})], cwd=ROOT,
        capture_output=True, timeout=30, check=False)
    require(result.returncode == 0 and not result.stdout, 'java-filesystem-current-production-input-drift')
    require(not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, timeout=30),
            'java-filesystem-clean-source-required')
    return {'productionSource': PRODUCTION,
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
        'currentProductionInputsEqual': True,
        'materials': {name: file_identity(ROOT / name) for name in sorted(set(MATERIALS))}}


def selected_products(prepared):
    original = historical.verify_prepared(prepared)
    host = prepared / 'selected-host'
    selected = acquisition.validate(host)
    retrieved = read_json(host / 'host-retrieval.json')
    origin = acquisition.origin()
    require(retrieved['artifact'] == origin['id'] and retrieved['archiveDigest'] == origin['digest']
        and retrieved['run'] == acquisition.RUN and retrieved['job'] == acquisition.JOB
        and retrieved['compiledSource'] == acquisition.SOURCE and retrieved['binary'] == selected['binary']
        and retrieved['sourceIdentity'] == acquisition.historical.git_source_identity(acquisition.SOURCE),
        'java-filesystem-authenticated-selected-host')
    old = historical.native_products(prepared)
    binaries = {'latent': old['latent'], 'latentd': host / 'latentd',
        **{'examples/' + name: old[name] for name in ('package', 'capsule_contracts', 'capsule_authoring')}}
    for binary in binaries.values(): binary.chmod(0o700)
    return binaries, {'historicalProducts': original, 'selectedHost': retrieved,
        'products': {name: file_identity(path, 512 * 1024**2) for name, path in binaries.items()},
        'originalDotnetReceiptRewritten': False, 'normalJavaReceiptFabricated': False,
        'currentNativeHostCompiled': False, 'allFiveJavaComponentsFresh': True}


def node_observation(node):
    from tools.rust_capsule_node import ACTIVE_COUNTERS
    require(node['status'] == 'passed' and len(node['invocations']) == 39
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in node['invocations'])
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'java-filesystem-original27-and12-known-reaped-required')
    scratch = node['standardScratchRefusal']
    require(scratch['status'] == 'passed' and scratch['language'] == 'java'
        and [row['mode'] for row in scratch['cases']] == ['open', 'create', 'temp']
        and all(row['observation']['unsupported'] is True
            and row['invocation']['decoded'] == [{'ok': 'scratch|java|unsupported-operation|fresh=1'}]
            for row in scratch['cases']), 'java-filesystem-three-caught-unsupported-required')
    arguments = node['javaFilesystemArguments']
    require(arguments['status'] == 'passed' and [(row['mode'], row['category']) for row in arguments['cases']]
        == list(JAVA_ARGUMENTS.items()) and all(row['invocation']['decoded'] ==
            [{'ok': 'scratch|java|' + row['category'] + '|fresh=1'}] for row in arguments['cases']),
        'java-filesystem-six-preserved-argument-errors-required')
    require(len(node['providerIdle']) == 18 and len(node['samples']) == 36,
        'java-filesystem-original-and-all-new-retirement-samples-required')
    require(all(not row['unavailable'] and all(name in row['counters'] and int(row['counters'][name]) == 0
        for name in ACTIVE_COUNTERS) for row in node['providerIdle']), 'java-filesystem-provider-owners-not-retired')
    return {'invocations': 39, 'originalProgrammeInvocations': 27,
        'filesystemAndArgumentCalls': 12, 'caughtUnsupported': 3, 'preservedArgumentErrors': 6,
        'providerIdleSamples': 18, 'physicalSamples': 36, 'cleanReapedShutdown': True}


def qualify(output, prepared, wasi_sdk):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'java-filesystem-owning-unprivileged-linux-python313-required')
    require(ROOT not in output.parents and output not in ROOT.parents and output != ROOT,
            'java-filesystem-owned-output-outside-checkout')
    output = fresh(output)
    source = production_inputs()
    binaries, retained = selected_products(prepared)
    record = {'schemaVersion': 'latent.java.closed-filesystem.replay.v1', 'status': 'in-progress',
        'source': source, 'inherited': retained, 'filesystemGrantsAdded': False,
        'writableScratchImplemented': False, 'fullTicketQualification': False}
    stage = 'fresh-current-components'
    deadline = time.monotonic() + 1100
    try:
        builds, inputs, markers = {}, {}, {}
        for template in TEMPLATES:
            if template == 'greeting':
                app, fixture = project('java', output / 'projects' / template)
                record['fixture'] = fixture
            else:
                app = create(output / 'projects' / template, template)
            inputs[template] = inventory(snapshot(app))
            require(deadline - time.monotonic() > 60, 'java-filesystem-remaining-build-deadline')
            artifact = build(app, output / 'builds' / template, binaries['examples/capsule_contracts'],
                binaries['examples/package'], 'https://github.com/KirilsTurkins/latent-service-fabric',
                wasi_sdk, timeout=min(600, deadline - time.monotonic()))
            require(read_file(artifact / 'source-inputs.json') == inputs[template], 'java-filesystem-compiled-source-drift')
            require(read_json(artifact / 'bindings.json')['closedFilesystem'] == filesystem.stage(ROOT / 'sdk/java-guest'),
                    'java-filesystem-actual-compiler-profile-required')
            markers[template] = read_json(artifact / 'BUILD-COMPLETE.json')
            package_identity(artifact, markers[template])
            builds[template] = artifact
        stage = 'fresh-normal-signing'
        from tools.rust_capsule_build import Commands
        from tools.build_observation import build_environment
        require(deadline - time.monotonic() >= 60, 'java-filesystem-remaining-signing-deadline')
        commands = Commands(ROOT, output, build_environment(output), deadline_seconds=int(deadline - time.monotonic()),
                            command_seconds=60)
        commands.run('filesystem-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign',
            output / 'signed', *(builds[name] for name in TEMPLATES))
        stage = 'actual39-signed-admitted-outcomes'
        node = run(binaries['latent'], binaries['latentd'], output / 'signed', output / 'node',
                   language='java', standard_scratch_refusal=True)
        record['observation'] = node_observation(node)
        report = execution_report('java', builds['greeting'], node)
        write_json(output / 'compatibility-execution-report.json', report)
        stage = 'final-input-integrity'
        require(production_inputs() == source and selected_products(prepared)[1] == retained,
                'java-filesystem-observed-source-or-products-changed')
        for name, artifact in builds.items():
            require(inventory(snapshot(output / 'projects' / name)) == inputs[name]
                and read_json(artifact / 'BUILD-COMPLETE.json') == markers[name], 'java-filesystem-source-or-marker-changed')
            package_identity(artifact, markers[name])
        require(time.monotonic() <= deadline, 'java-filesystem-original-total-deadline')
        record.update(status='passed', builds=markers, node=file_identity(output / 'node/workflow.json'),
            component=file_identity(builds['greeting'] / 'component.wasm', 64 * 1024**2),
            compatibilityReportIdentity=report['identity'])
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--wasi-sdk', type=Path)
    args = parser.parse_args()
    if args.prepare:
        require(args.prepared is None and args.wasi_sdk is None, 'java-filesystem-prepare-only')
        production_inputs()
        historical.prepare(args.output.resolve())
        acquisition.retrieve(args.output.resolve() / 'selected-host')
    else:
        require(args.prepared is not None and args.wasi_sdk is not None, 'java-filesystem-replay-inputs-required')
        print(qualify(args.output.resolve(), args.prepared.resolve(strict=True), args.wasi_sdk.resolve(strict=True))['status'])
