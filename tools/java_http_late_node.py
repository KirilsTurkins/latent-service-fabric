"""Real late HTTP completion after logical cancellation, before retirement."""
from contextlib import ExitStack
import hashlib
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools import java_http_phase_node as phase
from tools.java_http_late_fixture import CASES
from tools.java_http_mixed_node import identities, retain_partial
from tools.java_http_release_preparation import prepare
from tools.java_http_tenant_node import cleanup_owner
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import (RecordingClient, deploy, delete_all, sample, start_call,
                                    finish_call, selected_revision)
from tools.rust_capsule_project import fresh, write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer

KINDS = ('future-task', 'completable-default')


def expected(mode):
    require(type(mode) is int and 0 <= mode <= 2, 'java-late-unknown-mode')
    return '1:fresh:200:0:0' if mode == 2 else '1:late:'+KINDS[mode]+':1:0:1:true:4109'


def marker_after_cancel(observed, offset, gate, mode):
    """A real POST is possible only after the source's cancel/get/observe fence."""
    require(mode in (0, 1), 'java-late-marker-mode')
    marker = (KINDS[mode]+':cancelled:results:1').encode('ascii')
    pending = [row['sequence'] for row in observed['events'] if row['kind'] == 'gate-pending'
        and row['request'] == gate.request and row['phase'] == 'body']
    require(len(pending) == 1, 'java-late-exact-body-gate')
    complete = {row['request'] for row in observed['requests'][offset:]
        if row.get('role') == 'primary' and row.get('vector') == 'method-bytes'
        and row.get('method') == 'POST' and row.get('bodyBytes') == len(marker)
        and row.get('bodySha256') == 'sha256:'+hashlib.sha256(marker).hexdigest()
        and row.get('closeReason') == 'response-write-complete'}
    return any(row['kind'] == 'response-write-complete' and row['request'] in complete
        and row['sequence'] > pending[0] for row in observed['events'])


def validate_result(row, mode, selected):
    require(row['processReaped'] is True and row['exitCode'] == 0 and row['decoded'] == [expected(mode)]
        and row['response']['outcomeKnown'] is True
        and row['response']['data'].get('resolvedRevision') == selected,
        'java-late-cancelled-result-or-signed-revision')
    require(int(row['response']['data']['consumption']['outboundRequests']) == (1 if mode == 2 else 2),
        'java-late-request-replayed')


def invoke(client, node, target, peer, probe, mode, name):
    selected = selected_revision(client, target)
    origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
    offset = len(peer.observation()['requests'])
    process = start_call(client, target, 'java-standard-http', 'run', [mode, endpoint], name)
    gate = pending = None;released = failed = False
    stage = 'waiting'
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'java-late-invocation-deadline')
            process.drain();node.drain();peer.poll(.005)
            observed = peer.observation();require(observed['failure'] is None, 'java-late-peer-failed')
            gates = [row for row in peer.gates() if row.request > offset]
            require(len(gates) <= 1, 'java-late-ambiguous-gate')
            if gates and gate is None:
                gate = gates[0]
                require(mode != 2 and gate.phase == 'body', 'java-late-unexpected-gate')
            if gate is not None and not released and marker_after_cancel(observed, offset, gate, mode):
                require(gate in peer.gates() and not process.owner.exited(), 'java-late-body-no-longer-pending')
                stage = 'after-logical-cancel-pending-owner'
                pending = {'inventory': sample(client, probe, 'cancelled-but-running-'+name, 1, active=True),
                    'providerUsage': phase.usage(client, target), 'peer': observed,
                    'readOnlyRuntimeResultCount': 1, 'markerBodySha256': 'sha256:'+hashlib.sha256(
                        (KINDS[mode]+':cancelled:results:1').encode()).hexdigest()}
                require(int(pending['providerUsage']['counters']['broker_calls']) >= 1
                    and int(pending['providerUsage']['counters']['pool_running_requests']) >= 1,
                    'java-late-physical-http-owner-refunded-before-completion')
                # Publication/cancel are never retried. This is the only write
                # releasing the fixed peer suffix, after real cancellation proof.
                peer.release(gate);released = True;stage = 'waiting'
        stage = 'finish-result'
        row = finish_call(client, process)
    except BaseException:
        failed = True
        retain_partial(client, process, peer, name, stage, gate, pending, None, released)
        raise
    finally:
        try:process.close()
        except BaseException:
            try:write_json(client.evidence/(name+'-cleanup-refusal.json'), {'qualification': False,
                'ownedProcessCleanupConfirmed': False})
            except BaseException:pass
            if not failed:raise
    write_json(client.evidence/(name+'-result.json'), row)
    write_json(client.evidence/(name+'-peer-result.json'), peer.observation())
    validate_result(row, mode, selected)
    if mode != 2:
        require(gate is not None and pending is not None and released
            and marker_after_cancel(peer.observation(), offset, gate, mode), 'java-late-no-real-cancel-completion-order')
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0:break
    observed = peer.observation();validate_peer(observed)
    require(observed['openConnections'] == 0 and len(observed['requests'])-offset == (1 if mode == 2 else 2),
        'java-late-contact-or-connection-retained')
    retired = sample(client, probe, 'after-'+name, 1);physical = phase.usage(client, target)
    require(all(int(physical['counters'][key]) == 0 for key in ACTIVE_COUNTERS), 'java-late-active-owner-retained')
    value = {'case': name, 'mode': mode, 'selectedRevision': selected, 'invocation': row,
        'pendingAfterLogicalCancel': pending, 'releasedOnce': released,
        'retired': retired, 'providerUsage': physical, 'peer': observed, 'budget': target['budget'],
        'scope': 'late-accepted-task-completion-before-activation-retirement',
        'postRetiredStoreCallbackClaimed': False}
    path = client.evidence/(name+'-case.json');write_json(path, value)
    return {'case': name, 'mode': mode, 'receipt': {'path': 'controls/'+path.name, **file_identity(path, 1024*1024)}}


def run(artifact, binaries, output, *, deadline):
    output = fresh(output);original = identities(artifact)
    products = {name: file_identity(path) for name, path in binaries.items()}
    result = {'schemaVersion': 'latent.java.http-late-node.v1', 'status': 'in-progress', 'cases': [],
        'artifact': original, 'nativeProducts': products, 'postRetiredStoreCallbackClaimed': False,
        'full688Qualified': False, 'full741Qualified': False}
    stage = 'sign'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'java-late-normal-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-late-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'):(work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization';token = ('Bearer '+secrets.token_hex(32)).encode('ascii')
            credential.write_bytes(token);credential.chmod(0o600)
            peer = Peer(token, maximum_seconds=300);cleanup_owner(cleanup, peer, result, 'peer')
            client = RecordingClient(binaries['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            config = phase.configuration(work/'node', signed, peer, credential, [])
            result['nodeComponentInputProfile'] = phase.component_node_profile(config)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup_owner(cleanup, node, result, 'node');phase.component_operator(client)
            probe = Probe(node, products['latentd']);source = signed/'java-standard-http'
            stage = 'publish-and-prepare'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'java-late-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            result['preparation'] = prepare(client, publication, 'examples', original['component.wasm']['sha256'], output)
            target = deploy(client, source/'deployment.json', publication)
            stage = 'no-grants-denied-before-guest'
            origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
            denied = finish_call(client, start_call(client, target, 'java-standard-http', 'run', [2, endpoint], 'late-denied'))
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                and denied['response']['data']['consumption']['cpuFuel'] == '0'
                and peer.observation()['acceptedConnections'] == 0, 'java-late-authority-bypass')
            _, authorized = phase.grants(client, node, publication, [peer.origin()])
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for mode, name in CASES:
                stage = name;result['cases'].append(invoke(client, node, target, peer, probe, mode, name))
            stage = 'final-physical-and-products'
            write_json(output/'final-owner.json', sample(client, probe, 'final', 1))
            delete_all(client, [target['name']]);stop(client, node)
            shutdown = stopped_record(node);write_json(output/'node-stopped.json', shutdown)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'java-late-unclean-shutdown')
            observed = peer.close();write_json(output/'peer-stopped.json', observed);validate_peer(observed)
            require(observed['startedRequests'] == 6 and observed['rejectedRequests'] == 0
                and observed['committedMutations'] == 0 and observed['openConnections'] == 0,
                'java-late-final-contact-count')
        require(original == identities(artifact) and products == {name: file_identity(path) for name, path in binaries.items()},
            'java-late-final-source-or-product-drift')
        write_json(output/'final-products.json', {'artifact': original, 'native': products})
        result.update(status='passed', invocations=4, authorityDenials=1, httpContacts=6,
            shutdown=file_identity(output/'node-stopped.json'), peer=file_identity(output/'peer-stopped.json'),
            products=file_identity(output/'final-products.json'))
        write_json(output/'qualification.json', result);return result
    except BaseException:
        try:write_json(output/'FAILED.json', {**result, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise
