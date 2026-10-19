#!/usr/bin/env python3
"""Capture/build/sign ordinary .NET secure RNG with explicit finite authority."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.dotnet_guest.build import build
from tools.dotnet_guest.compiler import runtime_inputs
from tools.dotnet_guest.entropy import PROFILE
from tools.dotnet_standard_entropy_fixture import CASES, prepare
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_dotnet_standard_console import inherited
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_json, snapshot, write_json

HELPERS = ('tools/dotnet_standard_entropy_fixture.py', 'tools/dotnet_standard_entropy_probe.py',
    'tools/qualify_dotnet_standard_entropy.py', 'tools/run_rust_capsule_workflow.py',
    'tools/dotnet_guest/entropy.py', 'tools/dotnet_guest/entropy_grants.py')


def qualify(output: Path, tools: Path, native_qualification: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'dotnet-entropy-Linux-python313-required')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'dotnet-entropy-output-must-be-outside-checkout')
    status = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'status', '--porcelain'],
        cwd=ROOT, capture_output=True, check=True, timeout=15)
    require(not status.stdout, 'dotnet-entropy-clean-source-required')
    revision = subprocess.check_output(['git', '-c', 'safe.directory=' + str(ROOT), 'rev-parse', 'HEAD'],
                                      cwd=ROOT, timeout=15).decode().strip()
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output))
    helpers = {name: file_identity(ROOT / name) for name in HELPERS}
    runtime = runtime_inputs(ROOT)
    record = {'schemaVersion': 'latent.dotnet.entropy.qualification.v1', 'status': 'in-progress',
        'source': {'head': revision, 'helpers': helpers, 'runtimeInputsDigest': digest(runtime)},
        'profile': PROFILE, 'publisherAuthenticated': False, 'releasePublished': False,
        'fullTicketQualification': False, 'applicationEntropyReplacement': False,
        'fipsCertification': False, 'statisticalQualityTest': False, 'transactionalReplayQualified': False}
    stage = 'observed-inputs'
    try:
        binaries, companions, baseline = inherited(native_qualification)
        record['inherited'] = baseline
        stage = 'outside-library-and-normal-capture'
        application, captured = prepare(output / 'project', output / 'outside', tools)
        record['captured'] = captured
        require(captured['originalLibraryAndFeedRemoved'], 'dotnet-entropy-originals-must-be-unavailable')
        before = inventory(snapshot(application))
        stage = 'offline-native-aot-component'
        greeting = build(application, output / 'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True)
        require((greeting / 'source-inputs.json').read_bytes() == before, 'dotnet-entropy-source-capture-changed')
        record['build'] = read_json(greeting / 'BUILD-COMPLETE.json')
        port = read_json(greeting / 'noncrypto-entropy-port.json')
        require(port['profile'] == PROFILE and port['secureRandom'] == 'declared-provider-u64'
                and port['nativeLinkBinding']['secureWrapOccurrences'] == 1,
                'dotnet-entropy-final-native-port-binding')
        record['nativePort'] = port
        stage = 'sign'
        builds = [greeting if template == 'greeting' else companions[template] for template in TEMPLATES]
        commands.run('demo-sign', binaries['capsule_authoring'], 'demo-sign', output / 'releases', *builds)
        stage = 'signed-node'
        observed = run(binaries['latent'], binaries['latentd'], output / 'releases', output / 'node',
                       language='dotnet', noncrypto_entropy=True, dotnet_standard_entropy=True)
        require(observed['status'] == 'passed'
                and len(observed['dotnetStandardEntropy']['cases']) == len(CASES)
                and len(observed['dotnetStandardEntropy']['recovery']) == 3
                and observed['dotnetStandardEntropyAuthority']['operationDenied']['response']['outcomeKnown']
                and observed['nodeShutdown']['reaped'] and observed['nodeShutdown']['record']['clean'],
                'dotnet-entropy-original-and-new-signed-gates-required')
        fields = ('schemaVersion', 'status', 'scope', 'limits', 'invocations', 'samples', 'providerIdle',
                  'dotnetStandardEntropyAuthority', 'dotnetStandardEntropy',
                  'noncryptoEntropyGrantDenied', 'noncryptoEntropyAuthority',
                  'nodeShutdown', 'peerShutdown', 'cliCalls')
        write_json(output / 'node/public-workflow.json', {name: observed[name] for name in fields})
        stage = 'final-integrity'
        require(inherited(native_qualification)[2] == baseline
                and helpers == {name: file_identity(ROOT / name) for name in HELPERS}
                and runtime_inputs(ROOT) == runtime and inventory(snapshot(application)) == before,
                'dotnet-entropy-observed-inputs-changed')
        record.update(status='passed', invocations=len(observed['invocations']),
            component=file_identity(greeting / 'component.wasm', 64 * 1024 * 1024),
            workflow=file_identity(output / 'node/workflow.json'), commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, reason=type(error).__name__, commands=commands.records)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'native-qualification'):
        parser.add_argument('--' + name, type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(qualify(arguments.output.resolve(), arguments.tools.resolve(),
                             arguments.native_qualification.resolve())))
