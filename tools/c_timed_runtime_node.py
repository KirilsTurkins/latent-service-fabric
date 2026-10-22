"""Finite signed timer extension; original lifecycle protocol and caps retained."""
from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import tempfile
import time

from tools import c_thread_runtime_node as original
from tools import c_timed_runtime_fixture as fixture
from tools import c_thread_runtime_fixture as original_fixture
from tools.c_guest.threading import PROFILE
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import require, write_json, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure as configure_base, delete_all, deploy, sample, selected_revision, start_call
from tools.rust_capsule_project import ROOT, fresh, read_json
from tools.sdk_provider_scenario import start_provider

SERVICE = original.SERVICE
PROVIDERS = dict(original.PROVIDERS)
PROVIDERS[original.ACTIVATION] = ('c-activation', 'activation-owned-v1',
    ['register', 'park', 'wake', 'settle', 'observe', 'timer-start', 'timer-next', 'timer-stop'], 'clock')
for name, (contract, profile, operation, kind) in profiles('c').items():
    PROVIDERS[contract] = (name, profile, [operation], kind)
owned_cleanup = original.owned_cleanup


def configure(settings, capsule):
    require(type(capsule.get('imports')) is list and len(capsule['imports']) == 5
        and all(type(row) is dict and set(row) == {'contract', 'optional'} and row['optional'] is False
            for row in capsule['imports'])
        and {row['contract'] for row in capsule['imports']} == set(fixture.IMPORTS),
        'c-timed-five-explicit-imports')
    projected = dict(capsule, imports=[row for row in capsule['imports']
        if row['contract'] in original.IMPORTS])
    original.configure(settings, projected)
    for name, (contract, _, _, _) in profiles('c').items():
        settings['providers'][name] = {'identity': {'id': name, 'tenant': 'examples', 'service': 'c-runtime-host', 'epoch': 1}}
        settings['providers']['bindings'].append({'name': name, 'tenant': 'examples',
            'consumerService': 'examples/' + SERVICE, 'providerService': 'c-runtime-host',
            'contract': contract, 'providerBinding': name + '-installed'})
    require(len(settings['providers']['bindings']) == 6, 'c-timed-original-plus-five-bindings')
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
            'ceiling': {'operations': 4096, 'inputBytes': 8 if resource == 'random' else 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result = client.call('policy', 'apply', '--id', identity + '-allow', '--file', policy,
            '--operation-id', 'allow-' + identity, '--expected-generation', '0')
        require(result['outcomeKnown'] is True, 'c-thread-known-policy')
        grants.append({'capability': capability, 'policy': identity + '-allow'})
    return grants


def invoke_timed(client, probe, target, output, mode, activation):
    revision = selected_revision(client, target)
    process = start_call(client, target, SERVICE, 'greet', [mode], activation)
    primary = False
    try:
        row = original.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
            and row['response']['requestDispatched'] is True
            and row['response']['data']['resolvedRevision'] == revision,
            'c-timed-known-reaped-current-invocation')
        require(all(original.integer(row['response']['data']['consumption'][name]) == 0 for name in
            ('outboundRequests', 'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes',
             'logBytes', 'effectCount', 'childCalls')), 'c-timed-no-other-authority-used')
        require(row['exitCode'] == 0 and type(row['decoded']) is list and len(row['decoded']) == 1
            and set(row['decoded'][0]) == {'ok'}, 'c-timed-ordinary-success')
        witness = fixture.observation(row['decoded'][0]['ok'], mode)
        return {'activation': activation, 'mode': mode, 'exitCode': row['exitCode'], 'witness': witness,
            'retirement': original.retire(client, probe, target, output, activation)}
    except BaseException:
        primary = True
        try:
            original.retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        original.close_call(process, primary_failure=primary)


def programme(client, node, probe, manifest, target, output):
    require(target['grants'] == [], 'c-thread-no-default-authority')
    grants = install(client, node, target)
    outcomes = []
    for index, missing in enumerate(original.IMPORTS):
        target = deploy(client, manifest, target['publication'], generation=str(target['generation']),
                        grants=[row for row in grants if row['capability'] != missing])
        activation = 'c-thread-authority-' + str(index)
        process = start_call(client, target, SERVICE, 'greet', ['pthread'], activation)
        row = original.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        original.denied(row)
        outcomes.append({'activation': activation, 'missingCapability': missing,
            'retirement': original.retire(client, probe, target, output, activation)})
    target = deploy(client, manifest, target['publication'], generation=str(target['generation']), grants=grants)
    controls = (
        ('pthread', 'pthread'), ('c11', 'c11'), ('mixed', 'mixed'), ('invalid', 'invalid'),
        ('pressure', 'pressure'), ('root-return', 'root-return'), ('application-error', 'application-error'),
        ('root-trap', 'root-trap'), ('fresh-root-trap', 'pthread'),
        ('callback-trap', 'callback-trap'), ('fresh-callback-trap', 'c11'),
        ('cancel', 'cancel'), ('fresh-cancel', 'mixed'),
        ('deadline', 'deadline'), ('fresh-deadline', 'pthread'))
    for label, mode in controls:
        outcomes.append(original.invoke(client, probe, target, output, mode, 'c-thread-' + label, cancel=mode == 'cancel'))
    require(len(outcomes) == 17, 'c-thread-original-seventeen-controls')
    for label, mode in (('sync-pthread', 'sync-pthread'), ('sync-mixed', 'sync-mixed'),
                        ('fresh-sync', 'pthread')):
        outcomes.append(original.invoke(client, probe, target, output, mode, 'c-thread-' + label))
    require(len(outcomes) == 20, 'c-thread-original-seventeen-and-three-synchronization-controls')
    for mode in fixture.MODES:
        outcomes.append(invoke_timed(client, probe, target, output, mode, 'c-thread-' + mode))
    for index, missing in enumerate(fixture.IMPORTS[2:]):
        target = deploy(client, manifest, target['publication'], generation=str(target['generation']),
            grants=[row for row in grants if row['capability'] != missing])
        activation = 'c-timed-authority-' + str(index)
        process = start_call(client, target, SERVICE, 'greet', ['timed-sleep'], activation)
        row = original.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        original.denied(row)
        outcomes.append({'activation': activation, 'missingCapability': missing,
            'retirement': original.retire(client, probe, target, output, activation)})
    target = deploy(client, manifest, target['publication'], generation=str(target['generation']), grants=grants)
    outcomes.append(invoke_timed(client, probe, target, output, 'timed-sleep-c11', 'c-thread-fresh-timed'))
    require(len(outcomes) == 36, 'c-timed-original-twenty-plus-sixteen-outcomes')
    return {'schemaVersion': 'latent.c.thread-runtime.v1', 'status': 'passed',
        'profile': PROFILE, 'runtimeLimits': dict(original_fixture.LIMITS), 'outcomes': outcomes,
        'originalSeventeenOutcomePrefix': 17, 'originalTwentyOutcomePrefix': 20,
        'finiteTimedMutexConditionAndSleepQualified': True, 'recurringCallbacksQualified': False,
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
