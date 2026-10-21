"""Eight finite outcomes; ordinary admission and real retirement remain authoritative."""
from contextlib import contextmanager
import json
from pathlib import Path
import re
import tempfile
import time

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import read_json, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_resource_tenants import signed_inputs, stop_observation_peer
from tools import resource_tenant_node as tenants
from tools.rust_capsule_node import RecordingClient, call, configure, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import fresh, write_json
from tools.sdk_explicit_fallback_fixture import CASES, LANGUAGES, expected
from tools.sdk_provider_scenario import close_failed_provider, start_provider

PHYSICAL = ('execution-cell-leases', 'guest-invocations', 'guest-stores',
    'guest-host-states', 'guest-component-instances')


@contextmanager
def owned_cleanup(close, record):
    failed = False
    try:
        yield
    except BaseException:
        failed = True
        raise
    finally:
        try:
            close()
        except BaseException:
            record['cleanupRefused'] = True
            if not failed:
                raise


def unsigned(value):
    require(type(value) is str and re.fullmatch(r'0|[1-9][0-9]{0,19}', value) is not None
        and int(value) <= 2**64 - 1, 'fallback-canonical-counter')
    return int(value)


def u32(value):
    require(type(value) is int and 0 <= value <= 2**32 - 1, 'fallback-json-u32-counter')
    return value


def consumption(value, budget):
    require(0 < unsigned(value['cpuFuel']) <= budget['cpuFuel']
        and 0 < unsigned(value['peakMemoryBytes']) <= budget['memoryBytes']
        and all(u32(value[key]) == 0 for key in ('outboundRequests', 'effectCount', 'childCalls'))
        and all(unsigned(value[key]) == 0 for key in ('logBytes', 'stateReadBytes', 'stateWriteBytes',
            'blobReadBytes', 'blobWriteBytes')), 'fallback-original-budgets-and-no-effects')


def outcome(language, row, seed, alternate):
    require(language in LANGUAGES and row['processReaped'] is True
        and row['response']['outcomeKnown'] is True, 'fallback-known-reaped-result')
    if alternate is None:
        require(row['exitCode'] == 4 and row['response']['error']['code'] == 'guest-trap'
            and row['response']['data']['terminalState'] == 'guest_trap', 'fallback-explicit-terminal-trap')
        return {'category': 'guest-trap', 'preciseInstructionCauseProved': False}
    require(row['exitCode'] == 0 and row['response']['data']['terminalState'] == 'completed'
        and row['decoded'] == expected(language, seed, alternate), 'fallback-native-refusal-and-real-alternate-required')
    return {'category': 'explicit-application-fallback', 'seed': seed, 'alternate': alternate,
        'nativeRefusal': 'ENOTSUP' if language == 'c' else 'errors.ErrUnsupported+ENOSYS52',
        'transparentFilesystemCompatibility': False}


def retirement(client, probe, target, output, name, population):
    physical = sample(client, probe, name, population)
    topology = physical['inventory']['topology']
    rows = {row['name']: row for row in topology['entries']}
    require(topology['available'] is True and topology['complete'] is True
        and len(rows) == len(topology['entries'])
        and all(name in rows and unsigned(rows[name]['activeCount']) == 0 for name in PHYSICAL),
        'fallback-five-physical-owners-retired')
    usage = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    counters = usage['nodeUsage']
    require(usage['nextPageToken'] is None and type(counters) is dict and counters['scope'] == 'node'
        and type(counters['unavailable']) is list and counters['unavailable'] == []
        and type(counters['counters']) is dict
        and all(key in counters['counters'] and unsigned(counters['counters'][key]) == 0 for key in ACTIVE_COUNTERS),
        'fallback-original-eighteen-provider-counters-idle')
    path = output / (name + '-retirement.json')
    write_json(path, {'physical': physical, 'providerUsage': usage})
    return file_identity(path)


def run(language, artifact, signed, binaries, output, deadline):
    require(language in LANGUAGES, 'fallback-node-language')
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 64 * 1024**2)
    capsule = read_json(artifact / 'capsule.json')
    imports = tenants.required_imports(capsule)
    require(language == 'go' or imports == [], 'fallback-c-original-pure-imports')
    release = signed_inputs(signed, component['sha256'])
    record = {'schemaVersion': 'latent.sdk.explicit-fallback.node.v1', 'status': 'incomplete',
        'language': language, 'component': component, 'release': release, 'cases': [],
        'filesystemGrantAdded': False, 'transparentFilesystemCompatibility': False,
        'oldProgrammeReplayed': False, 'fullTicketQualification': False}
    stage = 'normal-node-setup'
    try:
        with tempfile.TemporaryDirectory(prefix='lsf-explicit-fallback-') as temporary, owned_cancellation() as cancellation:
            work = Path(temporary)
            for name in ('node', 'examples', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(binaries['latent'], work / 'examples', cancellation,
                min(deadline, time.monotonic() + 180), evidence=output / 'controls',
                invocation_timeout_millis=5000 if language == 'c' else 120000)
            peer, port = start_provider(client, work / 'peer', maximum_seconds=180)
            with owned_cleanup(lambda: peer.close() if 'peerShutdown' in record else close_failed_provider(peer), record):
                config, settings = configure(work / 'node', signed, port, language=language)
                tenants.configure(settings, capsule, language)
                config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
                record['configurationIdentity'] = file_identity(config)
                stage = 'normal-node-startup'
                node = connect(client, binaries['latentd'], work / 'node', config, 'examples', 0)
                with owned_cleanup(node.close, record):
                    record['startup'] = node.startup_record
                    probe = Probe(node, file_identity(binaries['latentd'], 512 * 1024**2))
                    stage = 'normal-publication-and-explicit-runtime-grants'
                    source = signed / 'my-greeting'
                    published = client.call('release', 'publish-package', source / 'package',
                        '--evidence', source / 'evidence/index.json', '--operation-id', 'fallback-publish',
                        '--expected-generation', '0')
                    require(published['outcomeKnown'] is True
                        and published['data']['release']['digest'] == component['sha256'], 'fallback-original-publication')
                    publication = published['data']['operation']['publication']['id']
                    manifest = client.directory / 'deployment.json'
                    write_json(manifest, tenants.scoped_deployment(read_json(source / 'deployment.json'), 'examples'))
                    target = deploy(client, manifest, publication)
                    target = tenants.install_grants(client, node, manifest, publication, target, imports, language, 'examples')
                    require(all(row['capability'] in tenants.PROFILES for row in target['grants']),
                        'fallback-no-filesystem-grant')
                    record['publication'] = publication
                    for index, (mode, seed, alternate) in enumerate(CASES):
                        name = f'fallback-{language}-{index}'
                        stage = name
                        pin = selected_revision(client, target)
                        row = call(client, target, 'greeting', 'greet', [f'fallback:{mode}:{seed}'], name)
                        # The raw invocation and real owner observations survive any oracle refusal.
                        physical = retirement(client, probe, target, output, name, 1)
                        item = {'name': name, 'invocation': file_identity(client.evidence / (name + '.json')),
                            'retirement': physical, 'seed': seed, 'expectedAlternate': alternate}
                        record['cases'].append(item)
                        require(pin['releaseDigest'] == component['sha256']
                            and row['response']['data']['resolvedRevision'] == pin, 'fallback-exact-current-revision')
                        consumption(row['response']['data']['consumption'], target['budget'])
                        item['observation'] = outcome(language, row, seed, alternate)
                        write_json(output / (name + '-case.json'), item)
                    delete_all(client, [target['name']])
                    file_identity_after_delete = output / 'after-delete.json'
                    write_json(file_identity_after_delete, sample(client, probe, 'after-fallback-delete', 0))
                    record['afterDelete'] = file_identity(file_identity_after_delete)
                    stop(client, node)
                    record['nodeShutdown'] = stopped_record(node)
                    client.node = None
                    record['peerShutdown'] = stop_observation_peer(peer)
                    require(client.calls <= 384 and record['nodeShutdown']['reaped'] is True
                        and record['nodeShutdown']['record']['clean'] is True, 'fallback-clean-reaped-bounded-node')
                    record['cliCalls'] = client.calls
            cancellation.check()
        require(len(record['cases']) == 4 and time.monotonic() < deadline, 'fallback-four-complete-original-budget-cases')
        record['status'] = 'passed'
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise
