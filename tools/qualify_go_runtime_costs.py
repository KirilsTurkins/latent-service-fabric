#!/usr/bin/env python3
"""Actual ordinary-Go stack/GC/heap observations on authenticated normal products."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import go_runtime_cost_fixture as fixture, go_runtime_cost_probe as oracle
from tools import qualify_go_node_stop as original
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import build_component, package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, assert_value, call, deploy, selected_revision
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

HELPERS = (*original.HELPERS, 'tools/qualify_go_runtime_costs.py',
           'tools/go_runtime_cost_fixture.py', 'tools/go_runtime_cost_probe.py')
CASES = {'go-component-async-v1': [('baseline', 'baseline')],
         'go-component-activation-v5': [('baseline', 'baseline'), ('live-stack-GC', 'stack-gc'),
             ('fresh-after-stack-GC', 'baseline'), ('live-heap-GC', 'heap-gc'),
             ('fresh-after-heap-GC', 'baseline')]}


def stack_placement_observation(stderr):
    require(type(stderr) is bytes and len(stderr) <= 262144, 'Go-cost-stack-placement-output-bound')
    text = stderr.decode('utf-8')
    rows = re.findall(r'^main\.costRecursive STEXT size=[0-9]+ args=0x[0-9a-f]+ locals=0x([0-9a-f]+)\b', text, re.M)
    require(len(rows) == 1 and re.search(r'\bmain\.frame(?:\+[0-9]+)?\(SP\)', text) is not None
            and 'moved to heap: frame' not in text and 'frame escapes to heap' not in text,
            'Go-cost-actual-recursive-stack-frame-required')
    size = int(rows[0], 16)
    require(8192 <= size < 16384, 'Go-cost-recursive-stack-frame-size')
    return {'target': 'wasip1/wasm', 'function': 'main.costRecursive', 'compilerFrameBytes': size,
            'ordinaryArrayBytes': 8192, 'referenceExecuted': False,
            'finalComponentPlacementInferredFromReferenceAlone': False}


def stack_placement_reference(output):
    output.mkdir()
    work = output / 'project'
    work.mkdir()
    source = fixture.stack_reference_source()
    (work / 'main.go').write_bytes(source)
    (work / 'go.mod').write_bytes(b'module lsf-cost-stack-proof\n\ngo 1.27.2\n')
    compiler = shutil.which('go')
    require(compiler is not None, 'Go-cost-maintained-Go-compiler-required')
    environment = build_environment(output)
    environment.update(GOOS='wasip1', GOARCH='wasm', GOTOOLCHAIN='local', GOWORK='off',
        GOFLAGS='-mod=readonly', GOPROXY='off', GOSUMDB='off', CGO_ENABLED='0',
        GOCACHE=str(output / 'cache'), GOMODCACHE=str(output / 'modules'))
    commands = Commands(work, output, environment, deadline_seconds=240, command_seconds=180)
    require(commands.run('stack-reference-compiler-version', compiler, 'version').strip()
            == b'go version go1.27.2 linux/amd64', 'Go-cost-pinned-compiler-version')
    commands.run('stack-reference-compile-not-execute', compiler, 'build',
        '-gcflags=lsf-cost-stack-proof=-m=2 -S', '-o', output / 'not-executed.wasm', '.')
    stderr = read_file(output / 'logs/01-stack-reference-compile-not-execute.stderr.txt', 262144)
    result = stack_placement_observation(stderr)
    result.update(source=file_identity(work / 'main.go'),
        compiler=file_identity(Path(compiler), 64 * 1024 * 1024),
        compilerDiagnostics=file_identity(output / 'logs/01-stack-reference-compile-not-execute.stderr.txt', 262144),
        commands=commands.records)
    require(read_file(work / 'main.go') == source, 'Go-cost-reference-source-changed')
    write_json(output / 'placement.json', result)
    return result


def idle(client):
    deadline = min(client.deadline, time.monotonic() + 3)
    for attempt in range(64):
        value = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']
        topology = value['topology']
        require(topology['available'] is True and topology['complete'] is True,
                'Go-cost-complete-physical-topology')
        rows = {row['name']: row for row in topology['entries']}
        require(len(rows) == len(topology['entries']) and all(name in rows for name in original.oracle.LIVE_ROWS),
                'Go-cost-actual-physical-owner-rows')
        if (all(oracle.integer(row['activeCount']) == 0 for row in rows.values()
                if row['ownership'] == 'activation-scoped')
            and all(oracle.integer(rows[name]['activeCount']) == 0 for name in original.oracle.LIVE_ROWS)
            and oracle.integer(value['queueDepth']) == 0
            and all(oracle.integer(amount) == 0 for amount in value['quotas']['usage'].values())
            and value['cellCapacity'] and all(cell['observationAvailable'] is True
                and oracle.integer(cell['active']) == 0 and oracle.integer(cell['quarantined']) == 0
                for cell in value['cellCapacity'])):
            return {'attempts': attempt + 1, 'inventory': value}
        require(time.monotonic() < deadline, 'Go-cost-physical-retirement-deadline')
        time.sleep(0.01)
    raise RuntimeError('Go-cost-physical-retirement-attempt-bound')


def programme(native, signed, output, profile):
    require(profile in fixture.PROFILES, 'Go-cost-explicit-profile')
    with tempfile.TemporaryDirectory(prefix='lsf-go-cost-') as private, owned_cancellation() as cancellation:
        work = Path(private)
        for name in ('client', 'node'):
            (work / name).mkdir(mode=0o700)
        client = RecordingClient(native['latent'], work / 'client', cancellation,
            time.monotonic() + 120, evidence=output / 'controls', invocation_timeout_millis=120000)
        path = original.configuration(work / 'node', signed)
        node = None
        record = {'profile': profile, 'status': 'in-progress', 'cases': [],
                  'ownerLimits': dict(original.oracle.OWNER_LIMITS)}
        try:
            node = connect(client, native['latentd'], work / 'node', path, 'examples', 1)
            record['startup'] = node.startup_record
            source = signed / 'my-greeting'
            publication = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'publish-cost',
                '--expected-generation', '0')['data']['operation']['publication']['id']
            target = deploy(client, source / 'deployment.json', publication)
            targets = {'greeting': target}
            original.runtime_grants(client, node, signed, targets, {'greeting': publication}, record, language='go')
            target = original.install_activation(client, node, signed, targets['greeting'], publication)
            require(target['budget']['cpuFuel'] == 1000000000 and target['budget']['memoryBytes'] == 67108864
                    and target['budget']['wallTimeLimitMillis'] == 120000, 'Go-cost-original-request-budgets')
            revision = selected_revision(client, target)
            record['budget'] = target['budget']
            for index, (name, mode) in enumerate(CASES[profile]):
                activation = 'go-cost-' + name
                row = call(client, target, 'greeting', 'greet', ['cost:' + mode], activation)
                # Preserve ordinary bounded diagnostics if a real guest fails.
                if row['exitCode'] != 0 or row['response']['outcomeKnown'] is not True:
                    assert_value(client, row, [{'ok': 'Go-cost-required-real-success'}])
                selected = oracle.invocation(row, mode, target['budget'], revision)
                budget_path = client.directory / (activation + '-budget.json')
                require(read_json(budget_path) == target['budget'], 'Go-cost-written-budget-mismatch')
                selected.update(name=name, activation=activation,
                    raw=file_identity(client.evidence / (activation + '.json')),
                    requestedBudget=file_identity(budget_path))
                physical = idle(client)
                physical_path = output / ('idle-' + str(index) + '.json')
                write_json(physical_path, physical)
                selected['physicalRetirement'] = file_identity(physical_path)
                record['cases'].append(selected)
            stop(client, node)
            record['shutdown'] = stopped_record(node)
            original.oracle.shutdown(record['shutdown'])
            node = None
            record.update(status='passed', invocations=len(CASES[profile]),
                fullCostMatrixQualified=False, physicalMemoryAccountingQualified=False,
                taskExhaustionQualified=False, unusedLogicalKindsQualified=False)
            write_json(output / 'result.json', record)
            return record
        except BaseException:
            record['status'] = 'failed'
            write_json(output / 'FAILED.json', record)
            raise
        finally:
            if node is not None:
                node.close()


def qualify(output, normal, producer):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'Go-cost-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'Go-cost-output-outside-checkout')
    output = fresh(output)
    record = {'schemaVersion': 'latent.go.runtime-costs.v1', 'status': 'in-progress',
        'fullCostMatrixQualified': False, 'physicalMemoryAccountingQualified': False,
        'newNativeBuild': False, 'profiles': [],
        'helpers': {name: file_identity(ROOT / name) for name in HELPERS}}
    stage = 'original-normal-products'
    try:
        record['producer'] = original.validate_producer(read_json(producer))
        binaries, _companions, inherited, compatibility = original.prepared(normal)
        require(inherited['originalInvocations'] == 27, 'Go-cost-original-normal27')
        record.update(inherited=inherited, sourceCompatibility=compatibility)
        stage = 'ordinary-recursive-stack-placement-reference'
        record['stackPlacementReference'] = stack_placement_reference(output / 'stack-placement')
        for path in binaries.values():
            path.chmod(0o700)
        native = {name: binaries[name] for name in ('latent', 'latentd')}
        fixture_sources = []
        for index, profile in enumerate(fixture.PROFILES):
            selected = output / ('profile-' + str(index))
            selected.mkdir()
            stage = profile + ':ordinary-source'
            app, source = fixture.project(selected / 'application', profile)
            fixture_sources.append(read_file(app / 'src/main.go'))
            before = inventory(snapshot(app))
            stage = profile + ':component-build'
            artifact = build_component('go', app, selected / 'build', binaries)
            require(read_file(artifact / 'source-inputs.json') == before, 'Go-cost-built-source-mismatch')
            marker = read_json(artifact / 'BUILD-COMPLETE.json')
            package = package_identity(artifact, marker)
            stage = profile + ':demo-sign'
            commands = Commands(ROOT, selected, build_environment(selected), deadline_seconds=600, command_seconds=120)
            signed = selected / 'signed'
            commands.run('actual-cost-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', signed, artifact)
            stage = profile + ':actual-signed-cases'
            observed = programme(native, signed, selected, profile)
            require(inventory(snapshot(app)) == before, 'Go-cost-observed-source-changed')
            record['profiles'].append({'profile': profile, 'fixture': source, 'build': marker,
                'package': package, 'programme': observed, 'commands': commands.records,
                'component': file_identity(artifact / 'component.wasm', 64 * 1024 * 1024)})
        stage = 'final-integrity'
        after = original.prepared(normal)
        require(after[2] == inherited and after[3] == compatibility
                and fixture_sources[0] == fixture_sources[1]
                and record['helpers'] == {name: file_identity(ROOT / name) for name in HELPERS},
                'Go-cost-observed-inputs-changed')
        record.update(status='passed', actualInvocations=6, cleanNodeStops=2,
                      identicalOrdinarySourceAcrossProfiles=True)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--normal-qualification', type=Path, required=True)
    parser.add_argument('--producer-receipt', type=Path, required=True)
    args = parser.parse_args()
    qualify(args.output, args.normal_qualification, args.producer_receipt)
