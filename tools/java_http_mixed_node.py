"""Signed ordinary body ownership controls under the unchanged phase limits."""
from __future__ import annotations

from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools import java_http_phase_node as phase
from tools.java_http_fiber_node import ready_sibling
from tools.java_http_mixed_fixture import CASES
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

EXPECTED = ('1:views:57:same:consumed:closed', '1:borrowed:57:false:false',
    '1:borrowed:4109:true:false', '1:partial-error:short:unexpected-eof',
    '1:response-limit:response-too-large', '1:request-boundary:4096:200',
    '1:request-limit:invalid-request', None, '1:fresh:200:0:0',
    '1:response-boundary:8192:200')
CONTACTS = (1, 1, 2, 1, 1, 1, 0, 2, 1, 1)
ARTIFACTS = ('component.wasm', 'BUILD-COMPLETE.json', 'source-inputs.json', 'recipe-inputs.json',
    'compiler-inputs.json', 'build-observation.json', 'http-client-profile.json',
    'runtime-profile.json', 'java-classpath.json')


def identities(artifact):
    return {name: file_identity(artifact/name, 64*1024*1024 if name == 'component.wasm' else 4*1024*1024)
        for name in ARTIFACTS}


def validate_result(row, mode, selected):
    require(type(mode) is int and 0 <= mode < len(CASES), 'java-mixed-unknown-case')
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data'].get('resolvedRevision') == selected, 'java-mixed-signed-result-owner')
    if mode == 7:
        require(row['exitCode'] == 4 and response['category'] == 'platform-failure'
            and response['error']['code'] == 'cancelled'
            and response['data']['terminalState'] == 'cancelled', 'java-mixed-root-cancellation')
    else:
        require(row['exitCode'] == 0 and row['decoded'] == [EXPECTED[mode]], 'java-mixed-ordinary-result')
    # A rejected declared length is refused before pool admission/outbound charge.
    require(int(response['data']['consumption']['outboundRequests']) == CONTACTS[mode],
        'java-mixed-request-count-or-replay')


def retain_partial(client, process, peer, name, stage, gate, pending, cancellation, released):
    """Best-effort bounded public-fixture evidence, never a terminal witness."""
    try:
        try: process.drain()
        except BaseException: pass
        streams = {}
        for index, suffix in enumerate(('stdout', 'stderr')):
            raw = process.buffers[index]
            require(type(raw) in (bytes, bytearray) and len(raw) <= 32768, 'java-mixed-partial-stream-bound')
            path = client.evidence/(name+'-partial.'+suffix)
            path.write_bytes(bytes(raw));streams[suffix] = file_identity(path, 32768)
        observed = peer.observation()
        require(len(json.dumps(observed, allow_nan=False).encode('utf-8')) <= 262144,
            'java-mixed-partial-peer-bound')
        value = {'schemaVersion': 'latent.java.http-mixed-partial-failure.v1', 'qualification': False,
            'phase': stage, 'partialStreams': streams, 'peer': observed,
            'gate': None if gate is None else {'request': gate.request, 'phase': gate.phase},
            'pending': pending, 'cancel': cancellation, 'releasedOnce': released,
            'processReaped': process.owner.finished is True, 'terminalResultAvailable': False}
        require(len(json.dumps(value, allow_nan=False).encode('utf-8')) <= 524288,
            'java-mixed-partial-record-bound')
        write_json(client.evidence/(name+'-partial-failure.json'), value)
    except BaseException:
        # A diagnostic refusal must never replace the original observer/process
        # exception, invent a completed invocation or authorize an operation retry.
        pass


def invoke(client, node, target, peer, probe, mode, name):
    selected = selected_revision(client, target)
    origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
    offset = len(peer.observation()['requests'])
    process = start_call(client, target, 'java-standard-http', 'run', [mode, endpoint], name)
    gate = pending = cancellation = None
    released = False
    stage = 'waiting'
    primary_failure = False
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'java-mixed-invocation-deadline')
            process.drain();node.drain();peer.poll(.005)
            observed = peer.observation()
            require(observed['failure'] is None, 'java-mixed-peer-failed')
            gates = [value for value in peer.gates() if value.request > offset]
            require(len(gates) <= 1, 'java-mixed-ambiguous-gate')
            if gates and gate is None:
                gate = gates[0]
                require(mode in (2, 7) and gate.phase == 'body', 'java-mixed-unexpected-gate')
                stage = 'pending-owner'
                pending = {'inventory': sample(client, probe, 'held-'+name, 1, active=True),
                    'providerUsage': phase.usage(client, target)}
                require(any(int(pending['providerUsage']['counters'][key]) > 0 for key in ACTIVE_COUNTERS),
                    'java-mixed-pending-owner-missing')
                stage = 'waiting'
            if (gate is not None and (mode == 2 and not released or mode == 7 and cancellation is None)
                    and ready_sibling(observed, offset, gate)):
                require(gate in peer.gates() and not process.owner.exited(), 'java-mixed-body-not-held')
                if mode == 2 and not released:
                    peer.release(gate);released = True
                elif mode == 7 and cancellation is None:
                    cancellation = {'attempted': True}
                    stage = 'cancellation'
                    value = client.call('activation', 'cancel', name, '--reason', 'Owned mixed Java response control')
                    require(value['outcomeKnown'] and value['data']['activationId'] == name
                        and value['data']['disposition'] == 'accepted', 'java-mixed-cancel-unconfirmed')
                    cancellation['receipt'] = value
                    stage = 'waiting'
        stage = 'finish-result'
        row = finish_call(client, process)
    except BaseException:
        primary_failure = True
        retain_partial(client, process, peer, name, stage, gate, pending, cancellation, released)
        raise
    finally:
        try: process.close()
        except BaseException:
            try:write_json(client.evidence/(name+'-cleanup-refusal.json'),
                {'qualification': False, 'ownedProcessCleanupConfirmed': False})
            except BaseException:pass
            if not primary_failure: raise
    # Store the actual result and peer observation even if a strict oracle fails.
    write_json(client.evidence/(name+'-result.json'), row)
    write_json(client.evidence/(name+'-peer-result.json'), peer.observation())
    validate_result(row, mode, selected)
    if mode in (2, 7):
        require(gate is not None and pending is not None
            and ready_sibling(peer.observation(), offset, gate), 'java-mixed-no-pending-and-sibling-proof')
    if mode == 2: require(released, 'java-mixed-body-never-released')
    if mode == 7:
        require(not released and cancellation is not None and 'receipt' in cancellation,
            'java-mixed-missing-cancel-proof')
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0: break
    observed = peer.observation()
    validate_peer(observed)
    require(observed['openConnections'] == 0 and len(observed['requests'])-offset == CONTACTS[mode],
        'java-mixed-peer-contact-or-retirement')
    retired = sample(client, probe, 'after-'+name, 1)
    physical = phase.usage(client, target)
    require(all(int(physical['counters'][key]) == 0 for key in ACTIVE_COUNTERS),
        'java-mixed-provider-owner-retained')
    result = {'case': name, 'mode': mode, 'selectedRevision': selected, 'invocation': row,
        'pending': pending, 'releasedOnce': released, 'cancel': cancellation,
        'retired': retired, 'providerUsage': physical, 'peer': observed, 'budget': target['budget'],
        'lateCompletionClaimed': False}
    path = client.evidence/(name+'-case.json');write_json(path, result)
    return {'case': name, 'mode': mode,
        'receipt': {'path': 'controls/'+path.name, **file_identity(path, 1024*1024)}}


def run(artifact, binaries, output, *, deadline):
    output = fresh(output)
    original = identities(artifact)
    products = {name: file_identity(path) for name, path in binaries.items()}
    result = {'schemaVersion': 'latent.java.http-mixed-node.v1', 'status': 'in-progress',
        'artifact': original, 'nativeProducts': products, 'cases': [],
        'full688Qualified': False, 'full741Qualified': False, 'lateCompletionClaimed': False}
    stage = 'sign'
    node = peer = None
    try:
        signed = output/'releases'
        signed_process = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(signed_process.returncode == 0, 'java-mixed-normal-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-mixed-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            token = ('Bearer '+secrets.token_hex(32)).encode('ascii')
            credential.write_bytes(token);credential.chmod(0o600)
            peer = Peer(token, maximum_seconds=300);cleanup_owner(cleanup, peer, result, 'peer')
            client = RecordingClient(binaries['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            config = phase.configuration(work/'node', signed, peer, credential, [])
            result['nodeComponentInputProfile'] = phase.component_node_profile(config)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            cleanup_owner(cleanup, node, result, 'node')
            phase.component_operator(client)
            probe = Probe(node, products['latentd'])
            source = signed/'java-standard-http'
            stage = 'publish-and-prepare'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'java-mixed-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            result['preparation'] = prepare(client, publication, 'examples',
                original['component.wasm']['sha256'], output)
            target = deploy(client, source/'deployment.json', publication)
            stage = 'no-grants-denied-before-guest'
            origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
            denied = finish_call(client, start_call(client, target, 'java-standard-http', 'run', [0, endpoint], 'mixed-denied'))
            require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                and denied['response']['data']['consumption']['cpuFuel'] == '0'
                and peer.observation()['acceptedConnections'] == 0, 'java-mixed-authority-bypass')
            _runtime, authorized = phase.grants(client, node, publication, [peer.origin()])
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for mode, name in enumerate(CASES):
                stage = name
                result['cases'].append(invoke(client, node, target, peer, probe, mode, name))
            stage = 'final-physical-and-products'
            write_json(output/'final-owner.json', sample(client, probe, 'final', 1))
            delete_all(client, [target['name']]);stop(client, node)
            shutdown = stopped_record(node);write_json(output/'node-stopped.json', shutdown)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'java-mixed-unclean-shutdown')
            observed = peer.close();write_json(output/'peer-stopped.json', observed)
            validate_peer(observed)
            require(observed['startedRequests'] == sum(CONTACTS) == 11 and observed['rejectedRequests'] == 0
                and observed['committedMutations'] == 0 and observed['openConnections'] == 0,
                'java-mixed-complete-contact-count')
        require(original == identities(artifact)
            and products == {name: file_identity(path) for name, path in binaries.items()},
            'java-mixed-source-or-product-drift')
        write_json(output/'final-products.json', {'artifact': original, 'native': products})
        result.update(status='passed', invocations=len(CASES), authorityDenials=1, httpContacts=11,
            shutdown=file_identity(output/'node-stopped.json'), peer=file_identity(output/'peer-stopped.json'),
            products=file_identity(output/'final-products.json'))
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        try:write_json(output/'FAILED.json', {**result, 'status': 'failed', 'stage': stage})
        except Exception:pass
        raise
