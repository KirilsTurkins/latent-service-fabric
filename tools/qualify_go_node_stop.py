#!/usr/bin/env python3
"""Exercise actual signed Go work across real SIGTERM, physical shutdown and restart."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import go_node_stop_fixture as fixture, go_node_stop_probe as oracle
from tools import java_control_refusal_diagnostic as control_refusal
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.guest_runtime_grants import configure as runtime_configuration, grant as runtime_grants
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.qualify_sdk_scratch import _prepared_with_inputs, build_component, current_inputs, package_identity
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, assert_value, call, deploy, finish_call, selected_revision, start_call
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

HELPERS = ('tools/qualify_go_node_stop.py', 'tools/go_node_stop_fixture.py', 'tools/go_node_stop_probe.py',
           'tools/qualify_sdk_scratch.py', 'tools/guest_runtime_grants.py',
           'tools/phase2_operator_process.py', 'tools/phase2_operator_scenario.py',
           'tools/rust_capsule_node.py', 'tools/java_control_refusal_diagnostic.py')
SERVICE = 'examples/my-greeting'
REPOSITORY = 'KirilsTurkins/latent-service-fabric'
PRODUCER_HEAD = '94d0f8b0c1508df50e2830e6d678661c1e76bc36'
PRODUCER_RUN, PRODUCER_JOB, PRODUCER_ARTIFACT = 39373374237, 118465965449, 12242839929
WORKFLOW_HELPER = 'run_rust_capsule_workflow.py'
ORIGINAL_HELPER = {'sha256': 'sha256:c0e042d4c7c354246121125950ad96e430f26052fae59fad533c5dec4f0059cd', 'bytes': 32387}
DOTNET_ONLY_HELPER = {'sha256': 'sha256:528266f02ff5346dc7345ca47005183b592cc7aee2cb2994869cee6a1ea6cad9', 'bytes': 33227}
JAVA_ONLY_HELPER = {'sha256': 'sha256:42ad89492f745d5da1904d9341ec6baa15b8eeb09192830dc17c2931ebcf9e5a', 'bytes': 33706}
RESOURCE_ONLY_HELPER = {'sha256': 'sha256:7c32777ab230a9c1da5a8ad99b1edce1fd2518fad81525c52376a66ec27b67d7', 'bytes': 34233}
ORIGINAL_RUNTIME = {'sha256': 'sha256:d1d1507dc96ad0477edb06ec12af301e44c6a63d28abf9cb3c6e839d65b35738',
    'files': 3299, 'bytes': 25834970,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
TEST_ONLY_RUNTIME = {'sha256': 'sha256:410f3bea073b8a650b7539c28e3ec1ff2a766b6c2e1ecdd43d41cad459f76c4f',
    'files': 3299, 'bytes': 25835711,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}
STARTUP_TEST = {'path': 'apps/latentd/tests/standalone_node/startup.rs',
    'original': {'sha256': 'sha256:342724783f48ee39f53d62e0173e7ad6b3e0080972a4b80107dab94319f8389f', 'bytes': 6115},
    'current': {'sha256': 'sha256:d6b134b615c3ff39c9de975e6a12a3108a0598a249109ea1e236e2565db71854', 'bytes': 6856}}


def compatible_normal_source(original, current):
    """Reconcile enumerated unused-helper/test-only inputs, never production drift."""
    require(type(original) is dict and type(current) is dict and original.keys() == current.keys(),
            'Go-node-stop-original-source-shape')
    require(original['helpers'][WORKFLOW_HELPER] == ORIGINAL_HELPER
            and current['helpers'][WORKFLOW_HELPER] in
                (ORIGINAL_HELPER, DOTNET_ONLY_HELPER, JAVA_ONLY_HELPER, RESOURCE_ONLY_HELPER),
            'Go-node-stop-reviewed-unused-helper-required')
    selected = copy.deepcopy(current)
    selected['helpers'][WORKFLOW_HELPER] = ORIGINAL_HELPER
    native_equal = original['runtime'] == current['runtime']
    test_composition = None
    if not native_equal:
        require(original['runtime'] == ORIGINAL_RUNTIME and current['runtime'] == TEST_ONLY_RUNTIME,
                'Go-node-stop-reviewed-native-test-only-source-must-match')
        # Both whole inventories are pinned. Their only Git-source delta is this
        # integration test, which is not compiled into any restored executable.
        selected['runtime'] = copy.deepcopy(original['runtime'])
        test_composition = {'originalInventory': original['runtime'],
            'currentInventory': current['runtime'], 'soleChangedSource': copy.deepcopy(STARTUP_TEST),
            'restoredExecutablesRebuilt': False}
    require(selected == original, 'Go-node-stop-native-Go-and-used-helpers-must-match')
    return {'originalNormalSource': PRODUCER_HEAD, 'normalInvocations': 27,
        'nativeSdkWitSchemasAndUsedHelpersEqual': native_equal,
        'nativeProductionSdkWitSchemasAndUsedHelpersEqual': True,
        'nativeTestOnlyComposition': test_composition,
        'unusedNormalWorkflowHelper': {'original': ORIGINAL_HELPER, 'current': current['helpers'][WORKFLOW_HELPER]},
        'originalNormalProgrammeRelabelledAsCurrent': False}


def prepared(normal):
    source = read_json(normal / 'source-inputs.json', 16 * 1024 * 1024)
    compatibility = compatible_normal_source(source, current_inputs('go'))
    binaries, companions, inherited = _prepared_with_inputs(normal, 'go', source)
    return binaries, companions, inherited, compatibility


def validate_producer(value):
    run, job, artifact = (value[name] for name in ('run', 'job', 'artifact'))
    require(run['id'] == PRODUCER_RUN and run['head_sha'] == PRODUCER_HEAD
        and run['event'] == 'push' and run['path'] == '.github/workflows/go-scratch-reference.yml'
        and run['head_branch'] == 'feat/go-standard-scratch-20261020'
        and run['status'] == 'completed' and run['conclusion'] == 'success',
        'Go-node-stop-exact-normal-producer-required')
    require(job['id'] == PRODUCER_JOB and job['run_id'] == PRODUCER_RUN and job['head_sha'] == PRODUCER_HEAD
        and job['status'] == 'completed' and job['conclusion'] == 'success'
        and all(next(row for row in job['steps'] if row['number'] == number)['conclusion'] == 'success'
                for number in (11, 12, 13, 14, 15, 16)), 'Go-node-stop-producer-actual-steps-required')
    require(artifact['id'] == PRODUCER_ARTIFACT and artifact['workflow_run']['id'] == PRODUCER_RUN
        and artifact['workflow_run']['head_sha'] == PRODUCER_HEAD and artifact['expired'] is False
        and artifact['name'] == 'go-scratch-prepared-' + PRODUCER_HEAD
        and artifact['size_in_bytes'] == 68946198
        and artifact['digest'] == 'sha256:d748d316bec91a06f3856b5f64e18e16ab71dd824d7a16d1fd8f6ec8c39ec4ea',
        'Go-node-stop-exact-public-artifact-required')
    return {'run': PRODUCER_RUN, 'job': PRODUCER_JOB, 'head': PRODUCER_HEAD,
            'artifact': PRODUCER_ARTIFACT, 'artifactDigest': artifact['digest'],
            'originalNormalSignedInvocations': 27, 'newNativeBuild': False}


def record_producer(output):
    value = {}
    for key, path in [('run', f'actions/runs/{PRODUCER_RUN}'), ('job', f'actions/jobs/{PRODUCER_JOB}'),
                      ('artifact', f'actions/artifacts/{PRODUCER_ARTIFACT}')]:
        result = subprocess.run(['gh', 'api', f'repos/{REPOSITORY}/{path}'],
                                check=True, capture_output=True, timeout=30)
        require(len(result.stdout) <= 131072, 'Go-node-stop-producer-metadata-bound')
        value[key] = json.loads(result.stdout)
    validate_producer(value)
    write_json(output, value)
    return value


def configuration(directory, signed):
    path = configure_node(directory, signed, 'examples')
    value = read_json(path)
    # Keep the existing Go authoring request and real-node shutdown bounds.
    value['execution']['maximumWallTimeMillis'] = 120000
    value['shutdownGraceMillis'] = 5000
    value['cache'].update(entries=2, preparations=1)
    value['budgetProfile'] = {'mode': 'phase3', 'maximumOutboundRequests': 0,
                            'maximumBlobReadBytes': 0, 'maximumBlobWriteBytes': 0}
    value['capabilityPolicies'] = {'formatVersion': 1, 'maximumControlJobs': 2,
        'store': {'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
                  'maximumReadOwners': 64, 'maximumPageRecords': 16}}
    value['audit'].update(records=1024, diskBytes=16777216)
    value['providers'] = {'formatVersion': 1, 'bindings': []}
    runtime_configuration(value, ('greeting',), language='go')
    # The helper's eight-slot audit queue drops optional observations during
    # normal v5 startup. Select the ordinary supported node default for this
    # strict evidence programme; guest, cell and request bounds stay unchanged.
    value['audit']['queuedOperations'] = 64
    value['providers']['activationRuntime'] = {'identity': {'id': 'activation', 'tenant': 'examples',
        'service': 'activation-host', 'epoch': 1}, 'limits': dict(oracle.OWNER_LIMITS)}
    value['providers']['bindings'].append({'name': 'activation-greeting', 'tenant': 'examples',
        'consumerService': SERVICE, 'providerService': 'activation-host',
        'contract': oracle.ACTIVATION, 'providerBinding': 'activation-installed'})
    require(len(value['providers']['bindings']) == 4, 'Go-node-stop-four-explicit-bindings')
    encoded = json.dumps(value, indent=2).encode() + b'\n'
    require(len(encoded) <= 262144, 'Go-node-stop-owned-config-bound')
    path.write_bytes(encoded)
    return path


def install_activation(client, node, signed, target, publication):
    descriptor, = [row for row in node.startup_record['providers'] if row['id'] == 'activation']
    require(descriptor['capability'] == oracle.ACTIVATION and descriptor['profile'] == oracle.PROFILE,
            'Go-node-stop-exact-installed-provider')
    for kind, name, value in [
        ('provider-binding', 'activation-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': oracle.ACTIVATION, 'providerProfile': oracle.PROFILE,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': oracle.OPERATIONS}}),
        ('policy', 'activation-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': oracle.ACTIVATION,
            'operations': oracle.OPERATIONS, 'resources': {'kind': 'clock'},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768,
                        'wallTimeMillis': target['budget']['wallTimeLimitMillis']}}]})]:
        path = client.directory / (name + '.json')
        write_json(path, value)
        command = ['policy'] + (['--kind', kind] if kind != 'policy' else [])
        client.call(*command, 'apply', '--id', name, '--file', path,
                    '--operation-id', 'install-' + name, '--expected-generation', '0')
    return deploy(client, signed / 'my-greeting/deployment.json', publication,
        generation=str(target['generation']),
        grants=target['grants'] + [{'capability': oracle.ACTIVATION, 'policy': 'activation-allow'}])


def audit_pages(client, since):
    pages, identities, token, seen = [], [], None, set()
    for _ in range(4):
        command = ('audit', 'query', '--scope', 'tenant', '--page-size', '64',
                   '--from-unix-millis', str(since))
        if token is not None:
            command += ('--page-token', token)
        page = client.call(*command, codes=(0, 4))
        path = client.evidence / f'{client.calls:03}.json'
        identities.append({'path': path.name, **file_identity(path, 262144)})
        if page['category'] != 'success':
            refused = oracle.refused_observation(page)
            return None, {'refusal': refused, 'queryFiles': identities,
                'context': {'scope': 'tenant', 'fromUnixMillis': str(since),
                    'pageSize': 64, 'pageOrdinal': len(identities), 'cursorPresent': token is not None}}
        pages.append(page)
        token = page['data']['page']['nextPageToken']
        if token is None:
            return pages, identities
        require(type(token) is str and token not in seen, 'Go-node-stop-audit-cursor-cycle')
        seen.add(token)
    raise RuntimeError('Go-node-stop-audit-page-bound')


def wait_live(client, node, pending, mode):
    original = client.deadline
    client.deadline = min(original, time.monotonic() + 10)
    refused = []
    try:
        for attempt in range(16):
            require(time.monotonic() < client.deadline, 'Go-node-stop-live-barrier-deadline')
            require(not pending.owner.exited(), 'Go-node-stop-guest-completed-before-signal')
            node.drain()
            pages, identities = audit_pages(client, max(0, pending.authoring_started_unix_millis - 1000))
            if pages is None:
                node.drain()
                item = {'attempt': attempt + 1, **identities,
                        'hostRefusals': control_refusal.observe(bytes(node.buffers[1]))}
                refused.append(item)
                write_json(client.evidence / ('refused-audit-' + str(attempt + 1) + '.json'), item)
                require(not pending.owner.exited(), 'Go-node-stop-guest-completed-before-signal')
                require(time.monotonic() < client.deadline, 'Go-node-stop-live-barrier-deadline')
                time.sleep(0.01)
                continue
            inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']
            providers = client.call('capability', 'list', '--deployment', 'my-greeting', '--include-node-usage')['data']
            require(providers['nextPageToken'] is None, 'Go-node-stop-provider-page-bound')
            observed = oracle.barrier(inventory, pages, pending.authoring_activation, mode,
                                      provider_usage=providers)
            require(not pending.owner.exited(), 'Go-node-stop-guest-completed-before-signal')
            require(time.monotonic() < client.deadline, 'Go-node-stop-live-barrier-deadline')
            if observed is not None:
                return {'observation': observed, 'inventory': inventory, 'providerUsage': providers,
                        'auditFiles': identities,
                        'refusedAuditObservations': refused,
                        'hostRefusals': control_refusal.observe(bytes(node.buffers[1])),
                        'attempts': attempt + 1}
            time.sleep(0.01)
        raise RuntimeError('Go-node-stop-live-barrier-attempts')
    finally:
        client.deadline = original


def fresh_call(client, target, name):
    revision = selected_revision(client, target)
    row = call(client, target, 'greeting', 'greet', ['node-stop:fresh'], name)
    assert_value(client, row, [{'ok': 'node-stop|fresh=1|value=42'}])
    require(row['processReaped'], 'Go-node-stop-fresh-process-not-reaped')
    data = row['response']['data']
    require(data.get('resolvedRevision') == revision, 'Go-node-stop-fresh-published-identity')
    consumption = data['consumption']
    require(0 < oracle.integer(consumption['cpuFuel']) <= target['budget']['cpuFuel']
            and 0 < oracle.integer(consumption['peakMemoryBytes']) <= target['budget']['memoryBytes']
            and all(oracle.integer(consumption[name]) == 0 for name in
                    ('outboundRequests', 'childCalls', 'logBytes', 'effectCount')),
            'Go-node-stop-fresh-original-budget-and-effects')
    return row


def programme(native, signed, output):
    result = {'status': 'in-progress', 'modes': []}
    for index, mode in enumerate(('pending', 'drain')):
        selected = output / mode
        selected.mkdir()
        with tempfile.TemporaryDirectory(prefix='lsf-go-node-stop-') as private, owned_cancellation() as cancellation:
            work = Path(private)
            for name in ('client', 'node'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                time.monotonic() + 120, evidence=selected / 'controls', invocation_timeout_millis=120000)
            path = configuration(work / 'node', signed)
            node = pending = None
            record = {'mode': mode, 'actualSignal': 'SIGTERM', 'shutdownGraceMillis': 5000,
                      'ownerLimits': dict(oracle.OWNER_LIMITS)}
            try:
                node = connect(client, native['latentd'], work / 'node', path, 'examples', index * 2 + 1,
                               control_refusal_diagnostic=True)
                record['startup'] = node.startup_record
                source = signed / 'my-greeting'
                publication = client.call('release', 'publish-package', source / 'package',
                    '--evidence', source / 'evidence/index.json', '--operation-id', 'publish-greeting',
                    '--expected-generation', '0')['data']['operation']['publication']['id']
                target = deploy(client, source / 'deployment.json', publication)
                targets = {'greeting': target}
                runtime_grants(client, node, signed, targets, {'greeting': publication}, record, language='go')
                target = install_activation(client, node, signed, targets['greeting'], publication)
                record['freshBefore'] = fresh_call(client, target, 'node-stop-' + mode + '-before')
                pending = start_call(client, target, 'greeting', 'greet', ['node-stop:' + mode], 'node-stop-' + mode)
                live = wait_live(client, node, pending, mode)
                write_json(selected / 'accepted-live-work.json', live)
                record['liveBarrier'] = live['observation']
                # This is the existing real SIGTERM/reap path. No cancel RPC,
                # invocation-handle drop or artificial elapsed-timer success.
                stop(client, node)
                stopped = stopped_record(node)
                record['shutdownWhileLive'] = stopped
                record['liveNodeControlRefusals'] = control_refusal.observe(bytes(node.buffers[1]))
                oracle.shutdown(stopped)
                node = None
                deadline = client.deadline
                try:
                    client.deadline = min(deadline, time.monotonic() + 10)
                    interrupted = finish_call(client, pending)
                finally:
                    client.deadline = deadline
                pending = None
                record['interruptedInvocation'] = interrupted
                record['transportDisposition'] = oracle.interrupted(interrupted)
                node = connect(client, native['latentd'], work / 'node', path, 'examples', index * 2 + 2,
                               control_refusal_diagnostic=True)
                record['restart'] = node.startup_record
                record['freshAfterRestart'] = fresh_call(client, target, 'node-stop-' + mode + '-after')
                stop(client, node)
                final = stopped_record(node)
                oracle.shutdown(final)
                record['shutdownAfterFresh'] = final
                record['freshNodeControlRefusals'] = control_refusal.observe(bytes(node.buffers[1]))
                node = None
                record['status'] = 'passed'
                write_json(selected / 'result.json', record)
                result['modes'].append(record)
            except BaseException:
                record['status'] = 'failed'
                if node is not None:
                    record['controlRefusals'] = control_refusal.observe(bytes(node.buffers[1]))
                write_json(selected / 'FAILED.json', record)
                raise
            finally:
                if pending is not None:
                    pending.close()
                if node is not None:
                    node.close()
    result['status'] = 'passed'
    result['realNodeStarts'] = result['cleanReapedNodeStops'] = 4
    result['actualGoInvocations'] = 6
    result['unchangedSignedProductsAcrossRestart'] = True
    return result


def qualify(output, normal, producer):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'Go-node-stop-unprivileged-linux-python313')
    output = output.absolute()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents,
            'Go-node-stop-output-outside-checkout')
    output = fresh(output)
    record = {'schemaVersion': 'latent.go.node-stop.v1', 'status': 'in-progress',
              'fullTicketQualification': False, 'newNativeBuild': False,
              'helpers': {name: file_identity(ROOT / name) for name in HELPERS}}
    stage = 'original-normal-products'
    try:
        record['producer'] = validate_producer(read_json(producer))
        binaries, _companions, inherited, compatibility = prepared(normal)
        require(inherited['originalInvocations'] == 27, 'Go-node-stop-original-normal27')
        record['inherited'] = inherited
        record['sourceCompatibility'] = compatibility
        for path in binaries.values():
            path.chmod(0o700)
        native = {'latent': binaries['latent'], 'latentd': binaries['latentd']}
        stage = 'ordinary-v5-source'
        app, record['fixture'] = fixture.project(output / 'application')
        before = inventory(snapshot(app))
        stage = 'fresh-component-build'
        artifact = build_component('go', app, output / 'build', binaries)
        require(read_file(artifact / 'source-inputs.json') == before, 'Go-node-stop-built-source-mismatch')
        record['build'] = read_json(artifact / 'BUILD-COMPLETE.json')
        record['package'] = package_identity(artifact, record['build'])
        stage = 'normal-demo-sign'
        commands = Commands(ROOT, output, build_environment(output), deadline_seconds=600, command_seconds=120)
        signed = output / 'signed'
        commands.run('actual-node-stop-demo-sign', binaries['examples/capsule_authoring'], 'demo-sign', signed, artifact)
        stage = 'actual-signed-node-stop'
        record['programme'] = programme(native, signed, output)
        stage = 'final-integrity'
        after = prepared(normal)
        require(after[2] == inherited and after[3] == compatibility and inventory(snapshot(app)) == before
                and record['helpers'] == {name: file_identity(ROOT / name) for name in HELPERS},
                'Go-node-stop-observed-inputs-changed')
        record.update(status='passed', component=file_identity(artifact / 'component.wasm', 64 * 1024 * 1024),
                      commands=commands.records)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        write_json(output / 'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--normal-qualification', type=Path)
    parser.add_argument('--producer-receipt', type=Path)
    parser.add_argument('--record-producer', action='store_true')
    args = parser.parse_args()
    if args.record_producer:
        require(args.normal_qualification is None and args.producer_receipt is None,
                'Go-node-stop-producer-only-selection')
        record_producer(args.output)
    else:
        require(args.normal_qualification is not None and args.producer_receipt is not None,
                'Go-node-stop-original-inputs-required')
        qualify(args.output, args.normal_qualification, args.producer_receipt)
