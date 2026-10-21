"""Actual finite managed owner refusals and physical retirement on frozen native6fd."""
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools import dotnet_standard_http_node as base, dotnet_http_mixed_node as shared
from tools.dotnet_managed_capacity_fixture import CASES, LIMITS
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_http_mixed_node import retain_partial
from tools.java_http_release_preparation import prepare
from tools.java_http_tenant_node import cleanup_owner
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, sample, start_call, finish_call, selected_revision
from tools.rust_capsule_project import fresh, read_json, write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer

EXPECTED = ('tasks:7:refused:7-finally:fresh', 'queue:2:refused:rollback:2-finally:fresh', None,
    'periodic:2:context:disposed:fresh', 'disposed-before-dispatch:0:fresh',
    'closing-timer:accepted', 'native-ledger:2:typed-refusal:settled:fresh',
    'fresh:task:queue:timer:native-table')


def configuration(directory, releases, peer, credential, native_limit):
    require(type(native_limit) is int and native_limit in (0, 1, 2), 'capacity-closed-native-profile')
    path = base.configuration(directory, releases, {'origins': peer.observation()['origins'],
        'destinations': peer.provider_destinations()}, credential)
    value = read_json(path)
    original = {'tasks': 8, 'executors': 2, 'queuedWork': 8, 'waits': 16,
        'timers': 8, 'results': 8, 'nativeOwners': 8}
    require(value['providers']['activationRuntime']['limits'] == original, 'capacity-original-owner-ceilings')
    selected = {**LIMITS, 'nativeOwners': native_limit}
    require(set(selected) == set(original) and all(0 <= selected[key] <= original[key] for key in original),
        'capacity-no-increased-ceiling')
    value['providers']['activationRuntime']['limits'] = selected
    path.write_text(json.dumps(value, indent=2)+'\n', encoding='utf8')
    return path


def timers(text):
    parts = text.split(':')
    require(len(parts) == 8 and parts[:2] == ['1', 'timers'] and parts[-3:] == ['refused', 'reused', 'fresh'],
        'capacity-timer-result-shape')
    count = shared.natural(parts[2]); require(count in (7, 8), 'capacity-distinct-timer-count')
    births, drops = ([shared.natural(item) for item in value.split(',')] for value in parts[3:5])
    require(len(births) == len(drops) == count and births[-1] == 8 and births[0] == 9-count
        and births == list(range(births[0], 9)), 'capacity-individual-timer-births')
    previous = 8
    for index, after in enumerate(drops):
        require(after + 1 == previous or (index == count-1 and after + 2 == previous),
            'capacity-individual-timer-returns')
        previous = after
    require(previous <= 1, 'capacity-logical-timers-still-owned')
    return {'individualTimers': count, 'birthCounts': births, 'returnCounts': drops,
        'coalescedDriverCountedSeparately': True}


def checked(row, mode, revision, budget, *, installation_refusal=False):
    response = row['response']; require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data'].get('resolvedRevision') == revision, 'capacity-exact-result-identity')
    if installation_refusal:
        require(mode == 7 and row['exitCode'] == 4 and response['category'] == 'platform-failure'
            and response['error']['code'] == 'guest-trap', 'capacity-zero-native-must-refuse')
        detail = {'scope': 'source-bound-production-registry-native-lease-refusal-before-application-entry',
            'originalManagedExceptionTransported': False, 'diagnosticCauseIndependentlyTyped': False}
    else:
        require(type(mode) is int and 0 <= mode < len(EXPECTED) and row['exitCode'] == 0
            and response['category'] == 'success'
            and type(row['decoded']) is list and len(row['decoded']) == 1, 'capacity-managed-result')
        detail = timers(row['decoded'][0]) if mode == 2 else None
        if mode != 2:require(row['decoded'] == ['1:'+EXPECTED[mode]], 'capacity-original-capacity-oracle')
    used = response['data']['consumption']
    require(shared.natural(used['outboundRequests']) == (1 if mode == 5 and not installation_refusal else 0)
        and 0 < shared.natural(used['cpuFuel']) <= shared.natural(budget['cpuFuel']) <= 1000000000
        and 0 < shared.natural(used['peakMemoryBytes']) <= shared.natural(budget['memoryBytes']) <= 134217728,
        'capacity-original-execution-budgets')
    return detail


def invoke(client, node, target, peer, probe, mode, label, *, installation_refusal=False):
    revision = selected_revision(client, target); offset = len(peer.observation()['requests'])
    process = start_call(client, target, 'dotnet-standard-http', 'run', [mode, shared.endpoint(peer)], label)
    failed = False
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'capacity-invocation-deadline')
            process.drain(); node.drain(); peer.poll(.005)
            require(peer.observation()['failure'] is None, 'capacity-peer-failed')
        row = finish_call(client, process)
        write_json(client.evidence/(label+'-result.json'), row)
    except BaseException:
        failed = True
        retain_partial(client, process, peer, label, 'capacity-result', None, None, None, False)
        raise
    finally:
        try:process.close()
        except BaseException:
            try:write_json(client.evidence/(label+'-cleanup-refusal.json'), {'qualification': False, 'processCleanupConfirmed': False})
            except BaseException:pass
            if not failed:raise
    detail = checked(row, mode, revision, target['budget'], installation_refusal=installation_refusal)
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0:break
    observed = peer.observation(); validate_peer(observed)
    expected = 1 if mode == 5 and not installation_refusal else 0
    require(observed['openConnections'] == 0 and len(observed['requests'])-offset == expected,
        'capacity-exact-contact-retirement')
    if expected:
        marker = b'capacity:closing-timer-finally'
        request, = observed['requests'][offset:]
        require(request['method'] == 'POST' and request['bodyBytes'] == len(marker)
            and request['bodySha256'] == 'sha256:'+hashlib.sha256(marker).hexdigest()
            and request['closeReason'] == 'response-write-complete', 'capacity-closing-descendant-finally')
    physical = sample(client, probe, 'after-'+label, 1)
    usage = shared.usage(client, target)
    require(all(shared.natural(usage['counters'][key]) == 0 for key in ACTIVE_COUNTERS), 'capacity-physical-owners-remain')
    value = {'case': label, 'mode': mode, 'result': row, 'peer': observed,
        'physical': physical, 'providerUsage': usage, 'capacityDetail': detail,
        'installationRefusal': installation_refusal, 'expectedRevision': revision,
        'rawNativeLedgerProbe': mode == 6, 'ordinaryNativeMemoryAllocationQualified': False}
    path = client.evidence/(label+'-case.json'); write_json(path, value)
    return {'case': label, 'receipt': {'path': 'controls/'+path.name, **file_identity(path, 1024**2)}}


def run(artifact, native, output, *, deadline):
    output = fresh(output); original = shared.identities(artifact)
    products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    record = {'schemaVersion': 'latent.dotnet.managed-capacity-node.v1', 'status': 'in-progress',
        'originalBuild': original, 'nativeProducts': products, 'profiles': [], 'cases': [],
        'nativeMemoryAllocationQualified': False, 'postRetiredStoreCallbackQualified': False}
    stage = 'normal-signing'
    try:
        signed = output/'releases'
        result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(result.returncode == 0, 'capacity-normal-signing')
        for native_limit in (2, 0, 1):
            profile = output/('native-'+str(native_limit)); profile.mkdir()
            with tempfile.TemporaryDirectory(prefix='lsf-dotnet-capacity-') as temporary, \
                    owned_cancellation() as cancellation, ExitStack() as cleanup:
                work = Path(temporary)
                for name in ('client', 'node', 'credentials'):(work/name).mkdir(mode=0o700)
                secret = ('Bearer '+secrets.token_hex(32)).encode('ascii')
                credential = work/'credentials'/'main'; credential.write_bytes(secret); credential.chmod(0o600)
                peer = Peer(secret, maximum_seconds=300); cleanup_owner(cleanup, peer, record, 'peer-'+str(native_limit))
                client = RecordingClient(native['latent'], work/'client', cancellation,
                    min(deadline, time.monotonic()+300), evidence=profile/'controls',
                    invocation_timeout_millis=120000, control_timeout_millis=15000)
                config = configuration(work/'node', signed, peer, credential, native_limit)
                node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
                cleanup_owner(cleanup, node, record, 'node-'+str(native_limit)); probe = Probe(node, products['latentd'])
                selected = {'nativeOwners': native_limit, 'limits': {**LIMITS, 'nativeOwners': native_limit},
                    'configuration': file_identity(config), 'providers': node.startup_record['providers']}
                record['profiles'].append(selected)
                source = signed/'dotnet-standard-http'; stage = 'publication-preparation-'+str(native_limit)
                published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                    '--operation-id', 'capacity-publish', '--expected-generation', '0')
                publication = published['data']['operation']['publication']['id']
                selected['preparation'] = prepare(client, publication, 'examples', original['component.wasm']['sha256'], profile)
                target = deploy(client, source/'deployment.json', publication)
                _, grants = base.grants(client, node, publication, peer.origin())
                target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=grants)
                modes = list(range(len(CASES))) if native_limit == 2 else [7] if native_limit == 0 else [7, 7]
                for index, mode in enumerate(modes):
                    stage = label = 'capacity-'+str(native_limit)+'-'+str(index)+'-'+str(mode)
                    entry = invoke(client, node, target, peer, probe, mode, label,
                        installation_refusal=native_limit == 0)
                    entry['receipt']['path'] = profile.name+'/'+entry['receipt']['path']; record['cases'].append(entry)
                    if native_limit == 2:
                        entry = invoke(client, node, target, peer, probe, 7, label+'-fresh')
                        entry['receipt']['path'] = profile.name+'/'+entry['receipt']['path']; record['cases'].append(entry)
                write_json(profile/'final-owner.json', sample(client, probe, 'final-capacity', 1))
                delete_all(client, [target['name']]); stop(client, node)
                shutdown = stopped_record(node); write_json(profile/'node-stopped.json', shutdown)
                require(shutdown['reaped'] is True and shutdown['record']['clean'] is True, 'capacity-clean-node')
                stopped = peer.close(); write_json(profile/'peer-stopped.json', stopped); validate_peer(stopped)
                require(stopped['startedRequests'] == stopped['acceptedConnections'] == (1 if native_limit == 2 else 0)
                    and stopped['openConnections'] == stopped['rejectedRequests'] == stopped['committedMutations'] == 0,
                    'capacity-exact-final-peer')
        require(shared.identities(artifact) == original and products == {
            name: file_identity(path, 512*1024**2) for name, path in native.items()}, 'capacity-final-products')
        record.update(status='passed', invocations=17, signedComponents=1, httpContacts=1,
            managedOwnerCapacityQualified=True, originalExecutionLimitsIncreased=False)
        require(len(record['cases']) == 17, 'capacity-mandatory-cases')
        write_json(output/'qualification.json', record); return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise
