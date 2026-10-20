"""Require fresh pure and joined BCL Unsupported, original validation and retirement."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.dotnet_closed_filesystem_fixture import project
from tools.dotnet_guest import closed_filesystem, task_wait
from tools.dotnet_guest.runtime import CLOCK
from tools.dotnet_filesystem_runtime import LIMITS
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_sdk_scratch import HELPERS, build_component, execution_report, package_identity, prepared
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.sdk_scratch_probe import DOTNET_ARGUMENTS

MATERIALS = (*HELPERS, 'tools/qualify_dotnet_closed_filesystem.py', 'tools/dotnet_closed_filesystem_fixture.py',
    'tools/dotnet_filesystem_runtime.py',
    'tools/dotnet_guest/closed_filesystem.py', 'tools/dotnet_guest/task_wait.py',
    'sdk/dotnet-guest/tools/http-errors/ClosedFilesystem.cs', 'sdk/dotnet-guest/tools/http-errors/ClosedFilesystem.targets')


def inherited(directory):
    return prepared(directory, 'dotnet')


def observed(directory, *, joined):
    node = read_json(directory / 'node/workflow.json', 4*1024**2)
    count = 40 if joined else 39
    require(node['status'] == 'passed' and node['language'] == 'dotnet' and len(node['invocations']) == count
            and all(row['processReaped'] is True and row['response']['outcomeKnown'] is True for row in node['invocations'])
            and node['standardScratchRefusal']['allErrorsAreUnsupported'] is True
            and node['dotnetFilesystemArguments']['status'] == 'passed'
            and len(node['dotnetFilesystemArguments']['cases']) == 6
            and node['nodeShutdown']['reaped'] is True and node['nodeShutdown']['record']['clean'] is True,
            'closed-filesystem-original27-twelve-new-outcomes')
    scratch = node['standardScratchRefusal']
    require([row['mode'] for row in scratch['cases']] == ['open', 'create', 'temp']
            and all(row['observation']['category'] == 'platform-not-supported' and row['observation']['unsupported'] is True
                and row['invocation']['decoded'] == [{'ok': 'scratch|dotnet|platform-not-supported|fresh=1'}]
                for row in scratch['cases'])
            and [(row['mode'], row['category']) for row in node['dotnetFilesystemArguments']['cases']] == list(DOTNET_ARGUMENTS.items())
            and all(row['invocation']['decoded'] == [{'ok': 'scratch|dotnet|' + row['category'] + '|fresh=1'}]
                    and row['invocation']['exitCode'] == 0 for row in node['dotnetFilesystemArguments']['cases'])
            and len(node['providerIdle']) == 18 and len(node['samples']) == 36
            and all(not row['unavailable'] and all(int(row['counters'][key]) == 0 for key in ACTIVE_COUNTERS)
                    for row in node['providerIdle']), 'closed-filesystem-exact-caught-errors-and-retirement')
    port = read_json(directory / 'build/closed-filesystem-port.json')
    binding = port['nativeAotReferenceBinding']
    require(port['profile'] == closed_filesystem.PROFILE and port['requiredDeclarations'] == []
            and port['filesystemAuthority'] is False and port['modifiedOriginalMethods'] == 2
            and port['originalMethodBodies'] == closed_filesystem.METHODS
            and len(binding['responseFiles']) == 1 and binding['selectedCoreLibDigest'] == port['derived']['digest']
            and (port['taskWaitIntermediate'] is not None) is joined,
            'closed-filesystem-actual-final-corelib')
    activation = 'latent:runtime/activation@0.1.0'
    grants = node['standardScratchRefusal']['preservedRuntimeGrants']
    require(any(row['capability'] == activation for row in grants) is joined,
            'closed-filesystem-independent-runtime-authority')
    if joined:
        authority = node['dotnetFilesystemRuntimeAuthority']
        denied = authority['denied']; response = denied['response']; consumed = response['data']['consumption']
        require(authority['requiredDeclarations'] == [CLOCK, activation]
                and authority['providerLimits'] == LIMITS
                and authority['additionalWallEntropyOrHttpAuthority'] is False
                and denied in node['invocations'] and denied['processReaped'] is True
                and denied['exitCode'] == 4 and response['outcomeKnown'] is True
                and response['error']['code'] == 'permission-denied'
                and all(int(consumed[key]) == 0 for key in ('cpuFuel', 'peakMemoryBytes', 'outboundRequests',
                                                           'logBytes', 'effectCount')),
                'closed-filesystem-explicit-activation-denial')
        task = read_json(directory / 'build/task-wait-port.json')
        require(task['profile'] == task_wait.PROFILE and task['derived'] == port['taskWaitIntermediate']
                and task['derived']['digest'] == port['baseDigest']
                and task['nativeAotReferenceBinding']['responseFiles'] == binding['responseFiles']
                and task['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'] == port['derived']['digest'],
                'closed-filesystem-actual-task-wait-chain')
    marker = read_json(directory / 'build/BUILD-COMPLETE.json')
    package_identity(directory / 'build', marker)
    return {'workflow': file_identity(directory / 'node/workflow.json'), 'component': file_identity(
        directory / 'build/component.wasm', 64*1024**2), 'port': port, 'invocations': count,
        'argumentCases': node['dotnetFilesystemArguments']['cases'], 'scratch': node['standardScratchRefusal']}


def qualify(output, tools, normal, pure=None):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'closed-filesystem-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'closed-filesystem-output-outside-checkout')
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    materials = {name: file_identity(ROOT / name) for name in MATERIALS}
    record = {'schemaVersion': 'latent.dotnet.closed-filesystem.qualification.v1', 'status': 'incomplete',
        'materials': materials, 'fullTicketQualification': False, 'filesystemGrantsAdded': False,
        'scratchStorageImplemented': False, 'phaseCount': 2}
    stage = 'normal-public-products-and-pure-phase'
    try:
        binaries, companions, baseline = inherited(normal)
        record['inherited'] = baseline
        for binary in binaries.values(): binary.chmod(0o700)
        sources = []
        def execute(location, joined):
            nonlocal stage
            label = 'joined' if joined else 'pure'
            location.mkdir()
            stage = label + '-ordinary-source'
            app, fixture = project(location / 'application', joined=joined)
            source = inventory(snapshot(app)); sources.append((app, source))
            record[label + 'Fixture'] = fixture
            stage = label + '-offline-native-aot'
            artifact = build_component('dotnet', app, location / 'build', binaries, tools=tools)
            require(read_file(artifact / 'source-inputs.json') == source, 'closed-filesystem-actual-source-mismatch')
            package_identity(artifact, read_json(artifact / 'BUILD-COMPLETE.json'))
            stage = label + '-normal-sign'
            commands.run(label + '-closed-filesystem-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', location / 'signed',
                *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
            stage = label + '-signed-bcl-calls'
            node = run(binaries['latent'], binaries['latentd'], location / 'signed', location / 'node',
                       language='dotnet', standard_scratch_refusal=True, dotnet_scratch_task_runtime=joined)
            result = observed(location, joined=joined)
            write_json(location / 'compatibility-execution-report.json', execution_report('dotnet', artifact, node))
            return result
        if pure is None:
            pure = output / 'pure'
            record['pure'] = execute(pure, False)
            record['purePhase'] = 'fresh-current-component'
        else:
            prior = read_json(pure / 'qualification.json')
            require(prior['status'] == 'passed' and prior['schemaVersion'] == 'latent.standard-scratch-refusal.v1'
                    and prior['language'] == 'dotnet' and prior['inherited'] == baseline
                    and prior['materials'] == {name: file_identity(ROOT / name) for name in HELPERS}
                    and prior['workflow'] == file_identity(pure / 'node/workflow.json'),
                    'closed-filesystem-same-source-pure-phase')
            record['pure'] = observed(pure, joined=False)
            record['purePhase'] = 'same-source-existing-scratch-child'
        record['joined'] = execute(output / 'joined', True)
        stage = 'final-integrity'
        require(inherited(normal)[2] == baseline and observed(pure, joined=False) == record['pure']
                and all(inventory(snapshot(app)) == source for app, source in sources)
                and materials == {name: file_identity(ROOT / name) for name in MATERIALS},
                'closed-filesystem-observed-inputs-changed')
        record.update(status='passed', actualInvocations=79, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'native-qualification'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--pure-scratch', type=Path)
    args = parser.parse_args()
    print(qualify(args.output, args.tools, args.native_qualification, args.pure_scratch)['status'])
