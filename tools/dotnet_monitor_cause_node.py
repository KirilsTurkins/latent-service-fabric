"""Original monitor control plus bounded causal observation on one authenticated node."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import time

from tools import dotnet_task_runtime_probe as authority, dotnet_monitor_cause_fixture as fixture
from tools.dotnet_standard_http_node import delete_when_audit_idle
from tools import guest_runtime_grants as clocks
from tools import resource_tenant_node as owners
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import WorkflowError, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, call, configure,
    deploy, sample, selected_revision, assert_value)
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.sdk_provider_scenario import close_failed_provider, start_provider

MODES = fixture.CASES

ORIGINAL_BUDGET = {'cpuFuel': 1000000000, 'memoryBytes': 134217728, 'wallTimeLimitMillis': 120000,
    'childCalls': 0, 'outboundRequests': 0, 'stateReadBytes': 0, 'stateWriteBytes': 0,
    'blobReadBytes': 0, 'blobWriteBytes': 0, 'logBytes': 0, 'effectCount': 0}


def original_budget(target):
    budget = target['budget']
    require(type(budget) is dict and budget == ORIGINAL_BUDGET
        and all(type(value) is int for value in budget.values()), 'dotnet-witness-original-deployment-budget')
    return dict(budget)


def observe_cases(client, target, component, record, accounting, checkpoint):
    require(fixture.CASES == MODES, 'monitor-cause-exact-selected-mode-order')
    all_passed = True
    for mode in MODES:
        label = 'dotnet-monitor-cause-' + mode
        revision = selected_revision(client, target)
        row = call(client, target, 'greeting', 'greet', ['task:' + mode], label)
        attempt = {'mode': mode, 'invocation': row, 'revision': revision}
        record['attempts'].append(attempt)
        checkpoint()
        # Unknown outcomes, foreign revisions or budget/effect drift never
        # authorize a second invocation. The actual first row is already saved.
        response = row['response']; used = response['data']['consumption']
        require(row['processReaped'] and response['outcomeKnown'] is True
            and revision['releaseDigest'] == component['sha256']
            and response['data']['resolvedRevision'] == revision,
            'monitor-cause-exact-terminal-and-revision')
        require(0 < int(used['cpuFuel']) <= target['budget']['cpuFuel'] == 1000000000
            and 0 < int(used['peakMemoryBytes']) <= target['budget']['memoryBytes'] == 134217728
            and all(int(used[key]) == 0 for key in ('outboundRequests', 'childCalls', 'effectCount',
                'logBytes', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')),
            'monitor-cause-original-budget-no-effects')
        try:
            # Mismatches also use the existing bounded/redacted diagnostics.
            value = fixture.observation(row) if mode == 'monitor-cause' else fixture.expected(mode)
            if mode == 'monitor-cause':
                attempt['diagnosticObservation'] = value
            assert_value(client, row, [{'ok': value}])
        except WorkflowError as error:
            all_passed = False
            attempt.update(status='unexpected-result', errorCategory=type(error).__name__)
            # The shared diagnostic has a fixed name. Move it in this owned
            # evidence directory before a later failure can try to write it.
            diagnostic = client.evidence / 'unexpected-invocation-diagnostics.json'
            destination = client.evidence / ('unexpected-' + mode + '-diagnostics.json')
            require(not diagnostic.is_symlink() and not destination.is_symlink()
                and not destination.exists(), 'monitor-cause-diagnostic-path')
            if diagnostic.exists():
                require(diagnostic.is_file(), 'monitor-cause-diagnostic-file')
                diagnostic.rename(destination)
                attempt['diagnostic'] = destination.name
        else:
            attempt['status'] = 'observed' if mode == 'monitor-cause' else 'passed'
        checkpoint()
        # Continue after an unexpected *known* terminal only if the actual
        # node remains alive and all original provider/cell owners are idle.
        require(client.node is not None and not client.node.owner.exited(),
            'monitor-cause-node-exited-before-retirement')
        attempt['retirement'] = {'provider': owners.provider_idle(client, target),
            'physical': sample(client, accounting, label + '-retired', 1)}
        checkpoint()
    return all_passed


def run(artifact: Path, native: dict, output: Path):
    output = fresh(output); component = file_identity(artifact / 'component.wasm')
    native_before = {key: file_identity(path) for key, path in native.items()}
    record = {'schemaVersion': 'latent.dotnet.monitor-cause.node.v1', 'status': 'incomplete',
        'expectedModes': list(MODES), 'attempts': [], 'component': component, 'native': native_before,
        'theseTwoCasesOnly': True, 'fullTicketQualification': False, 'diagnosticOnly': True}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
        deadline_seconds=360, command_seconds=120)
    peer = node = client = None; stage = 'sign-one-component'
    def checkpoint():
        (output / 'progress.json').write_bytes((json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode())
    try:
        signed = output / 'signed'; commands.run(stage, native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
            'monitor-cause-one-original-component-signature')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-monitor-cause-') as temporary:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'): (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 300), evidence=output / 'controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            peer, port = start_provider(client, work / 'peer', maximum_seconds=300)
            try:
                config, settings = configure(work / 'node', signed, port, language='dotnet', runtime_grants=True)
                authority.configure(settings)
                config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
                stage = 'node-and-original-runtime-authority'
                node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
                record['startup'] = node.startup_record; accounting = Probe(node, file_identity(native['latentd']))
                published = client.call('release', 'publish-package', signed / 'my-greeting/package',
                    '--evidence', signed / 'my-greeting/evidence/index.json', '--operation-id',
                    'monitor-cause-publish', '--expected-generation', '0')
                require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'monitor-cause-normal-component-admission')
                publications = {'greeting': published['data']['operation']['publication']['id']}
                targets = {'greeting': deploy(client, signed / 'my-greeting/deployment.json', publications['greeting'])}
                authority_record = {'invocations': []}
                clocks.grant(client, node, signed, targets, publications, authority_record, language='dotnet')
                authority.grant(client, node, signed, targets, publications, authority_record)
                target = targets['greeting']; record['authority'] = authority_record
                record['budget'] = original_budget(target)
                record['afterGrants'] = {'provider': owners.provider_idle(client, target),
                    'physical': sample(client, accounting, 'monitor-cause-after-grants', 1)}
                stage = 'two-actual-ordinary-observations'
                observations_passed = observe_cases(client, target, component, record, accounting, checkpoint)
                delete_when_audit_idle(client, target)
                record['afterDeletes'] = sample(client, accounting, 'monitor-cause-deleted', 0)
                stop(client, node); record['nodeShutdown'] = stopped_record(node)
                record['peerShutdown'] = stop_observation_peer(peer)
                require(record['nodeShutdown']['reaped'] and record['nodeShutdown']['record']['clean'],
                    'monitor-cause-clean-node-shutdown')
                require(observations_passed, 'monitor-cause-at-least-one-observation-failed')
            finally:
                client.node = None
                if node is not None: node.close()
                if peer is not None:
                    if 'peerShutdown' not in record: record['peerFailure'] = close_failed_provider(peer)
                    else: peer.close()
            cancellation.check()
        require(native_before == {key: file_identity(path) for key, path in native.items()}
            and component == file_identity(artifact / 'component.wasm') and client.calls <= 384
            and time.monotonic() < commands.deadline, 'monitor-cause-final-native-component-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record); return record
    except BaseException:
        record.update(status='failed', stage=stage); write_json(output / 'FAILED.json', record); raise
