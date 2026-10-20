"""Separate optional public-SPI programme, never a substitute for default clients."""
from __future__ import annotations

import json
from pathlib import Path
import secrets
import tempfile
import time

from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.java_http_phase_node import configuration, grants, usage, component_operator, component_node_profile
from tools.java_http_spi_fixture import CASES
from tools.phase2_operator_process import require, write_json, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import (RecordingClient, deploy, delete_all, sample, start_call,
                                    finish_call, selected_revision)
from tools.rust_capsule_project import fresh
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer


def expected(mode):
    require(type(mode) is int and 0 <= mode <= 4, 'java-spi-unknown-mode')
    if mode in (0,): return '1:spi:200:7:1'
    if mode in (1, 4): return '1:spi:200:7:0'
    if mode == 2: return '1:spi-error:permission-denied:1'
    if mode == 3: return '1:spi-error:invalid-request:1'
    raise ValueError('java-spi-unknown-mode')


def validate_result(row, mode, selected):
    response = row['response'];data = response['data']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and data.get('resolvedRevision') == selected, 'java-spi-result-owner')
    require(row['exitCode'] == 0 and row['decoded'] == [expected(mode)], 'java-spi-ordinary-result')
    consumption = data['consumption']
    for key in ('cpuFuel', 'outboundRequests'):
        value = consumption[key]
        require(type(value) is str and 0 < len(value) <= 20 and value.isascii()
            and value.isdecimal() and int(value) < 2**64, 'java-spi-invalid-consumption')
    require(int(consumption['cpuFuel']) > 0, 'java-spi-did-not-execute-library')
    outbound = int(consumption['outboundRequests'])
    require(0 <= outbound <= 1 and (mode in (2, 3) or outbound == 1), 'java-spi-replay-or-outbound-charge')


def invoke(client, node, target, peer, probe, mode, name):
    origin = peer.origin('secondary' if mode == 2 else 'primary')
    endpoint = f"http://{origin['host']}:{origin['port']}"
    selected = selected_revision(client, target)
    before = peer.observation();offset = len(before['requests'])
    process = start_call(client, target, 'java-standard-http', 'run', [mode, endpoint], name)
    try:
        expires = min(client.deadline, time.monotonic()+125)
        while not process.owner.exited():
            require(time.monotonic() < expires, 'java-spi-invocation-deadline')
            process.drain();node.drain();peer.poll(.005)
            require(peer.observation()['failure'] is None, 'java-spi-peer-failed')
            require(not peer.gates(), 'java-spi-unexpected-pending-gate')
        result = finish_call(client, process)
    except BaseException:
        try: process.close()
        except Exception: pass
        raise
    else:
        process.close()
    write_json(client.evidence/(name+'-result.json'), result)
    validate_result(result, mode, selected)
    for _ in range(64):
        peer.poll(.005)
        if peer.observation()['openConnections'] == 0: break
    observed = peer.observation()
    require(observed['openConnections'] == 0
        and len(observed['requests'])-offset == (0 if mode in (2, 3) else 1),
        'java-spi-contact-or-close')
    retired = sample(client, probe, 'after-'+name, 1)
    physical = usage(client, target)
    require(all(int(physical['counters'][key]) == 0 for key in ACTIVE_COUNTERS),
        'java-spi-physical-owner-retained')
    record = {'case': name, 'mode': mode, 'selectedRevision': selected, 'invocation': result,
        'providerUsage': physical, 'retired': retired, 'peer': observed}
    path = client.evidence/(name+'-spi.json');write_json(path, record)
    return {'case': name, 'mode': mode, 'receipt': {'path': 'controls/'+path.name,
        **file_identity(path, 262144)}}


def run(artifact: Path, binaries: dict, output: Path, *, deadline: float):
    output = fresh(output)
    require(set(binaries) == {'latent', 'latentd', 'capsule_authoring'}, 'java-spi-native-products')
    before = {name: file_identity(path) for name, path in binaries.items()}
    result = {'schemaVersion': 'latent.java.http-public-spi-node.v1', 'status': 'in-progress',
        'defaultClientQualification': False, 'sameNodeCrossTenantHttpQualified': False, 'cases': []}
    node = peer = None;stage = 'sign'
    try:
        signed = output/'releases'
        completed = run_bounded_result([str(binaries['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(completed.returncode == 0, 'java-spi-signing-failed')
        with tempfile.TemporaryDirectory(prefix='lsf-java-http-spi-') as private, owned_cancellation() as cancellation:
            work = Path(private)
            for name in ('client', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_bytes(('Bearer '+secrets.token_hex(32)).encode('ascii'));credential.chmod(0o600)
            peer = Peer(credential.read_bytes(), maximum_seconds=180)
            client = RecordingClient(binaries['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+160), evidence=output/'controls', invocation_timeout_millis=120000)
            config = configuration(work/'node', signed, peer, credential, [])
            result['nodeComponentInputProfile'] = component_node_profile(config)
            stage = 'node'
            node = connect(client, binaries['latentd'], work/'node', config, 'examples', 1)
            component_operator(client)
            probe = Probe(node, before['latentd'])
            source = signed/'java-standard-http'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'http-spi-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            runtime, authorized = grants(client, node, publication, [peer.origin()])
            for allowed, name in (([], 'runtime-denied'), (runtime, 'http-denied')):
                stage = name
                target = deploy(client, source/'deployment.json', publication,
                    generation=str(target['generation']), grants=allowed)
                origin = peer.origin();endpoint = f"http://{origin['host']}:{origin['port']}"
                process = start_call(client, target, 'java-standard-http', 'run', [0, endpoint], name)
                try: denied = finish_call(client, process)
                finally: process.close()
                write_json(client.evidence/(name+'-result.json'), denied)
                require(denied['exitCode'] == 4 and denied['response']['error']['code'] == 'permission-denied'
                    and denied['response']['data']['consumption']['cpuFuel'] == '0'
                    and peer.observation()['startedRequests'] == 0, 'java-spi-authority-bypass')
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for mode, name in CASES:
                stage = name
                result['cases'].append(invoke(client, node, target, peer, probe, mode, name))
            require(len(result['cases']) == 6, 'java-spi-incomplete-cases')
            delete_all(client, [target['name']]);stop(client, node)
            shutdown = stopped_record(node);write_json(client.evidence/'node-stopped.json', shutdown)
            require(shutdown['reaped'] and shutdown['record']['clean'], 'java-spi-unclean-shutdown')
            node = None
            observed = peer.close();peer = None;write_json(client.evidence/'final-peer.json', observed)
            validate_peer(observed)
            require(observed['startedRequests'] == 4 and observed['rejectedRequests'] == 0
                and observed['committedMutations'] == 0
                and all(row['role'] == 'primary' for row in observed['requests']), 'java-spi-contact-count')
            after = {name: file_identity(path) for name, path in binaries.items()}
            write_json(client.evidence/'native-products-final.json', {'before': before, 'after': after})
            require(before == after, 'java-spi-native-product-mutated')
            result.update(status='passed', invocations=6, authorityDenials=2, httpContacts=4,
                shutdown={'path': 'controls/node-stopped.json', **file_identity(client.evidence/'node-stopped.json')},
                peer={'path': 'controls/final-peer.json', **file_identity(client.evidence/'final-peer.json')})
            write_json(output/'qualification.json', result)
            return result
    except BaseException:
        try: write_json(output/'FAILED.json', {**result, 'status': 'failed', 'stage': stage})
        except Exception: pass
        raise
    finally:
        import sys
        original = sys.exc_info()[0] is not None;failure = None
        for owned in (node, peer):
            if owned is not None:
                try: owned.close()
                except Exception as error: failure = failure or error
        if not original and failure is not None: raise failure
