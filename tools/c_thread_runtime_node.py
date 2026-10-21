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
from tools.phase2_operator_process import require, write_json
from tools.phase2_operator_process import stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.qualify_resource_tenants import stop_observation_peer
from tools.resource_runtime_node import LIVE, integer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, configure as configure_base, delete_all,
    deploy, sample, selected_revision, start_call, MEDIA)
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.sdk_provider_scenario import start_provider

ACTIVATION, NATIVE = IMPORTS
SERVICE = 'c-thread-runtime'
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


def child_entry(inventory, pages, activation, *, expected_revision):
    topology = inventory['topology']
    require(topology['available'] is True and topology['complete'] is True, 'c-thread-live-topology')
    rows = {row['name']: row for row in topology['entries']}
    require(len(rows) == len(topology['entries']) and set(LIVE) <= rows.keys(), 'c-thread-five-live-rows')
    if any(integer(rows[name]['activeCount']) != 1 for name in LIVE):
        return None
    require(type(pages) is list and 0 < len(pages) <= 4, 'c-thread-audit-page-bound')
    require(pages[-1]['data']['page']['nextPageToken'] is None, 'c-thread-audit-complete')
    observed, seen, epochs = {}, set(), set()
    for page in pages:
        require(page['category'] == 'success' and page['outcomeKnown'] is True
                and integer(page['data']['coverage']['droppedObservations']) == 0,
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
    return {'activation': activation, 'nativeStartCompletedSequence': starts[0],
        'childObserveCompletedSequence': entered[0], 'physicalOwners': {name: 1 for name in LIVE},
        'sourceBoundChildEntry': True, 'typedObserveSuccessClaimed': False, 'waitForPollPendingClaimed': False}


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
            token = page['data']['page']['nextPageToken']
            if token is None:
                break
        inventory = client.call('node', 'get', 'operator-workflow-test')['data']['inventory']
        witness = child_entry(inventory, pages, process.authoring_activation, expected_revision=revision)
        if witness is not None:
            physical = sample(client, probe, 'entered-' + process.authoring_activation, 1, active=True)
            value = {'witness': witness, 'inventory': inventory, 'auditPages': pages,
                     'providerUsage': usage(client, target, idle=False), 'physical': physical}
            require(not process.owner.exited(), 'c-thread-child-ended-before-physical-witness')
            write_json(output / ('child-' + process.authoring_activation + '.json'), value)
            return witness
        process.drain()
    raise ValueError('c-thread-child-entry-not-observed')


def invoke(client, probe, target, output, mode, activation, *, cancel=False):
    revision = selected_revision(client, target)
    # Clip the deadline request below the unchanged five-second guest ceiling,
    # so its actual terminal receipt can arrive within the original CLI wait.
    process = start_call(client, target, SERVICE, 'greet', [mode], activation,
                         wall=3000 if mode == 'deadline' else None)
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
            children = {'mixed': 2, 'pressure': 3}.get(mode, 1)
            witness = fixture.observation(row['decoded'][0]['ok'], children)
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
    return {'schemaVersion': 'latent.c.thread-runtime.v1', 'status': 'passed',
        'profile': PROFILE, 'runtimeLimits': dict(fixture.LIMITS), 'outcomes': outcomes,
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
