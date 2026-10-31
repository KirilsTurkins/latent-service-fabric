"""Ordinary C lifecycle calls through the selected, enforced node profile.

The audit barrier establishes child entry and physical liveness. It never
claims a timer Pending witness or a successful typed result from audit alone.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import base64
import json
from pathlib import Path
import tempfile
import time

from tools import c_thread_runtime_fixture as fixture
from tools.c_guest.threading import IMPORTS, PROFILE
from tools.c_guest.standard_facilities import FETCH_PROFILE, FETCH_STANDARD_PROFILE
from tools.phase2_operator_process import require, write_json
from tools.phase2_operator_process import stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS, integer
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, configure as configure_base, delete_all,
    deploy, sample, selected_revision, start_call, MEDIA)
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.sdk_provider_scenario import start_provider

ACTIVATION, NATIVE = IMPORTS
SERVICE = 'c-thread-runtime'
LIVE = ('execution-cell-leases', 'guest-invocations', 'guest-stores',
        'guest-host-states', 'guest-component-instances')
PROVIDERS = {
    ACTIVATION: ('c-activation', 'activation-owned-v1',
                 ['register', 'park', 'wake', 'settle', 'observe'], 'clock'),
    NATIVE: ('c-native', 'conservative-native-total-starts-v1', ['start'], 'context'),
}


def configure(settings, capsule):
    imports = capsule.get('imports')
    require(type(imports) is list and len(imports) == 2
            and all(type(row) is dict and set(row) == {'contract', 'optional'}
                    and row['optional'] is False for row in imports)
            and {row['contract'] for row in imports} == set(IMPORTS), 'c-thread-two-explicit-imports')
    require(capsule['execution']['limits']['memoryBytes'] == 32 * 1024 * 1024
            and capsule['execution']['limits']['wallTimeLimitMillis'] == 5000,
            'c-thread-one-original-fixture-envelope')
    require(settings['workers'] == {'runtime': 1, 'control': 1}
            and len(settings['cells']) == 1 and settings['cells'][0]['capacity'] == 1
            and settings['cells'][0]['queueCapacity'] == 2, 'c-thread-original-one-cell')
    require(settings['audit'] == {'mode': 'durable', 'records': 1024, 'diskBytes': 16 * 1024 * 1024,
            'queuedOperations': 8, 'queryOwners': 2}, 'c-thread-original-diagnostic-audit-envelope')
    # Nine original pre-hold provider calls can offer 18 optional observations.
    # Each holds 16 KiB through journal completion; one serialized query needs 4 KiB.
    # This is a finite test-environment envelope, not a durable/lossless guarantee.
    settings['audit']['queuedOperations'] = (9 * 2 * 16384 + 4096) // 4096
    settings.setdefault('engine', {})['threadingProfile'] = PROFILE
    providers = settings['providers']
    providers['activationRuntime'] = {'identity': {'id': 'c-activation', 'tenant': 'examples',
        'service': 'c-runtime-host', 'epoch': 1}, 'limits': dict(fixture.LIMITS), 'nativeThreads': True}
    for capability, (identity, _, _, _) in PROVIDERS.items():
        providers['bindings'].append({'name': identity, 'tenant': 'examples',
            'consumerService': 'examples/' + SERVICE, 'providerService': 'c-runtime-host',
            'contract': capability, 'providerBinding': identity + '-installed'})
    require(len(providers['bindings']) == 3, 'c-thread-exact-original-plus-two-bindings')
    return settings


def install(client, node, target):
    grants = []
    for capability, (identity, profile, operations, resource) in PROVIDERS.items():
        rows = [row for row in node.startup_record['providers'] if row['capability'] == capability]
        require(len(rows) == 1 and rows[0]['tenant'] == 'examples'
                and rows[0]['service'] == 'c-runtime-host' and rows[0]['profile'] == profile
                and rows[0]['configurationEpoch'] == '1', 'c-thread-exact-installed-provider')
        descriptor = rows[0]
        binding = client.directory / (identity + '-binding.json')
        write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': operations}})
        result = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', identity + '-installed',
            '--file', binding, '--operation-id', 'install-' + identity, '--expected-generation', '0')
        require(result['outcomeKnown'] is True, 'c-thread-known-binding')
        policy = client.directory / (identity + '-policy.json')
        write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'ordinary-c', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': capability, 'operations': operations, 'resources': {'kind': resource},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result = client.call('policy', 'apply', '--id', identity + '-allow', '--file', policy,
            '--operation-id', 'allow-' + identity, '--expected-generation', '0')
        require(result['outcomeKnown'] is True, 'c-thread-known-policy')
        grants.append({'capability': capability, 'policy': identity + '-allow'})
    return grants


def usage(client, target, *, idle):
    value = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    require(value['nextPageToken'] is None, 'c-thread-one-capability-page')
    node = value['nodeUsage']
    require(type(node) is dict and node['scope'] == 'node' and node['unavailable'] == []
            and type(node['counters']) is dict and set(ACTIVE_COUNTERS) <= node['counters'].keys(),
            'c-thread-original-node-usage-schema')
    counters = {name: integer(node['counters'][name]) for name in ACTIVE_COUNTERS}
    if idle:
        require(all(value == 0 for value in counters.values()), 'c-thread-all-provider-owners-retired')
    return value


def positive_audit_coverage(pages):
    """Qualify retained positive records, never completeness of optional capture."""
    require(type(pages) is list and 0 < len(pages) <= 4, 'c-thread-audit-page-bound')
    epoch, high, drops, seen_tokens, previous_sequence = None, None, [], set(), 0
    for index, page in enumerate(pages):
        require(page['category'] == 'success' and page['outcomeKnown'] is True
                and page['requestDispatched'] is True, 'c-thread-positive-audit-query-known')
        coverage = page['data']['coverage']
        raw_epoch = coverage['epoch']
        require(type(raw_epoch) is str and len(raw_epoch) == 32
                and all(value in '0123456789abcdef' for value in raw_epoch), 'c-thread-positive-audit-epoch')
        numbers = {}
        for name in ('retainedFloor', 'highWatermark', 'scanned', 'droppedObservations', 'unknownOutcomes'):
            require(type(coverage[name]) is str, 'c-thread-positive-audit-wire-counter')
            numbers[name] = integer(coverage[name])
        require(numbers['retainedFloor'] == 1 and numbers['unknownOutcomes'] == 0
                and coverage['previousSessionLossUnknown'] is False
                and numbers['droppedObservations'] < 2**64 - 1, 'c-thread-positive-audit-known-coverage')
        if epoch is None:
            epoch, high = raw_epoch, numbers['highWatermark']
        require((raw_epoch, numbers['highWatermark']) == (epoch, high),
                'c-thread-positive-audit-frozen-cursor')
        records = page['data']['records']
        require(type(records) is list and len(records) <= 64
                and len(records) <= numbers['scanned'] <= 1024, 'c-thread-positive-audit-scan-bound')
        for row in records:
            sequence = integer(row['sequence'])
            require(row['epoch'] == epoch and previous_sequence < sequence <= high,
                    'c-thread-positive-audit-ordered-current-record')
            previous_sequence = sequence
        token = page['data']['page']['nextPageToken']
        if index == len(pages) - 1:
            require(token is None and coverage['stop'] == 'AUDIT_PAGE_STOP_END',
                    'c-thread-positive-audit-complete-cursor')
        else:
            require(type(token) is str and 0 < len(token) <= 256 and token not in seen_tokens
                    and coverage['stop'] in ('AUDIT_PAGE_STOP_RECORD_LIMIT', 'AUDIT_PAGE_STOP_BYTE_LIMIT',
                                             'AUDIT_PAGE_STOP_SCAN_LIMIT'), 'c-thread-positive-audit-next-cursor')
            seen_tokens.add(token)
        if drops:
            require(numbers['droppedObservations'] >= integer(drops[-1]),
                    'c-thread-positive-audit-monotonic-loss-counter')
        drops.append(coverage['droppedObservations'])
    return {'mode': 'retained-positive-records', 'epoch': epoch, 'highWatermark': str(high),
        'droppedObservationsByPage': drops, 'optionalObservationLossReported': any(integer(v) > 0 for v in drops),
        'completeFrozenCursor': True, 'losslessCaptureClaimed': False, 'negativeEvidenceClaimed': False}


def child_entry(inventory, pages, activation, *, expected_revision, positive_only=False):
    require(type(positive_only) is bool, 'c-thread-closed-audit-evidence-mode')
    topology = inventory['topology']
    require(topology['available'] is True and topology['complete'] is True, 'c-thread-live-topology')
    rows = {row['name']: row for row in topology['entries']}
    require(len(rows) == len(topology['entries']) and set(LIVE) <= rows.keys(), 'c-thread-five-live-rows')
    if any(integer(rows[name]['activeCount']) != 1 for name in LIVE):
        return None
    require(type(pages) is list and 0 < len(pages) <= 4, 'c-thread-audit-page-bound')
    require(pages[-1]['data']['page']['nextPageToken'] is None, 'c-thread-audit-complete')
    coverage = positive_audit_coverage(pages) if positive_only else None
    observed, seen, epochs = {}, set(), set()
    for page in pages:
        require(page['category'] == 'success' and page['outcomeKnown'] is True
                and (positive_only or integer(page['data']['coverage']['droppedObservations']) == 0),
                'c-thread-lossless-current-audit-required')
        require(type(page['data']['records']) is list and len(page['data']['records']) <= 64,
                'c-thread-audit-record-bound')
        for row in page['data']['records']:
            epoch, sequence = row['epoch'], integer(row['sequence'])
            require(type(epoch) is str and len(epoch) == 32 and all(c in '0123456789abcdef' for c in epoch)
                    and sequence > 0 and (epoch, sequence) not in seen, 'c-thread-distinct-audit-identity')
            seen.add((epoch, sequence))
            event = row.get('data', {}).get('observation', {})
            identities = event.get('identities', {})
            identity = identities.get('capability', {})
            capability = identity.get('capability')
            if identity.get('activation') != activation or capability not in PROVIDERS:
                continue
            require(identity['rootActivation'] == activation and identity['service'] == 'examples/' + SERVICE
                    and identity['providerProfile'] == PROVIDERS[capability][1], 'c-thread-current-provider-audit')
            require(identities['publicationId'] == expected_revision['publicationId']
                    and identities['componentDigest'] == expected_revision['releaseDigest']
                    and identities['revision'] == expected_revision['revisionId']
                    and integer(identities['routeGeneration']) == integer(expected_revision['routeGeneration']),
                    'c-thread-current-published-revision-audit')
            epochs.add(epoch)
            if event['kind'] == 'PHASE2_AUDIT_EVENT_KIND_CAPABILITY_PROVIDER_OUTCOME' \
                    and identity.get('providerOutcome') == 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED':
                key = (capability, identity['operation'])
                observed.setdefault(key, []).append(sequence)
    require(len(epochs) <= 1, 'c-thread-one-current-audit-epoch')
    starts, entered = observed.get((NATIVE, 'start'), []), observed.get((ACTIVATION, 'observe'), [])
    if len(starts) != 1 or len(entered) != 1 or starts[0] >= entered[0]:
        return None
    result = {'activation': activation, 'nativeStartCompletedSequence': starts[0],
        'childObserveCompletedSequence': entered[0], 'physicalOwners': {name: 1 for name in LIVE},
        'sourceBoundChildEntry': True, 'typedObserveSuccessClaimed': False, 'waitForPollPendingClaimed': False}
    if positive_only:
        result['auditCoverage'] = coverage
    return result


@contextmanager
def owned_cleanup(record):
    stack = ExitStack()
    try:
        yield stack
    except BaseException:
        try:
            stack.close()
        except BaseException:
            record['cleanupRefused'] = True
            record['originalFailurePreserved'] = True
        raise
    else:
        stack.close()


def close_call(process, *, primary_failure):
    try:
        process.close()
    except BaseException:
        if not primary_failure:
            raise


def retain_partial(process, output, activation):
    process.drain()
    stdout, stderr = (bytes(part) for part in process.buffers)
    require(len(stdout) <= 32768 and len(stderr) <= 32768, 'c-thread-partial-output-bound')
    # Only the ordinary public CLI result and its fixed public diagnostics.
    (output / (activation + '.stdout')).write_bytes(stdout)
    (output / (activation + '.stderr')).write_bytes(stderr)


def finish_call(client, process):
    primary = False
    try:
        completed = process.complete(min(client.deadline, time.monotonic() + 8))
    except BaseException:
        primary = True
        raise
    finally:
        close_call(process, primary_failure=primary)
    value = json.loads(completed.stdout)
    require(value['schemaVersion'] == 'latent.cli.result.v1' and completed.returncode in (0, 3, 4, 5),
            'c-thread-original-public-result-schema')
    payload = value['data'].get('payload') or (value['data'].get('declaredError') or {}).get('payload')
    decoded = None
    if payload:
        require(payload['encoding'] == 'base64' and payload['mediaType'] == MEDIA and len(payload['data']) <= 8192,
                'c-thread-original-typed-result-bound')
        decoded = json.loads(base64.b64decode(payload['data'], validate=True))
    row = {'activation': process.authoring_activation, 'exitCode': completed.returncode,
        'startedAtUnixMillis': str(process.authoring_started_unix_millis),
        'elapsedNanos': str(time.monotonic_ns() - process.authoring_started), 'decoded': decoded,
        'response': value, 'processReaped': process.owner.finished}
    write_json(client.evidence / (process.authoring_activation + '.json'), row)
    return row


def retire(client, probe, target, output, activation):
    value = {'physical': sample(client, probe, 'after-' + activation, 1),
             'providerUsage': usage(client, target, idle=True)}
    write_json(output / ('retirement-' + activation + '.json'), value)
    return {'activation': activation, 'physicalOwnersAfter': 0, 'activeProviderCountersAfter': 0}


def wait_child(client, process, probe, target, output):
    revision = selected_revision(client, target)
    for attempt in range(8):
        require(time.monotonic() < client.deadline and not process.owner.exited(), 'c-thread-child-before-terminal')
        pages, token = [], None
        for _ in range(4):
            command = ('audit', 'query', '--scope', 'tenant', '--page-size', '64',
                '--from-unix-millis', str(max(0, process.authoring_started_unix_millis - 1)))
            if token is not None:
                command += ('--page-token', token)
            page = client.call(*command)
            pages.append(page)
            write_json(output / f'child-audit-{process.authoring_activation}-{attempt}-{len(pages)}.json', page)
            token = page['data']['page']['nextPageToken']
            if token is None:
                break
        inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']
        write_json(output / f'child-inventory-{process.authoring_activation}-{attempt}.json', inventory)
        witness = child_entry(inventory, pages, process.authoring_activation,
            expected_revision=revision, positive_only=True)
        if witness is not None:
            physical = sample(client, probe, 'entered-' + process.authoring_activation, 1, active=True)
            value = {'witness': witness, 'inventory': inventory, 'auditPages': pages,
                     'providerUsage': usage(client, target, idle=False), 'physical': physical}
            require(not process.owner.exited(), 'c-thread-child-ended-before-physical-witness')
            write_json(output / ('child-' + process.authoring_activation + '.json'), value)
            return witness
        process.drain()
    raise ValueError('c-thread-child-entry-not-observed')


def wait_audit_idle(client, target, output, activation):
    names = ('audit_queued_operations', 'audit_queued_bytes', 'audit_reserved_records',
        'audit_reserved_bytes', 'audit_pending_attempts', 'audit_query_owners',
        'audit_query_bytes', 'audit_recovery_pending', 'audit_closed')
    for attempt in range(16):
        observed = usage(client, target, idle=True)
        write_json(output / ('audit-before-' + activation + '-' + str(attempt) + '.json'), observed)
        counters = observed['nodeUsage']['counters']
        require(integer(counters['audit_closed']) == 0
            and integer(counters['audit_recovery_pending']) == 0, 'c-thread-precall-audit-live')
        if all(integer(counters[name]) == 0 for name in names):
            write_json(output / ('audit-before-' + activation + '.json'), observed)
            return observed
        if attempt < 15:
            time.sleep(0.01)
    raise ValueError('c-thread-precall-audit-idle-premise')


def invoke(client, probe, target, output, mode, activation, *, cancel=False):
    revision = selected_revision(client, target)
    # This final case runs after the ordinary hot-cache controls. Request a
    # shorter deadline so it can precede fuel exhaustion in the unchanged1B
    # CPU-spin envelope; the actual terminal cause and positive child/physical
    # barrier remain mandatory. This makes no fairness or timing guarantee.
    if mode in ('cancel', 'deadline'):
        wait_audit_idle(client, target, output, activation)
    process = start_call(client, target, SERVICE, 'greet', [mode], activation,
                         wall=250 if mode == 'deadline' else None)
    primary = False
    try:
        witness = None
        if mode in ('cancel', 'deadline'):
            witness = wait_child(client, process, probe, target, output)
            if cancel:
                acknowledgement = client.call('activation', 'cancel', activation, '--reason', 'C child lifecycle control')
                require(acknowledgement['outcomeKnown'] is True
                        and acknowledgement['data']['disposition'] == 'accepted', 'c-thread-known-cancel')
        row = finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
                and row['response']['requestDispatched'] is True
                and row['response']['data']['resolvedRevision'] == revision, 'c-thread-known-reaped-current-invocation')
        require(all(integer(row['response']['data']['consumption'][name]) == 0 for name in
                    ('outboundRequests', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes',
                     'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')), 'c-thread-no-other-authority-used')
        if mode in ('root-trap', 'callback-trap', 'cancel', 'deadline'):
            code = {'root-trap': 'guest-trap', 'callback-trap': 'guest-trap',
                    'cancel': 'cancelled', 'deadline': 'deadline-exceeded'}[mode]
            require(row['exitCode'] == 4 and row['response']['error']['code'] == code,
                    'c-thread-exact-terminal-cause')
        elif mode == 'application-error':
            require(row['exitCode'] == 3 and row['decoded'] == [{'err': 'application-error'}],
                    'c-thread-original-application-error')
        elif mode == 'root-return':
            require(row['exitCode'] == 0 and row['decoded'] == [{'ok': 'drain-1'}],
                    'c-thread-root-return-waits-for-real-child')
        else:
            require(row['exitCode'] == 0 and type(row['decoded']) is list and len(row['decoded']) == 1
                    and set(row['decoded'][0]) == {'ok'}, 'c-thread-ordinary-success')
            children = {'mixed': 2, 'pressure': 3, 'sync-pthread': 2, 'sync-mixed': 2}.get(mode, 1)
            witness = fixture.observation(row['decoded'][0]['ok'], children,
                synchronized=mode in ('sync-pthread', 'sync-mixed'))
        result = {'activation': activation, 'mode': mode, 'exitCode': row['exitCode'],
                  'witness': witness, 'retirement': retire(client, probe, target, output, activation)}
        return result
    except BaseException:
        primary = True
        try:
            retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        close_call(process, primary_failure=primary)


def denied(row):
    response = row['response']
    require(row['exitCode'] == 4 and row['processReaped'] is True
            and response['outcomeKnown'] is True and response['requestDispatched'] is True
            and response['error']['code'] == 'permission-denied', 'c-thread-explicit-authority-required')
    consumption = response['data']['consumption']
    require(all(integer(consumption[name]) == 0 for name in
                ('cpuFuel', 'peakMemoryBytes', 'outboundRequests', 'logBytes', 'effectCount')),
            'c-thread-denied-before-guest-and-resource-allocation')


def programme(client, node, probe, manifest, target, output):
    require(target['grants'] == [], 'c-thread-no-default-authority')
    grants = install(client, node, target)
    outcomes = []
    for index, missing in enumerate(IMPORTS):
        target = deploy(client, manifest, target['publication'], generation=str(target['generation']),
                        grants=[row for row in grants if row['capability'] != missing])
        activation = 'c-thread-authority-' + str(index)
        process = start_call(client, target, SERVICE, 'greet', ['pthread'], activation)
        row = finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        denied(row)
        outcomes.append({'activation': activation, 'missingCapability': missing,
            'retirement': retire(client, probe, target, output, activation)})
    target = deploy(client, manifest, target['publication'], generation=str(target['generation']), grants=grants)
    controls = (
        ('pthread', 'pthread'), ('c11', 'c11'), ('mixed', 'mixed'), ('invalid', 'invalid'),
        ('pressure', 'pressure'), ('root-return', 'root-return'), ('application-error', 'application-error'),
        ('root-trap', 'root-trap'), ('fresh-root-trap', 'pthread'),
        ('callback-trap', 'callback-trap'), ('fresh-callback-trap', 'c11'),
        ('cancel', 'cancel'), ('fresh-cancel', 'mixed'),
        ('deadline', 'deadline'), ('fresh-deadline', 'pthread'))
    for label, mode in controls:
        outcomes.append(invoke(client, probe, target, output, mode, 'c-thread-' + label, cancel=mode == 'cancel'))
    require(len(outcomes) == 17, 'c-thread-original-seventeen-controls')
    for label, mode in (('sync-pthread', 'sync-pthread'), ('sync-mixed', 'sync-mixed'),
                        ('fresh-sync', 'pthread')):
        outcomes.append(invoke(client, probe, target, output, mode, 'c-thread-' + label))
    require(len(outcomes) == 20, 'c-thread-original-seventeen-and-three-synchronization-controls')
    return {'schemaVersion': 'latent.c.thread-runtime.v1', 'status': 'passed',
        'profile': PROFILE, 'runtimeLimits': dict(fixture.LIMITS), 'outcomes': outcomes,
        'originalSeventeenOutcomePrefix': 17,
        'pthreadAndMixedBasicSynchronizationQualified': True,
        'selectedRevision': selected_revision(client, target), 'full744Qualified': False,
        'mutexConditionVariablesQualified': False, 'compiledLoopCheckpointsQualified': False,
        'arbitraryStackPointerEscapeQualified': False, 'cppDynamicTlsQualified': False,
        'waitForPollPendingClaimed': False, 'nativeObserverChanged': False}


def run(artifact: Path, native: dict, output: Path):
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    before = {name: file_identity(path) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    record = {'schemaVersion': 'latent.c.thread-runtime.node.v1', 'status': 'incomplete',
              'native': before, 'component': component, 'full744Qualified': False}
    stage, primary = 'normal-single-component-signing', False
    try:
        signed = output / 'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'c-thread-one-original-component-signature')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-thread-runtime-') as temporary, \
                owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            peer, port = start_provider(client, work / 'peer', maximum_seconds=240)
            cleanup.callback(peer.close)
            config, settings = configure_base(work / 'node', signed, port, language='c')
            configure(settings, read_json(artifact / 'capsule.json'))
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            record['configuration'] = settings
            stage = 'normal-selected-c-node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-thread-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'c-thread-normal-signed-component-admission')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source / 'deployment.json', publication)
            stage = 'ordinary-c-thread-lifecycle'
            record['programme'] = programme(client, node, probe, source / 'deployment.json', target, output)
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'c-thread-after-deletes', 0)
            stop(client, node)
            record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = stop_observation_peer(peer)
            cancellation.check()
        require(before == {name: file_identity(path) for name, path in native.items()}
                and component == file_identity(artifact / 'component.wasm', 8 * 1024**2)
                and client.calls <= 384 and time.monotonic() < commands.deadline,
                'c-thread-final-native-component-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', stage=stage, qualification=False)
        raise
    finally:
        if primary:
            try:
                write_json(output / 'FAILED.json', record)
            except BaseException:
                pass


HTTP = 'latent:http/streaming@0.3.0'
HTTP_OPS = ['open', 'write', 'finish', 'read', 'chunk-bytes', 'trailers', 'abort-upload', 'abort-body']


def configure_http(settings, capsule, peer, credential):
    imports = capsule.get('imports')
    require(type(imports) is list and len(imports) == 3
            and all(type(row) is dict and set(row) == {'contract', 'optional'}
                    and row['optional'] is False for row in imports)
            and {row['contract'] for row in imports} == {*IMPORTS, HTTP}, 'c-libfetch-exact-imports')
    # Only the local validation projection omits HTTP; signed source stays intact.
    configure(settings, {**capsule, 'imports': [row for row in imports if row['contract'] != HTTP]})
    providers = settings['providers']
    del providers['http']
    providers['bindings'] = [row for row in providers['bindings'] if row['name'] != 'http-binding']
    providers['httpStreaming'] = {
        'identity': {'id': 'http-standard', 'tenant': 'examples', 'service': 'http-host', 'epoch': 1},
        'credentialDirectory': str(credential.parent),
        'credentials': [{'reference': 'standard-peer', 'file': credential.name,
                         'destination': 0, 'header': 'authorization'}],
        'configuration': {'formatVersion': 1, 'destinations': peer.provider_destinations(),
            'limits': {'maximumRequestBodyBytes': 4096, 'maximumResponseBodyBytes': 32768,
                'maximumEncodedResponseBytes': 65536, 'maximumHeaderBytes': 4096,
                'maximumHeaders': 16, 'maximumRedirects': 0}, 'extraRoots': [], 'publicRoots': False},
        'limits': {'maximumInputBytes': 4096, 'maximumOutputBytes': 32768,
                   'maximumChunkBytes': 16384, 'maximumOutstandingChunks': 2}}
    providers['bindings'].append({'name': 'http-standard', 'tenant': 'examples',
        'consumerService': 'examples/' + SERVICE, 'providerService': 'http-host',
        'contract': HTTP, 'providerBinding': 'http-installed'})
    require(len(providers['bindings']) == 3, 'c-libfetch-exact-required-bindings')
    return settings


def install_http(client, node, target, origin):
    from tools.static_api.node import policy
    grants = install(client, node, target)
    rows = [row for row in node.startup_record['providers'] if row['capability'] == HTTP]
    require(len(rows) == 1 and rows[0]['profile'] == 'bounded-streaming-http-identity-v1'
            and rows[0]['tenant'] == 'examples' and rows[0]['service'] == 'http-host'
            and rows[0]['configurationEpoch'] == '1', 'c-libfetch-installed-provider')
    descriptor = rows[0]
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': HTTP, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
        'id': 'ordinary-libfetch', 'effect': 'allow',
        'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
        'services': [target['service']], 'publications': [target['publication']],
        'capability': HTTP, 'operations': HTTP_OPS,
        'resources': {'kind': 'http', 'origins': [origin], 'methods': ['GET'],
                      'paths': [], 'pathPrefixes': ['/conformance/']},
        'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144, 'wallTimeMillis': 5000}}]})
    return grants + [{'capability': HTTP, 'policy': 'http-allow'}]


def start_http_call(client, target, text, activation):
    from tools.phase2_operator_process import Process
    path, budget = client.directory / (activation + '-input.json'), client.directory / (activation + '-budget.json')
    write_json(path, [text]); write_json(budget, target['budget'])
    process = Process([client.executable, '--output', 'json', '--config', str(client.config),
        '--profile', 'operator', '--rpc-timeout-ms', '5000', 'invoke', '--service', target['service'],
        '--route', target['name'], '--contract', fixture.HTTP_API, '--function', 'run',
        '--activation-id', activation, '--input', str(path), '--budget', str(budget), '--budget-profile', 'phase3'],
        client.directory, client.environment, client.cancellation, maximum=32768)
    process.authoring_activation = activation
    process.authoring_started_unix_millis = time.time_ns() // 1_000_000
    process.authoring_started = time.monotonic_ns()
    return process


def http_cell(client, node, probe, target, peer, output, case):
    from tools.standard_http.observations import validate, delta, require_zero_contact
    vectors = {'normal': 'domain-json', 'not-found': 'http-404', 'denied': 'denied-target',
               'early-close': 'partial-body', 'sibling': 'partial-body'}
    before, revision = peer.observation(), selected_revision(client, target)
    validate(before)
    text = case + '\n' + peer.url(vectors[case])
    if case == 'sibling':
        text += '\n' + peer.url('domain-json')
    activation = 'c-libfetch-' + case
    process, primary, barrier = start_http_call(client, target, text, activation), False, None
    deadline = min(client.deadline, time.monotonic() + 8)
    try:
        while not process.owner.exited():
            client.cancellation.check()
            require(time.monotonic() < deadline, 'c-libfetch-cell-deadline')
            process.drain()
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
            observed = peer.observation()
            validate(observed)
            change = delta(before, observed)
            # TCP acceptance precedes the peer's parsed request/vector observation.
            if (case == 'sibling' and barrier is None and len(change['requests']) >= 3
                    and change['startedRequests'] >= 3):
                requests = change['requests']
                require(len(requests) == 3
                        and [row.get('vector') for row in requests] == ['partial-body', 'domain-json', 'domain-json']
                        and requests[0]['state'] == 'held-body'
                        and requests[1].get('closeReason') == 'response-write-complete',
                        'c-libfetch-held-A-completed-B-third-contact')
                gates = peer.gates()
                require(len(gates) == 1 and gates[0].generation == observed['generation']
                        and gates[0].request == requests[0]['request'] and gates[0].phase == 'body',
                        'c-libfetch-original-unreleased-body-gate')
                physical = sample(client, probe, 'held-' + activation, 1, active=True)
                providers = usage(client, target, idle=False)
                counters = providers['nodeUsage']['counters']
                require(all(integer(counters[name]) >= 1 for name in
                    ('broker_calls', 'pool_active_connections', 'pool_running_requests'))
                    and not process.owner.exited(), 'c-libfetch-positive-held-provider-owners')
                barrier = {'peer': observed, 'physical': physical, 'providerUsage': providers,
                    'sourceBoundFirstFreadPending': True, 'nativePollPendingObserved': False,
                    'completedSiblingBeforeGateRelease': True}
                write_json(output / ('barrier-' + activation + '.json'), barrier)
                peer.release(gates[0])
        row = finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
                and row['response']['requestDispatched'] is True
                and row['response']['data']['resolvedRevision'] == revision,
                'c-libfetch-known-current-invocation')
        fixture.http_result(row, case)
        require(all(integer(row['response']['data']['consumption'][name]) == 0 for name in
                    ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes',
                     'logBytes', 'effectCount', 'childCalls')), 'c-libfetch-no-unrelated-authority')
        # Drive real remote FIN observation after the original provider closes.
        for _ in range(128):
            observed = peer.observation()
            if observed['openConnections'] == 0:
                break
            require(time.monotonic() < deadline, 'c-libfetch-peer-retirement-deadline')
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
        change = delta(before, peer.observation())
        if case == 'denied':
            require_zero_contact(before, peer.observation())
        else:
            expected = ['partial-body', 'domain-json', 'domain-json'] if case == 'sibling' else [vectors[case]]
            require([item.get('vector') for item in change['requests']] == expected
                    and all(item['method'] == 'GET' and item['role'] == 'primary'
                            and item.get('authorizationPresent') is True for item in change['requests'])
                    and change['rejectedRequests'] == change['connectionBoundRejections'] == 0,
                    'c-libfetch-exact-authenticated-peer-contacts')
        if case == 'early-close':
            events = change['events']
            require(any(event['kind'] == 'gate-pending' and event['phase'] == 'body' for event in events)
                    and not any(event['kind'] == 'gate-released' for event in events)
                    and len(change['requests']) == 1 and change['requests'][0]['state'] == 'closed',
                    'c-libfetch-close-before-unreleased-body')
        require(case != 'sibling' or barrier is not None, 'c-libfetch-sibling-barrier-required')
        require(peer.observation()['openConnections'] == 0, 'c-libfetch-no-peer-owners-left')
        write_json(output / ('peer-' + activation + '.json'), peer.observation())
        return {'case': case, 'activation': activation, 'exitCode': row['exitCode'],
                'barrier': barrier, 'peerDelta': change,
                'retirement': retire(client, probe, target, output, activation)}
    except BaseException:
        primary = True
        write_json(output / ('peer-failed-' + activation + '.json'), peer.observation())
        try:
            retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        close_call(process, primary_failure=primary)


def run_http(artifact: Path, native: dict, output: Path, *, deadline, runtime_profile=FETCH_PROFILE,
             client_kind='libfetch', client_state=None, client_deadline=None):
    import secrets
    from tools.standard_http.peer import Peer
    from tools.standard_http.observations import validate
    require(type(runtime_profile) is str and runtime_profile in (FETCH_PROFILE, FETCH_STANDARD_PROFILE),
            'c-http-exact-runtime-profile')
    expanded = runtime_profile == FETCH_STANDARD_PROFILE
    require(type(client_kind) is str and client_kind in ('libfetch', 'libucl', 'outside-card')
            and (expanded or client_kind == 'libfetch'), 'c-http-exact-client')
    is_libucl = client_kind == 'libucl'
    is_outside = client_kind == 'outside-card'
    if client_state is not None:
        require(expanded and type(client_state) is dict
                and set(client_state) == {'calls', 'controlAttempts', 'retainedBytes'}
                and all(type(value) is int and value >= 0 for value in client_state.values())
                and client_state['calls'] < 384 and client_state['controlAttempts'] < 384
                and client_state['retainedBytes'] < 4 * 1024**2, 'c-http-original-shared-client-budget')
        require(type(client_deadline) is float and time.monotonic() < client_deadline <= deadline,
                'c-http-original-shared-client-deadline')
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    before = {name: file_identity(path) for name, path in native.items()}
    require(deadline > time.monotonic(), 'c-libfetch-original-parent-deadline')
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    commands.deadline = min(commands.deadline, deadline)
    record = {'schemaVersion': 'latent.c.outside-card.node.v1' if is_outside else
                              'latent.c.libucl.node.v1' if is_libucl else 'latent.c.libfetch.node.v1',
              'status': 'incomplete',
              'component': component, 'native': before, 'full690Qualified': False,
              'fullCCostModelQualified': False, 'independentClientCount': 1}
    stage, failed = 'sign', False
    client = None
    budget_before = dict(client_state) if client_state is not None else None
    if expanded:
        record.update(runtimeProfile=runtime_profile, client=client_kind, independentClientCount=0)
    try:
        signed = output / 'signed'
        commands.run('libfetch-sign', native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'c-libfetch-one-signed-component')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-libfetch-') as temporary, \
                owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'credentials'):
                (work / name).mkdir(mode=0o700)
            secret = b'Bearer ' + secrets.token_hex(32).encode('ascii')
            credential = work / 'credentials/peer'
            credential.write_bytes(secret); credential.chmod(0o600)
            peer = Peer(secret, maximum_seconds=max(1, min(300, int(commands.deadline - time.monotonic()))))
            cleanup.callback(peer.close)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            if client_state is not None:
                client.deadline = min(client.deadline, client_deadline)
                client.calls = client_state['calls']
                client.control_attempts = client_state['controlAttempts']
                client.retained = client_state['retainedBytes']
            config, settings = configure_base(work / 'node', signed, peer.origin()['port'], language='c')
            if expanded:
                configure_libucl(settings, read_json(artifact / 'capsule.json'), peer, credential)
            else:
                configure_http(settings, read_json(artifact / 'capsule.json'), peer, credential)
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            # Private credentials and node configuration are intentionally not public artifacts.
            stage = 'node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-libfetch-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'c-libfetch-signed-admission')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source / 'deployment.json', publication)
            require(target['grants'] == [], 'c-libfetch-no-ambient-grants')
            grants = (install_libucl if expanded else install_http)(client, node, target, peer.origin())
            target = deploy(client, source / 'deployment.json', publication,
                            generation=str(target['generation']), grants=grants)
            stage = 'one-outside-captured-cell' if is_outside else 'five-ordinary-cells'
            record['cases'] = []
            cases = fixture.CARD_CASES if is_outside else fixture.LIBUCL_CASES if is_libucl else fixture.HTTP_CASES
            cell = libucl_cell if is_libucl or is_outside else http_cell
            for case in cases:
                record['cases'].append(cell(client, node, probe, target, peer, output, case,
                    **({'outside_library': True} if is_outside else {})))
            require([row['case'] for row in record['cases']] == list(cases)
                    and peer.observation()['startedRequests'] == (1 if is_outside else 2 if is_libucl else 6),
                    'c-libucl-five-cells-two-contacts' if is_libucl else 'c-libfetch-five-cells-six-contacts')
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'c-libfetch-after-deletes', 0)
            stop(client, node); record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = peer.close(); validate(record['peerShutdown'])
            require(record['peerShutdown']['openConnections'] == record['peerShutdown']['listeningOrigins'] == 0,
                    'c-libfetch-stopped-peer')
            cancellation.check()
        require(component == file_identity(artifact / 'component.wasm', 8 * 1024**2)
                and before == {name: file_identity(path) for name, path in native.items()}
                and time.monotonic() < commands.deadline and client.calls <= 384,
                'c-libfetch-final-original-inputs-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        if expanded:
            record['independentClientCount'] = 0 if is_outside else 1
        if client_state is not None:
            record['sharedClientBudget'] = {'before': budget_before,
                'after': {'calls': client.calls, 'controlAttempts': client.control_attempts,
                          'retainedBytes': client.retained}}
        write_json(output / 'qualified.json', record)
        return record
    except BaseException:
        failed = True
        record.update(status='failed', stage=stage)
        raise
    finally:
        if client_state is not None and client is not None:
            client_state.update(calls=client.calls, controlAttempts=client.control_attempts,
                                retainedBytes=client.retained)
        if failed:
            write_json(output / 'FAILED.json', record)


def configure_libucl(settings, capsule, peer, credential):
    """Select exactly the normal HTTP plus standard clock/entropy contracts."""
    from tools.c_guest.standard_facilities import IMPORTS as standard
    from tools.guest_runtime_profiles import profiles
    imports = capsule.get('imports')
    require(type(imports) is list and len(imports) == 6
            and all(type(row) is dict and set(row) == {'contract', 'optional'}
                    and row['optional'] is False for row in imports)
            and {row['contract'] for row in imports} == {*IMPORTS, HTTP, *standard},
            'c-libucl-exact-six-imports')
    # Validation projection only; the complete signed source remains unchanged.
    configure_http(settings, {**capsule, 'imports': [
        row for row in imports if row['contract'] not in standard]}, peer, credential)
    selected = profiles('c')
    providers = settings['providers']
    require({value[0] for value in selected.values()} == set(standard)
            and all(name not in providers for name in selected), 'c-libucl-fresh-standard-providers')
    for name, (contract, _, _, _) in selected.items():
        providers[name] = {'identity': {'id': name, 'tenant': 'examples',
                                       'service': 'runtime-host', 'epoch': 1}}
        providers['bindings'].append({'name': name + '-c-thread-runtime', 'tenant': 'examples',
            'consumerService': 'examples/' + SERVICE, 'providerService': 'runtime-host',
            'contract': contract, 'providerBinding': name + '-installed'})
    require(len(providers['bindings']) == 6, 'c-libucl-exact-six-bindings')
    return settings


def install_libucl(client, node, target, origin):
    from tools.guest_runtime_profiles import profiles
    from tools.static_api.node import policy
    grants = install_http(client, node, target, origin)
    for name, (capability, profile, operation, kind) in profiles('c').items():
        rows = [row for row in node.startup_record['providers'] if row['id'] == name]
        require(len(rows) == 1 and rows[0]['capability'] == capability
                and rows[0]['profile'] == profile and rows[0]['tenant'] == 'examples'
                and rows[0]['service'] == 'runtime-host' and rows[0]['configurationEpoch'] == '1',
                'c-libucl-original-standard-provider')
        descriptor = rows[0]
        policy(client, 'provider-binding', name + '-installed', {
            'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': [operation]}})
        policy(client, 'policy', name + '-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': capability, 'operations': [operation], 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 128 if kind == 'random' else 0,
                        'outputBytes': 65536, 'wallTimeMillis': 5000}}]})
        grants.append({'capability': capability, 'policy': name + '-allow'})
    require(len(grants) == 6, 'c-libucl-explicit-six-grants')
    return grants


def libucl_cell(client, node, probe, target, peer, output, case, *, outside_library=False):
    from tools.standard_http.observations import validate, delta, require_zero_contact
    require(type(outside_library) is bool
            and case in (fixture.CARD_CASES if outside_library else fixture.LIBUCL_CASES), 'c-libucl-closed-cell')
    vectors = {'normal': 'domain-json', 'not-found': 'http-404', 'denied': 'denied-target'}
    before, revision = peer.observation(), selected_revision(client, target)
    validate(before)
    text = ('' if outside_library else case + '\n') + (peer.url(vectors[case]) if case in vectors else '')
    activation = ('c-outside-card-' if outside_library else 'c-libucl-') + case
    process, primary = start_http_call(client, target, text, activation), False
    deadline = min(client.deadline, time.monotonic() + 8)
    try:
        while not process.owner.exited():
            client.cancellation.check()
            require(time.monotonic() < deadline, 'c-libucl-cell-deadline')
            process.drain()
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
        row = finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
                and row['response']['requestDispatched'] is True
                and row['response']['data']['resolvedRevision'] == revision,
                'c-libucl-known-current-invocation')
        (fixture.unseen_result if outside_library else fixture.libucl_result)(row, case)
        require(all(integer(row['response']['data']['consumption'][name]) == 0 for name in
            ('stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes',
             'logBytes', 'effectCount', 'childCalls')), 'c-libucl-no-unrelated-authority')
        for _ in range(128):
            observed = peer.observation()
            if observed['openConnections'] == 0:
                break
            require(time.monotonic() < deadline, 'c-libucl-peer-retirement-deadline')
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
        change = delta(before, peer.observation())
        if case in ('denied', 'file', 'glob'):
            require_zero_contact(before, peer.observation())
        else:
            require([item.get('vector') for item in change['requests']] == [vectors[case]]
                    and all(item['method'] == 'GET' and item['role'] == 'primary'
                            and item.get('authorizationPresent') is True for item in change['requests'])
                    and change['rejectedRequests'] == change['connectionBoundRejections'] == 0,
                    'c-libucl-exact-authenticated-peer-contact')
        require(peer.observation()['openConnections'] == 0 and not peer.gates(),
                'c-libucl-no-peer-owners-left')
        write_json(output / ('peer-' + activation + '.json'), peer.observation())
        return {'case': case, 'activation': activation, 'exitCode': row['exitCode'],
                'peerDelta': change, 'retirement': retire(client, probe, target, output, activation)}
    except BaseException:
        primary = True
        write_json(output / ('peer-failed-' + activation + '.json'), peer.observation())
        try:
            retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        close_call(process, primary_failure=primary)
