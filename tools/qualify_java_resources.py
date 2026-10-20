"""One fresh Java resource greeting on unchanged normally qualified companions."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import application_dependencies as dependencies
from tools.build_observation import build_environment
from tools.java_capsule_build import RECIPE, build
from tools.java_guest import resources
from tools.java_resource_fixture import APPLICATION_RESOURCE, DATA, EXPECTED, MATERIALS as FIXTURE_MATERIALS, capture
from tools.java_standard_http_library import compiler_cache
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_sdk_scratch import package_identity, prepared
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = (*FIXTURE_MATERIALS, *RECIPE, 'tools/java_resource_fixture.py', 'tools/java_resource_probe.py',
    'tools/qualify_java_resources.py', 'tools/java_standard_http_library.py',
    'tools/run_rust_capsule_workflow.py', 'tools/rust_capsule_node.py')


def observation(node):
    require(node['status'] == 'passed' and node['language'] == 'java' and len(node['invocations']) == 39
        and all(row['processReaped'] and row['response']['outcomeKnown'] is True for row in node['invocations'])
        and node['nodeShutdown']['reaped'] and node['nodeShutdown']['record']['clean'],
        'java-resource-original29-plus10-known-reaped')
    resource = node['javaResourceConformance']
    require(resource['status'] == 'passed' and resource['newInvocations'] == 10
        and [row['mode'] for row in resource['cases']] == list(EXPECTED)
        and all(row['invocation'] in node['invocations'] and row['invocation']['exitCode'] == 0
            and row['invocation']['decoded'] == [{'ok':EXPECTED[row['mode']]}] for row in resource['cases'])
        and resource['freshAfterTrap']['decoded'] == [{'ok':EXPECTED['binary']}]
        and resource['explicitTrap']['response']['error']['code'] == 'guest-trap'
        and resource['clockInvocation'] in node['invocations'], 'java-resource-exact-runtime-data')
    from tools.java_resource_probe import clock_values
    require(resource['clock'] == clock_values(resource['clockInvocation']['decoded'],
        resource['clock']['wallBefore'], resource['clock']['wallAfter']), 'java-resource-clock-recheck')
    require(len(node['providerIdle']) == 16 and len(node['samples']) == 36
        and all(not row['unavailable'] and all(int(row['counters'][name]) == 0 for name in ACTIVE_COUNTERS)
            for row in node['providerIdle']), 'java-resource-actual-owner-retirement')
    return {'originalProgrammeInvocations':29, 'resourceAndClockInvocations':10, 'totalInvocations':39,
        'exactDataCases':list(EXPECTED), 'clock':resource['clock'], 'physicalSamples':36,
        'zeroActiveOwnerSamples':16, 'allKnownReaped':True, 'cleanShutdown':True,
        'crossTenantQualification':False, 'fullTicketQualification':False}


def campaign(output, binaries, companions, ancestry, wasi_sdk, *, read_only_cache=None):
    require(sys.platform == 'linux' and sys.version_info >= (3,13) and os.geteuid() != 0,
            'java-resource-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'java-resource-output-outside-checkout')
    require(set(companions) == set(TEMPLATES)-{'greeting'}, 'java-resource-four-companions')
    output = fresh(output)
    materials = {name:file_identity(ROOT/name) for name in sorted(set(MATERIALS))}
    native = {name:file_identity(path, 512*1024**2) for name,path in binaries.items()}
    original_companions = {name:package_identity(path, read_json(path/'BUILD-COMPLETE.json')) for name,path in companions.items()}
    record = {'schemaVersion':'latent.java.resource-conformance.v1', 'status':'in-progress',
        'materials':materials, 'nativeProducts':native, 'inherited':ancestry,
        'nativeHostRebuilt':False, 'companionComponentsRecompiled':False,
        'fullTicketQualification':False, 'filesystemAuthority':False}
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1100, command_seconds=600)
    stage = 'ordinary-outside-jars'
    try:
        app, captured = capture(output, commands)
        record['capture'] = captured
        source = inventory(snapshot(app))
        stage = 'pinned-compiler-cache'
        cache_root = output/'compiler'; cache_root.mkdir()
        cache = compiler_cache(commands, wasi_sdk, cache_root, read_only_cache)
        stage = 'offline-actual-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 60, 'java-resource-remaining-compilation-deadline')
        artifact = build(app, output/'build', binaries['examples/capsule_contracts'], binaries['examples/package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk, timeout=remaining, read_only_cache=cache)
        require(read_file(artifact/'source-inputs.json') == source, 'java-resource-actual-compiled-source')
        profile = read_json(artifact/'bindings.json')['immutableResources']
        require(profile['profile'] == resources.PROFILE and profile['resourceInputs'] == json.loads(inventory({**DATA,**APPLICATION_RESOURCE}))
            and profile['streamOwnership'] == 'fresh-decoded-byte-array-per-open', 'java-resource-actual-resource-profile')
        marker = read_json(artifact/'BUILD-COMPLETE.json'); package_identity(artifact, marker)
        stage = 'normal-package-sign-admit'
        commands.run('resource-conformance-sign', binaries['examples/capsule_authoring'], 'demo-sign', output/'signed',
            *(artifact if name == 'greeting' else companions[name] for name in TEMPLATES))
        stage = 'signed-original29-and-ten-resource-calls'
        node = run(binaries['latent'], binaries['latentd'], output/'signed', output/'node',
            language='java', java_resource_conformance=True)
        observed = observation(node)
        stage = 'final-input-recheck'
        require(inventory(snapshot(app)) == source and dependencies.verify_inputs(app,'java').identity == captured['capturedInputIdentity']
            and materials == {name:file_identity(ROOT/name) for name in materials}
            and native == {name:file_identity(path,512*1024**2) for name,path in binaries.items()}
            and original_companions == {name:package_identity(path,read_json(path/'BUILD-COMPLETE.json')) for name,path in companions.items()},
            'java-resource-final-input-drift')
        require(time.monotonic() <= commands.deadline, 'java-resource-original-total-deadline')
        record.update(status='passed', observation=observed, source=file_identity(artifact/'source-inputs.json'),
            recipe=file_identity(artifact/'recipe-inputs.json'), component=file_identity(artifact/'component.wasm',64*1024**2),
            marker=marker, resourceProfile=profile, companions=original_companions,
            workflow=file_identity(output/'node/workflow.json'), commands=commands.records)
        write_json(output/'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output','native-qualification','wasi-sdk'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--read-only-cache',type=Path)
    args = parser.parse_args()
    binaries, companions, ancestry = prepared(args.native_qualification.resolve(strict=True),'java')
    print(campaign(args.output, binaries, companions, ancestry, args.wasi_sdk.resolve(strict=True),
        read_only_cache=args.read_only_cache)['status'])
