"""Continue untouched mixed operations after preserving the exact request-limit failure."""
from contextlib import ExitStack
from pathlib import Path
import secrets
import sys
import tempfile
import time

from tools import dotnet_http_mixed_node as n
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import WorkflowError, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_node import RecordingClient, deploy, delete_all, sample, selected_revision
from tools.rust_capsule_project import fresh, read_json, write_json
from tools.standard_http.peer import Peer
from tools.standard_http.observations import validate as validate_peer


def preserved_limit(row, revision, budget):
    """A failed outcome stays failed; this is never an alternative success oracle."""
    response = row['response'];data = response['data']
    require(row['activation'] == 'managed-mixed-request-limit' and row['exitCode'] == 4
        and row['decoded'] is None and row['processReaped'] is True
        and response['category'] == 'platform-failure' and response['outcomeKnown'] is True
        and response['requestDispatched'] is True and data['terminalState'] == 'guest_trap'
        and data['resolvedRevision'] == revision and response['error']['code'] == 'guest-trap'
        and response['error']['retryable'] is False
        and response['error']['details'] == [
            {'kind': 'activation.guest-trap', 'fields': {'code': 'guest-trap'}},
            {'kind': 'activation.guest-trap-kind', 'fields': {'kind': 'unreachable-code'}}],
        'managed-continuation-exact-failed-limit-outcome')
    used = data['consumption']
    require(n.natural(used['outboundRequests']) == n.natural(used['effectCount']) == n.natural(used['logBytes']) == 0
        and 0 < n.natural(used['cpuFuel']) <= n.natural(budget['cpuFuel']) <= 1000000000
        and 0 < n.natural(used['peakMemoryBytes']) <= n.natural(budget['memoryBytes']) <= 134217728,
        'managed-continuation-failed-limit-original-bounds')


def run(artifact, native, output, *, deadline):
    output = fresh(output);original = n.identities(artifact)
    products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    record = {'schemaVersion': 'latent.dotnet.http-mixed-continuation.v1', 'status': 'failed',
        'originalRequestLimitFailurePreserved': True, 'requestLimitQualified': False,
        'fullMixedProgrammeQualified': False, 'newGuestOrNativeCompilation': False,
        'originalBuild': original, 'nativeProducts': products, 'cases': []}
    stage = 'normal-signing'
    try:
        signed = output/'releases'
        result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=min(30, deadline-time.monotonic()), max_output_bytes=65536)
        require(result.returncode == 0, 'managed-continuation-normal-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-managed-http-continuation-') as temporary, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'credentials'):(work/name).mkdir(mode=0o700)
            peers, credentials = {}, {}
            for name in ('main', 'helper'):
                secret = ('Bearer '+secrets.token_hex(32)).encode('ascii')
                credentials[name] = work/'credentials'/name
                credentials[name].write_bytes(secret);credentials[name].chmod(0o600)
                peers[name] = Peer(secret, maximum_seconds=300)
                n.cleanup_owner(cleanup, peers[name], record, 'peer-'+name)
            client = RecordingClient(native['latent'], work/'client', cancellation,
                min(deadline, time.monotonic()+300), evidence=output/'controls',
                invocation_timeout_millis=120000, control_timeout_millis=15000)
            config = n.configuration(work/'node', signed, peers, credentials)
            record['configuration'] = file_identity(config)
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            n.cleanup_owner(cleanup, node, record, 'node');probe = Probe(node, products['latentd'])
            try:
                source = signed/n.TEMPLATE;stage = 'publication-preparation'
                published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                    '--operation-id', 'managed-continuation-publish', '--expected-generation', '0')
                publication = published['data']['operation']['publication']['id']
                record['preparation'] = n.prepare(client, publication, 'examples', original['component.wasm']['sha256'], output)
                target = deploy(client, source/'deployment.json', publication)
                _, authorized = n.grants(client, node, publication, [peer.origin() for peer in peers.values()])
                target = deploy(client, source/'deployment.json', publication, generation=str(target['generation']), grants=authorized)
                stage = 'preserve-failed-request-limit'
                revision = selected_revision(client, target)
                try:
                    n.invoke(client, node, target, peers, probe, 8, 'managed-mixed-request-limit')
                except WorkflowError as error:
                    require(str(error) == 'managed-mixed-default-result', 'managed-continuation-only-original-assertion')
                else:raise WorkflowError('managed-continuation-original-failure-changed')
                failed = read_json(client.evidence/'managed-mixed-request-limit-result.json')
                preserved_limit(failed, revision, target['budget'])
                retired = sample(client, probe, 'after-original-request-limit-failure', 1)
                counters = n.usage(client, target)
                require(all(n.natural(counters['counters'][key]) == 0 for key in ACTIVE_COUNTERS),
                    'managed-continuation-failed-limit-owner-retirement')
                for peer in peers.values():
                    peer.poll(.005)
                    value = peer.observation();validate_peer(value)
                    require(value['acceptedConnections'] == value['startedRequests'] == value['openConnections'] == 0,
                        'managed-continuation-failed-limit-zero-contact')
                cells, = retired['inventory']['cellCapacity']
                require(n.natural(cells['total']) == n.natural(cells['available']) == 1
                    and n.natural(cells['active']) == n.natural(cells['quarantined']) == n.natural(cells['queueDepth']) == 0,
                    'managed-continuation-original-single-free-cell')
                record['preservedFailure'] = {'outcome': failed, 'physicalRetirement': retired, 'providerUsage': counters,
                    'peers': {name: peer.observation() for name, peer in peers.items()}, 'qualified': False}
                write_json(output/'preserved-request-limit-failure.json', record['preservedFailure'])
                stage = 'fresh-after-original-failure'
                fresh_call = n.invoke(client, node, target, peers, probe, 16, 'managed-continuation-fresh-after-limit')
                fresh_raw = read_json(output/fresh_call['receipt']['path'])
                require(fresh_raw['invocation']['response']['data']['metadata'] == {
                    'cell-disposition': 'released', 'cell-id': 'operator-workflow-test:phase0:standard:00000000'},
                    'managed-continuation-fresh-original-cell')
                record['freshAfterFailure'] = fresh_call
                for mode in range(9, 20):
                    stage = n.CASES[mode]
                    record['cases'].append(n.invoke(client, node, target, peers, probe, mode, 'managed-mixed-'+n.CASES[mode]))
                write_json(output/'final-owner.json', sample(client, probe, 'final-managed-continuation', 1))
                delete_all(client, [target['name']]);stop(client, node)
                shutdown = stopped_record(node);write_json(output/'node-stopped.json', shutdown)
                require(shutdown['reaped'] is True and shutdown['record']['clean'] is True, 'managed-continuation-clean-node-stop')
                for name, peer in peers.items():
                    value = peer.close();write_json(output/(name+'-peer-stopped.json'), value);validate_peer(value)
                    expected = sum(n.helper_contacts(mode) for mode in range(9, 20))
                    if name != 'helper':expected = 1+sum(n.CONTACTS[9:20])-expected
                    require(value['startedRequests'] == value['acceptedConnections'] == expected
                        and value['openConnections'] == value['rejectedRequests'] == value['committedMutations'] == 0
                        and all(row['role'] == 'primary' and row['authorizationPresent'] is True for row in value['requests']),
                        'managed-continuation-exact-final-peer-contacts')
            finally:
                prior_failure = sys.exc_info()[0] is not None
                try:
                    node.drain()
                    for index, name in ((0, 'stdout'), (1, 'stderr')):
                        raw = bytes(node.buffers[index])
                        for credential in credentials.values():
                            value = credential.read_bytes()
                            for secret in (value, value.removeprefix(b'Bearer ')):
                                raw = raw.replace(secret, b'[REDACTED-OWNED-FIXTURE-CREDENTIAL]')
                        require(len(raw) <= 262144, 'managed-continuation-existing-node-stream-bound')
                        (output/('node-'+name+'.txt')).write_bytes(raw)
                except BaseException:
                    record['nodeStreamCaptureConfirmed'] = False
                    if not prior_failure:raise
        require(original == n.identities(artifact) and products == {
            name: file_identity(path, 512*1024**2) for name, path in native.items()}, 'managed-continuation-final-product-identities')
        write_json(output/'final-products.json', {'build': original, 'native': products})
        record.update(diagnosticCompleted=True, continuedInvocations=11, freshAfterFailureInvocations=1,
            httpContacts=1+sum(n.CONTACTS[9:20]))
        write_json(output/'diagnostic.json', record)
        return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'stage': stage, 'diagnosticCompleted': False})
        except BaseException:pass
        raise
