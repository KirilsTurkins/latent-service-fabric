"""Normal captured published Fetch clients; genuine emitted execution required."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_fetch_runtime as base
from tools import typescript_published_fetch_fixture as fixture
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import Process, WorkflowError, require, stopped_record, write_json
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_node import RecordingClient, call, delete_all, deploy
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot
from tools.standard_http.observations import validate as validate_peer
from tools.standard_http.vectors import DOMAIN, json_bytes
from tools.typescript_fetch_replay_inputs import native_inputs
from tools.typescript_guest.build import build

IDENTITIES = (('outside-fetch-alpha', '1.0.0'), ('outside-fetch-delta', '2.4.0'))
VECTORS = (
    ('ky-json', 0, '/conformance/json', 'ky:'),
    ('wretch-json', 1, '/conformance/json', 'wretch:'),
    ('outside-json', 2, '/conformance/json', 'outside:'),
    ('ky-http404-unsupported', 3, '/conformance/status/404', 'ky:unsupported:response-status-text'),
    ('wretch-http404-error', 4, '/conformance/status/404', 'wretch:error:404'),
    ('ky-fresh', 0, '/conformance/json', 'ky:'),
)


def peer_evidence(value):
    validate_peer(value)
    expected = ['domain-json']*3+['http-404']*2+['domain-json']
    require(value['state'] == 'stopped' and value['startedRequests'] == len(expected)
            and value['completedResponseWrites'] == value['acceptedConnections'] == len(expected)
            and value['rejectedRequests'] == value['committedMutations'] == 0
            and [row.get('vector') for row in value['requests']] == expected
            and all(row['role'] == 'primary' for row in value['requests']),
            'published-fetch-exact-peer-contacts')
    return value


def checked_client_result(client, row, expected, name):
    try:
        base.require_result(row, expected, 1)
        return True
    except WorkflowError:
        # The existing redacted operator projection preserves the original
        # failed invocation. No error is reclassified and no request is retried.
        from tools.capsule_invocation_diagnostics import capture
        capture(client,row)
        original=client.evidence/'unexpected-invocation-diagnostics.json'
        if original.is_file():original.rename(client.evidence/('unexpected-'+name+'.json'))
        return False


def require_original_clients(observed, failed):
    expected=['buffered-reader-probe','buffered-json-probe']+[row[0] for row in VECTORS]
    require(not failed and observed==expected,'published-fetch-original-client-outcomes-failed')


def execute(artifact, native, output):
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.published-fetch-execution.v1', 'status': 'in-progress',
              'fullTicketQualification': False, 'cases': []}
    stage, expires = 'sign', time.monotonic()+300
    try:
        original = base.build_evidence(artifact)
        record['artifact'] = original
        environment = build_environment(output)
        signed = output/'releases'
        signed_result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, environment, timeout_seconds=30, max_output_bytes=65536)
        require(signed_result.returncode == 0, 'published-fetch-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-published-fetch-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            credential = work/'peer/authorization'
            credential.write_text('Bearer '+secrets.token_hex(32), encoding='ascii'); credential.chmod(0o600)
            client = RecordingClient(native['latent'], work/'client', cancellation, expires,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            stage = 'peer'
            peer = Process([sys.executable, str(ROOT/'tools/java_standard_http_peer.py'), '--credential', str(credential)],
                work/'peer', environment, cancellation, maximum=65536)
            cleanup.callback(peer.close)
            startup = peer.line(min(expires, time.monotonic()+10))
            config = base.configuration(work/'node', signed, startup, credential)
            record['configurationIdentity'] = file_identity(config)
            stage = 'node'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 1)
            cleanup.callback(node.close)
            probe = Probe(node, file_identity(native['latentd']))
            source = signed/'typescript-fetch'
            stage = 'publication'
            published = client.call('release', 'publish-package', source/'package', '--evidence', source/'evidence/index.json',
                '--operation-id', 'published-fetch-publish', '--expected-generation', '0')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication)
            origin = startup['origins']['primary']
            address = f"http://{origin['host']}:{origin['port']}"
            for phase, selected in (('runtime-denied', None), ('http-denied', 'runtime')):
                stage = phase
                if selected is not None:
                    runtime, authorized = base.grants(client, node, publication, origin)
                    target = deploy(client, source/'deployment.json', publication,
                        generation=str(target['generation']), grants=runtime)
                row = call(client, target, 'typescript-fetch', 'run', [0, address+'/conformance/json'], 'published-fetch-'+phase)
                base.require_denied(row)
                record[phase] = row
                base.retire(client, probe, target, output, phase)
            target = deploy(client, source/'deployment.json', publication,
                generation=str(target['generation']), grants=authorized)
            for name, mode, expected in [('buffered-reader-probe',5,'1|buffered-reader-ready'),
                                         ('buffered-json-probe',6,'1|buffered-json-ready')]:
                stage = name
                row = call(client, target, 'typescript-fetch', 'run', [mode,address+'/conformance/json'],
                    'published-fetch-'+name)
                write_json(output/(name+'.json'), row)
                base.require_result(row,expected,0)
                base.retire(client,probe,target,output,name)
                record['cases'].append(name)
            failed=[]
            for name, mode, path, expected in VECTORS:
                stage = name
                row = call(client, target, 'typescript-fetch', 'run', [mode, address+path], 'published-fetch-'+name)
                write_json(output/(name+'.json'), row)
                if path == '/conformance/json': expected += json_bytes(DOMAIN).decode()
                passed=checked_client_result(client,row,'1|'+expected,name)
                base.retire(client, probe, target, output, name)
                if passed:record['cases'].append(name)
                else:failed.append(name)
                record['failedClientCases']=list(failed)
            delete_all(client, [target['name']])
            stop(client, node)
            record['shutdown'] = stopped_record(node)
            require(record['shutdown']['reaped'] and record['shutdown']['record']['clean'], 'published-fetch-clean-shutdown')
            peer.stop()
            record['peer'] = json.loads(bytes(peer.buffers[0]).splitlines()[0])
            peer_evidence(record['peer'])
            require(peer.owner.finished, 'published-fetch-peer-reaped')
            require_original_clients(record['cases'],failed)
        require(base.build_evidence(artifact) == original, 'published-fetch-built-artifact-changed')
        record.update(status='passed', signedExecution='passed', providerExecution='passed')
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', record)
        raise


def qualify(acquired, tools, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'published-fetch-Linux-Python313')
    acquired, tools = acquired.resolve(strict=True), tools.resolve(strict=True)
    require(output.resolve() != ROOT and ROOT not in output.resolve().parents
            and all(output.resolve() != path and output.resolve() not in path.parents
                    and path not in output.resolve().parents for path in (acquired, tools)),
            'published-fetch-separate-output')
    output = fresh(output)
    originals, identity = native_inputs(acquired/'native')
    selected = fresh(output/'selected-native')
    native = {}
    for name, source in originals.items():
        native[name] = selected/name
        shutil.copyfile(source, native[name]); native[name].chmod(0o700)
    binaries = {name: file_identity(path, 192*1024**2) for name, path in native.items()}
    record = {'schemaVersion': 'latent.typescript.published-fetch-qualification.v1', 'status': 'incomplete',
              'fullTicketQualification': False, 'historicalNative': identity, 'variants': [],
              'defaultClientHttpErrorQualified': False, 'statusText': 'unsupported-by-original-typed-response',
              'limits': dict(base.OWNER_LIMITS), 'applicationFetchInjection': False, 'packageSourceChanges': False}
    stage = 'capture'
    try:
        for index, (name, version) in enumerate(IDENTITIES, 1):
            variant = fresh(output/f'variant-{index}')
            app = fixture.project(variant/'application', name)
            stage = f'capture-{index}'
            capture = fixture.capture(app, variant/name, name, version)
            write_json(variant/'capture.json', capture)
            before = inventory(snapshot(app))
            stage = f'normal-build-{index}'
            artifact = build(app, variant/'build', native['capsule_contracts'], native['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
                runtime_engine=acquired/'engine/engine.wasm', runtime_engine_receipt=acquired/'engine/engine-input.json',
                runtime_splicer=acquired/'splicer/splicer', runtime_splicer_receipt=acquired/'splicer/splicer-input.json')
            stage = f'signed-execution-{index}'
            observed = execute(artifact, native, variant/'node')
            require(before == inventory(snapshot(app)), 'published-fetch-captured-source-changed')
            record['variants'].append({'capture': capture, 'source': digest(before),
                'build': base.build_evidence(artifact), 'cases': observed['cases'],
                'execution': file_identity(variant/'node/qualification.json')})
        require(native_inputs(acquired/'native')[1] == identity
                and binaries == {name: file_identity(path, 192*1024**2) for name, path in native.items()},
                'published-fetch-native-input-changed')
        record.update(status='passed', signedExecution='passed', providerExecution='passed')
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        record.update(status='failed', stage=stage)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('acquired', 'tools', 'output'): parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.acquired, args.tools, args.output)))
