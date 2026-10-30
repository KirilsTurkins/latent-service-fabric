"""Five finite signed calls of the authentic retained default ThreadPool guest.

This selects Rust40 explicitly. Source/compiler controls do not count as guest
progress; only the ordinary CLI result and physical retirement can pass here.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import json
from pathlib import Path
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS, integer
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, configure as configure_base, delete_all,
    deploy, finish_call, sample, selected_revision, start_call)
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.rust_thread_runtime_package import IMPORTS, PROFILE, RUN, SOURCE, WRAPPED
from tools.sdk_provider_scenario import start_provider

SERVICE = 'ordinary-thread-inputs'
HOST = 'rust-thread-runtime-host'
CLOCK_HOST = 'rust-thread-clock-host'
LIMITS = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
          'timers': 8, 'results': 8, 'nativeOwners': 8}
PROVIDERS = {
    IMPORTS[0]: ('rust-activation', 'activation-owned-v1',
        ['register', 'park', 'wake', 'settle', 'observe', 'timer-start', 'timer-next', 'timer-stop'], 'clock'),
    IMPORTS[1]: ('rust-native', 'conservative-native-total-starts-v1', ['start'], 'context'),
    IMPORTS[2]: ('clockMonotonic', 'activation-monotonic-v1', ['now-nanos'], 'clock'),
}
CASES = (('pools', 'pools-cold', 0, 'ordinary-default-pools:42'),
         ('pools', 'pools-hot', 0, 'ordinary-default-pools:42'),
         ('  ', 'declared-error', 3, 'Please enter a name.'),
         ('  Ada  ', 'after-error', 0, 'Hello, Ada!'),
         ('pools', 'pools-after-error', 0, 'ordinary-default-pools:42'))


def configure(settings, capsule):
    imports = capsule.get('imports')
    require(type(imports) is list and len(imports) == 3
            and all(type(row) is dict and set(row) == {'contract', 'optional'}
                    and row['optional'] is False for row in imports)
            and {row['contract'] for row in imports} == set(IMPORTS),
            'rust-thread-three-actual-component-imports')
    require(capsule['execution']['threading'] == 'cooperative'
            and capsule['execution']['limits']['memoryBytes'] == 32 * 1024 * 1024
            and capsule['execution']['limits']['wallTimeLimitMillis'] == 5000,
            'rust-thread-explicit-signed-qualification-envelope')
    require(settings['workers'] == {'runtime': 1, 'control': 1}
            and len(settings['cells']) == 1 and settings['cells'][0]['capacity'] == 1
            and settings['cells'][0]['queueCapacity'] == 2
            and settings['cells'][0]['maximumMemoryBytes'] >= 32 * 1024 * 1024,
            'rust-thread-original-one-cell-envelope')
    settings.setdefault('engine', {})['threadingProfile'] = PROFILE
    providers = settings['providers']
    require(len(providers['bindings']) == 1
            and not any(name in providers for name in ('activationRuntime', 'clockMonotonic', 'clockWall')),
            'rust-thread-unmodified-provider-base')
    providers['activationRuntime'] = {'identity': {'id': 'rust-activation', 'tenant': 'examples',
        'service': HOST, 'epoch': 1}, 'limits': dict(LIMITS), 'nativeThreads': True}
    for name in ('clockMonotonic',):
        providers[name] = {'identity': {'id': name, 'tenant': 'examples', 'service': CLOCK_HOST, 'epoch': 1}}
    for capability, (identity, _, _, _) in PROVIDERS.items():
        providers['bindings'].append({'name': identity, 'tenant': 'examples',
            'consumerService': 'examples/' + SERVICE,
            'providerService': HOST if capability in IMPORTS[:2] else CLOCK_HOST,
            'contract': capability, 'providerBinding': identity + '-installed'})
    require(len(providers['bindings']) == 4, 'rust-thread-original-plus-three-bindings')
    return settings


def install(client, node, target):
    grants = []
    for capability, (identity, profile, operations, resource) in PROVIDERS.items():
        rows = [row for row in node.startup_record['providers'] if row['capability'] == capability]
        expected_service = HOST if capability in IMPORTS[:2] else CLOCK_HOST
        require(len(rows) == 1 and rows[0]['tenant'] == 'examples' and rows[0]['service'] == expected_service
                and rows[0]['profile'] == profile and rows[0]['configurationEpoch'] == '1',
                'rust-thread-exact-installed-provider-descriptor')
        descriptor = rows[0]
        binding = client.directory / (identity + '-binding.json')
        write_json(binding, {'formatVersion': 1, 'tenant': 'examples', 'capability': capability,
            'providerProfile': profile, 'configurationDigest': descriptor['configurationDigest'],
            'configurationEpoch': 1, 'restriction': {'operations': operations}})
        result = client.call('policy', '--kind', 'provider-binding', 'apply', '--id', identity + '-installed',
            '--file', binding, '--operation-id', 'install-' + identity, '--expected-generation', '0')
        require(result['outcomeKnown'] is True, 'rust-thread-known-installed-binding')
        policy = client.directory / (identity + '-policy.json')
        write_json(policy, {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'ordinary-rust', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': capability, 'operations': operations, 'resources': {'kind': resource},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result = client.call('policy', 'apply', '--id', identity + '-allow', '--file', policy,
            '--operation-id', 'allow-' + identity, '--expected-generation', '0')
        require(result['outcomeKnown'] is True, 'rust-thread-known-explicit-policy')
        grants.append({'capability': capability, 'policy': identity + '-allow'})
    return grants


def idle(client, target):
    value = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    usage = value['nodeUsage']
    require(value['nextPageToken'] is None and type(usage) is dict and usage['scope'] == 'node'
            and usage['unavailable'] == [] and type(usage['counters']) is dict
            and set(ACTIVE_COUNTERS) <= usage['counters'].keys()
            and all(integer(usage['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
            'rust-thread-all-eighteen-original-provider-owners-retired')
    return usage


@contextmanager
def cleanup_owner(record):
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


def run(artifact: Path, native: dict, output: Path, *, diagnostic=False):
    require(type(diagnostic) is bool, 'rust-thread-explicit-diagnostic-mode')
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 2 * 1024 * 1024)
    require(component == WRAPPED, 'rust-thread-exact-retained-component-not-caller-selected')
    before = {name: file_identity(path) for name, path in native.items()}
    projection = read_json(artifact / 'qualification-projection.json', 65536)
    require(projection['componentDigest'] == component['sha256']
            and projection['selectedHostProfile'] == PROFILE
            and projection['compilerSource'] == SOURCE and projection['compilerRun'] == str(RUN)
            and projection['applicationRecompiled'] is False,
            'rust-thread-explicit-original-compiler-projection')
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    record = {'schemaVersion': 'latent.rust.thread-runtime.node.v1', 'status': 'incomplete',
              'native': before, 'component': component, 'projection': projection,
              'full743Qualified': False, 'checkpointQualified': False, 'privateGraphRuntimeQualified': False,
              'diagnosticMode': diagnostic, 'diagnosticRuntimeQualification': False}
    stage, primary = 'normal-single-component-signing', False
    try:
        signed = output / 'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'rust-thread-one-retained-component-signature')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-rust-thread-runtime-') as temporary, \
                cleanup_owner(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            peer, port = start_provider(client, work / 'peer', maximum_seconds=240)
            cleanup.callback(peer.close)
            config, settings = configure_base(work / 'node', signed, port, language='rust')
            configure(settings, read_json(artifact / 'capsule.json'))
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            record['configuration'] = settings
            stage = 'normal-selected-rust40-node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'rust-thread-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'rust-thread-original-signed-component-publication')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source / 'deployment.json', publication)
            grants = install(client, node, target)
            target = deploy(client, source / 'deployment.json', publication,
                            generation=str(target['generation']), grants=grants)
            revision = selected_revision(client, target)
            record['programme'] = []
            for argument, activation, code, result in CASES:
                stage = 'ordinary-default-threadpool-' + activation
                row = finish_call(client, start_call(client, target, 'greeting', 'greet', [argument], activation))
                write_json(output / ('invocation-' + activation + '.json'), row)
                require(row['processReaped'] is True and row['response']['outcomeKnown'] is True
                        and row['response']['requestDispatched'] is True
                        and row['response']['data']['resolvedRevision'] == revision
                        and revision['releaseDigest'] == component['sha256'],
                        'rust-thread-reaped-known-current-signed-invocation')
                matched = row['exitCode'] == code and row['decoded'] == [{'err' if code else 'ok': result}]
                if not matched:
                    if diagnostic:
                        # Only the owning diagnostic programme binds the new
                        # host identity. A stderr prefix alone authenticates
                        # nothing in the ordinary default consumer.
                        from tools.rust_thread_fault_frames import capture as fault_capture
                        try:
                            fault_capture(node, before['latentd'], component, output)
                        except BaseException:
                            record['numericFaultDiagnosticRefused'] = True
                        diagnostic_frames = output / 'numeric-fault-frames.json'
                        details = row['response'].get('error', {}).get('details', [])
                        require(row['exitCode'] == 4 and row['decoded'] is None
                                and row['response']['data']['terminalState'] == 'guest_trap'
                                and any(item.get('kind') == 'activation.guest-trap-kind'
                                    and item.get('fields') == {'kind': 'unreachable-code'}
                                    for item in details)
                                and diagnostic_frames.is_file(),
                                'rust-thread-exact-numeric-original-fault-observation')
                        consumption = row['response']['data']['consumption']
                        require(0 < integer(consumption['cpuFuel']) <= 100000000
                                and 0 < integer(consumption['peakMemoryBytes']) <= 32 * 1024 * 1024
                                and all(integer(consumption[name]) == 0 for name in (
                                    'outboundRequests', 'stateReadBytes', 'stateWriteBytes',
                                    'blobReadBytes', 'blobWriteBytes', 'logBytes', 'effectCount',
                                    'childCalls')), 'rust-thread-finite-numeric-fault-only')
                        record.update(status='diagnostic-fault-observed', qualification=False,
                            actualDefaultThreadPoolProgress=False, diagnosticFaultObserved=True,
                            diagnosticFaultFrames=file_identity(diagnostic_frames, 64 * 1024),
                            cliCalls=client.calls, commands=commands.records)
                        write_json(output / 'diagnostic-fault.json', record)
                        return record
                    from tools.capsule_invocation_diagnostics import capture
                    capture(client, row)
                require(matched, 'rust-thread-exact-original-default-pool-or-error-result')
                consumption = row['response']['data']['consumption']
                require(0 < integer(consumption['cpuFuel']) <= 100000000
                        and 0 < integer(consumption['peakMemoryBytes']) <= 32 * 1024 * 1024
                        and all(integer(consumption[name]) == 0 for name in ('outboundRequests',
                            'stateReadBytes', 'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes',
                            'logBytes', 'effectCount', 'childCalls')), 'rust-thread-finite-owned-runtime-only')
                retirement = {'physical': sample(client, probe, 'after-' + activation, 1),
                              'providerUsage': idle(client, target)}
                write_json(output / ('retirement-' + activation + '.json'), retirement)
                record['programme'].append({'activation': activation, 'argument': argument,
                    'typedResult': row['decoded'], 'physicalRetirementObserved': True})
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'rust-thread-after-deletes', 0)
            stop(client, node)
            record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = stop_observation_peer(peer)
            cancellation.check()
        require(before == {name: file_identity(path) for name, path in native.items()}
                and component == file_identity(artifact / 'component.wasm', 2 * 1024 * 1024)
                and client.calls <= 192 and time.monotonic() < commands.deadline,
                'rust-thread-final-native-component-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records,
                      actualDefaultThreadPoolProgress=True, independentQueuesProgress=True)
        write_json(output / ('diagnostic-completed.json' if diagnostic else 'qualified.json'), record)
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
