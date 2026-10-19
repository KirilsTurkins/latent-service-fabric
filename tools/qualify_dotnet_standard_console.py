#!/usr/bin/env python3
"""Capture/build/sign ordinary Console using the existing observed native tuple."""
from __future__ import annotations

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
from tools.dotnet_standard_console_fixture import CASES, prepare
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_rust_capsules import inputs
from tools.run_rust_capsule_workflow import run
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, TEMPLATES, digest, fresh, inventory, read_json, snapshot, write_json

NATIVE_NAMES = {'latent': 'latent', 'latentd': 'latentd', 'package': 'examples/package',
    'capsule_contracts': 'examples/capsule_contracts', 'capsule_authoring': 'examples/capsule_authoring'}
HELPERS = ('tools/dotnet_standard_console_fixture.py', 'tools/dotnet_standard_console_probe.py',
    'tools/qualify_dotnet_standard_console.py', 'tools/run_rust_capsule_workflow.py',
    'tools/dotnet_dependency_authoring.py', 'tools/dotnet_application_dependencies.py')


def inherited(native_qualification: Path):
    path = native_qualification / 'qualification.json'
    receipt = read_json(path)
    require(receipt['status'] == 'passed' and receipt['schemaVersion'] == 'latent.dotnet-capsule.qualification.v1',
            'dotnet-Console-observed-native-qualification-required')
    source = native_qualification / 'source-inputs.json'
    require(digest(source.read_bytes()) == receipt['sourceIdentityDigest']
            and read_json(source) == inputs('dotnet'), 'dotnet-Console-prepared-source-mismatch')
    binaries = {name: native_qualification / 'native-binaries' / key.replace('/', '-')
                for name, key in NATIVE_NAMES.items()}
    identities = {name: file_identity(binary, 512 * 1024 * 1024) for name, binary in binaries.items()}
    require(all(identities[name] == receipt['binaries'][key] for name, key in NATIVE_NAMES.items()),
            'dotnet-Console-native-tuple-mismatch')
    companions, original = {}, {}
    for template in TEMPLATES:
        if template == 'greeting': continue
        directory = native_qualification / 'builds' / template
        complete = read_json(directory / 'BUILD-COMPLETE.json')
        require(complete == receipt['builds'][template],
                'dotnet-Console-companion-build-mismatch')
        companions[template] = directory
        original[template] = {name: file_identity(directory / name, 64 * 1024 * 1024) for name in (
            'BUILD-COMPLETE.json', 'build-observation.json', 'source-inputs.json', 'component.wasm')}
        require(all(original[template][name]['sha256'] == complete[field] for name, field in (
            ('component.wasm', 'componentDigest'), ('source-inputs.json', 'sourceDigest'),
            ('build-observation.json', 'observationDigest'))), 'dotnet-Console-companion-bytes-mismatch')
    return binaries, companions, {'qualification': file_identity(path), 'sourceInputs': file_identity(source),
                                 'binaries': identities, 'companions': original}


def qualify(output: Path, tools: Path, native_qualification: Path):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'dotnet-Console-Linux-python313-required')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'dotnet-Console-output-must-be-outside-checkout')
    status = subprocess.run(['git', '-c', 'safe.directory=' + str(ROOT), 'status', '--porcelain'],
        cwd=ROOT, capture_output=True, check=True, timeout=15)
    require(not status.stdout, 'dotnet-Console-clean-source-required')
    revision = subprocess.check_output(['git', '-c', 'safe.directory=' + str(ROOT), 'rev-parse', 'HEAD'],
                                        cwd=ROOT, timeout=15).decode().strip()
    output = fresh(output)
    commands = Commands(ROOT, output, build_environment(output))
    source = {name: file_identity(ROOT / name) for name in HELPERS}
    runtime = runtime_inputs(ROOT)
    record = {'schemaVersion': 'latent.dotnet.Console.qualification.v1', 'status': 'in-progress',
        'source': {'head': revision, 'helpers': source, 'runtimeInputsDigest': digest(runtime)},
        'publisherAuthenticated': False, 'releasePublished': False, 'fullTicketQualification': False,
        'limits': {'libraryCommandsSeconds': 600, 'libraryOverallSeconds': 900,
                   'componentOverallSeconds': 900, 'nodeOverallSeconds': 900},
        'applicationConsoleReplacement': False}
    stage = 'observed-inputs'
    try:
        binaries, companions, baseline = inherited(native_qualification)
        record['inherited'] = baseline
        stage = 'outside-library-and-normal-capture'
        app, captured = prepare(output / 'project', output / 'outside', tools)
        record['captured'] = captured
        require(captured['originalLibraryAndFeedRemoved'], 'dotnet-Console-originals-must-be-unavailable')
        before = inventory(snapshot(app))
        stage = 'offline-native-aot-component'
        greeting = build(app, output / 'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools, offline=True)
        require((greeting / 'source-inputs.json').read_bytes() == before, 'dotnet-Console-source-capture-changed')
        record['build'] = read_json(greeting / 'BUILD-COMPLETE.json')
        stage = 'sign'
        builds = [greeting if template == 'greeting' else companions[template] for template in TEMPLATES]
        commands.run('demo-sign', binaries['capsule_authoring'], 'demo-sign', output / 'releases', *builds)
        stage = 'signed-node'
        observed = run(binaries['latent'], binaries['latentd'], output / 'releases', output / 'node',
                       language='dotnet', dotnet_standard_logging=True)
        require(observed['status'] == 'passed' and len(observed['dotnetStandardConsoleCases']) == len(CASES)
                and len(observed['dotnetStandardConsoleRecovery']) == 2
                and observed['nodeShutdown']['reaped'] and observed['nodeShutdown']['record']['clean'],
                'dotnet-Console-original-and-new-signed-gates-required')
        # Keep the public result bounded and exclude private node configuration.
        fields = ('schemaVersion', 'status', 'scope', 'limits', 'invocations', 'samples', 'providerIdle',
                  'dotnetStandardConsoleAuthority', 'dotnetStandardConsoleCases', 'dotnetStandardConsoleRecovery',
                  'nodeShutdown', 'peerShutdown', 'cliCalls')
        write_json(output / 'node/public-workflow.json', {name: observed[name] for name in fields})
        stage = 'final-integrity'
        require(inherited(native_qualification)[2] == baseline
                and source == {name: file_identity(ROOT / name) for name in HELPERS}
                and runtime_inputs(ROOT) == runtime and inventory(snapshot(app)) == before,
                'dotnet-Console-observed-inputs-changed')
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
    args = parser.parse_args()
    print(json.dumps(qualify(args.output.resolve(), args.tools.resolve(), args.native_qualification.resolve())))
