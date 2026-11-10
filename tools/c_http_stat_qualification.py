#!/usr/bin/env python3
"""Qualify ordinary libfetch HEAD, Range and redirect refusal with one signed C component."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import sys
import tempfile
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_thread_runtime_node as owner
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, source_identity
from tools.phase3_resource_os import Probe
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure as configure_base, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.standard_http.observations import delta, require_zero_contact, validate
from tools.standard_http.peer import Peer
from tools.standard_http.vectors import DOMAIN, head, json_bytes
from tools.static_api.node import policy

CASES = ('normal', 'denied', 'not-found', 'redirect', 'fresh', 'range', 'range-ignored', 'range-denied',
         'range-unsolicited', 'range-before')
PROBE = 'sdk/c-guest/runtime-fixtures/libfetch/stat-probe.c'
SELF = 'tools/c_http_stat_qualification.py'
WORKFLOW = '.github/workflows/c-http-stat-qualification.yml'


def partial_response(request):
    require(request.method == b'GET' and request.headers.get(b'range') == b'bytes=5-',
            'c-range-exact-request')
    body = json_bytes(DOMAIN)
    require(len(body) > 5, 'c-range-fixture-size')
    value = f'bytes 5-{len(body) - 1}/{len(body)}'.encode('ascii')
    return head(206, len(body) - 5, headers=((b'Content-Range', value),)) + body[5:]


def invalid_partial_response(request, *, unsolicited):
    require(request.method == b'GET', 'c-invalid-partial-method')
    if unsolicited:
        require(b'range' not in request.headers, 'c-unsolicited-request-has-range')
        value = b'bytes 0-3/*'
    else:
        require(request.headers.get(b'range') == b'bytes=5-', 'c-before-exact-range-request')
        value = b'bytes 0-3/4'
    return head(206, 4, headers=((b'Content-Range', value),)) + b'abcd'


class RangePeer(Peer):
    """Serve the selected valid and invalid ranges on existing fixture paths."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.range_requests = 0
        self.unsolicited_requests = 0
        self.early_range_requests = 0

    def _start_request(self, stream, record):
        super()._start_request(stream, record)
        if record.parser.method == b'GET':
            if record.vector.identity == 'domain-json' and b'range' not in record.parser.headers:
                self.unsolicited_requests += 1
            else:
                require(record.parser.headers.get(b'range') == b'bytes=5-', 'c-range-exact-request')
                self.range_requests += 1
                if record.vector.identity == 'method-bytes':
                    self.early_range_requests += 1

    def _complete_request(self, stream, record):
        if record.parser.method != b'GET' or record.vector.identity not in ('domain-json', 'method-bytes'):
            return super()._complete_request(stream, record)
        body = record.parser.body
        record.observation.update(state='request-complete', bodyBytes=len(body),
                                  bodySha256='sha256:' + hashlib.sha256(body).hexdigest())
        self._event('request-complete', record, bodyBytes=len(body))
        if record.vector.identity == 'method-bytes':
            output = invalid_partial_response(record.parser, unsolicited=False)
        elif b'range' not in record.parser.headers:
            output = invalid_partial_response(record.parser, unsolicited=True)
        else:
            output = partial_response(record.parser)
        record.output, record.suffix = output, b''
        record.phase = 'sending'
        self._set_events(stream, record, selectors.EVENT_READ | selectors.EVENT_WRITE)


def install(client, node, target, origin):
    grants = owner.install(client, node, target)
    rows = [row for row in node.startup_record['providers'] if row['capability'] == owner.HTTP]
    require(len(rows) == 1 and rows[0]['profile'] == 'bounded-streaming-http-identity-v1'
            and rows[0]['tenant'] == 'examples' and rows[0]['service'] == 'http-host'
            and rows[0]['configurationEpoch'] == '1', 'c-stat-installed-http-provider')
    descriptor = rows[0]
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': owner.HTTP, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    rules = []
    for method, paths in [('HEAD', ['/conformance/json', '/conformance/status/404', '/conformance/redirect']),
                          ('GET', ['/conformance/echo', '/conformance/json', '/conformance/body/boundary'])]:
        rules.append({'id': 'ordinary-libfetch-' + method.lower(), 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': owner.HTTP, 'operations': owner.HTTP_OPS,
            'resources': {'kind': 'http', 'origins': [origin], 'methods': [method],
                          'paths': paths, 'pathPrefixes': []},
            'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144,
                        'wallTimeMillis': 5000}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': rules})
    return grants + [{'capability': owner.HTTP, 'policy': 'http-allow'}]


def cell(client, probe, target, peer, output, case):
    vectors = {'normal': 'domain-json', 'denied': 'method-bytes',
               'not-found': 'http-404', 'redirect': 'redirect', 'fresh': 'domain-json', 'range': 'domain-json',
               'range-ignored': 'response-boundary', 'range-denied': 'http-404',
               'range-unsolicited': 'domain-json', 'range-before': 'method-bytes'}
    require(case in CASES, 'c-stat-closed-case-set')
    before, revision = peer.observation(), owner.selected_revision(client, target)
    validate(before)
    activation = 'c-stat-' + case
    process = owner.start_http_call(client, target, case + '\n' + peer.url(vectors[case]), activation)
    deadline, primary = min(client.deadline, time.monotonic() + 8), False
    try:
        while not process.owner.exited():
            client.cancellation.check()
            require(time.monotonic() < deadline, 'c-stat-cell-deadline')
            process.drain(); peer.poll(min(0.02, max(0, deadline - time.monotonic())))
        row = owner.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        response = row['response']
        require(row['processReaped'] is True and response['outcomeKnown'] is True
                and response['requestDispatched'] is True
                and response['data']['resolvedRevision'] == revision, 'c-stat-known-current-invocation')
        def range_result(offset, total, data):
            checksum = 0
            for byte in data: checksum = (checksum * 33 + byte) & 0xffffffff
            return (0, [{'ok': f'{offset}:{len(data)}:{total}:{len(data)}:{checksum}'}])
        domain = json_bytes(DOMAIN)
        expected = {
            'normal': (0, [{'ok': f'{len(json_bytes(DOMAIN))}:0:0'}]),
            'fresh': (0, [{'ok': f'{len(json_bytes(DOMAIN))}:0:0'}]),
            'denied': (3, [{'err': 'permission-denied'}]),
            'not-found': (3, [{'err': 'unavailable'}]),
            'redirect': (3, [{'err': 'redirect-unsupported'}]),
            'range': range_result(5, len(domain), domain[5:]),
            'range-ignored': range_result(0, 8192, b'x' * 8192),
            'range-denied': (3, [{'err': 'permission-denied'}]),
            'range-unsolicited': (3, [{'err': 'invalid-content-range'}]),
            'range-before': (3, [{'err': 'invalid-content-range'}]),
        }
        require(type(row['exitCode']) is int and (row['exitCode'], row['decoded']) == expected[case],
                'c-stat-exact-ordinary-result')
        consumed = response['data']['consumption']
        require(0 < owner.integer(consumed['cpuFuel']) <= 1_000_000_000
                and 0 < owner.integer(consumed['peakMemoryBytes']) <= 32 * 1024**2
                and all(owner.integer(consumed[key]) == 0 for key in ('stateReadBytes', 'stateWriteBytes',
                    'blobReadBytes', 'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')),
                'c-stat-original-budget-and-unrelated-authority')
        for _ in range(128):
            observed = peer.observation()
            if observed['openConnections'] == 0: break
            require(time.monotonic() < deadline, 'c-stat-peer-retirement-deadline')
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
        observed = peer.observation(); validate(observed)
        change = delta(before, observed)
        if case in ('denied', 'range-denied'):
            require_zero_contact(before, observed)
        else:
            require(change['startedRequests'] == 1 and len(change['requests']) == 1
                    and change['requests'][0]['vector'] == vectors[case]
                    and change['requests'][0]['method'] == ('GET' if case.startswith('range') else 'HEAD')
                    and change['requests'][0]['role'] == 'primary'
                    and change['requests'][0]['authorizationPresent'] is True
                    and change['rejectedRequests'] == change['connectionBoundRejections'] == 0,
                    'c-stat-one-authenticated-head-no-replay')
        require(observed['openConnections'] == 0, 'c-stat-no-peer-owners-left')
        write_json(output / ('peer-' + activation + '.json'), observed)
        retirement = owner.retire(client, probe, target, output, activation)
        if case == 'redirect':
            # Both origins remain live. Drain any immediately pending contact
            # after the original activation is retired, then fail on any new
            # connection or request instead of treating an idle snapshot as a fence.
            peer.poll(0.05)
            after_retirement = peer.observation()
            require_zero_contact(observed, after_retirement)
            require(after_retirement['openConnections'] == 0, 'c-redirect-no-late-peer-owners')
            write_json(output / ('peer-post-retirement-' + activation + '.json'), after_retirement)
        return {'case': case, 'activation': activation, 'exitCode': row['exitCode'],
                'peerDelta': change, 'retirement': retirement}
    except BaseException:
        primary = True
        write_json(output / ('peer-failed-' + activation + '.json'), peer.observation())
        try: owner.retain_partial(process, output, activation)
        except BaseException: pass
        raise
    finally:
        owner.close_call(process, primary_failure=primary)


def run_node(artifact, native, output, deadline):
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    before = {name: file_identity(path) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    commands.deadline = min(commands.deadline, deadline)
    record = {'schemaVersion': 'latent.c.http-stat.node.v1', 'status': 'incomplete',
              'component': component, 'native': before, 'full690Qualified': False}
    stage, failed = 'sign', False
    try:
        signed = output / 'signed'
        commands.run('stat-sign', native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == component['sha256'],
                'c-stat-one-signed-component')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-c-stat-') as temporary, \
                owner.owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'credentials'): (work / name).mkdir(mode=0o700)
            secret = b'Bearer ' + secrets.token_hex(32).encode('ascii')
            credential = work / 'credentials/peer'
            credential.write_bytes(secret); credential.chmod(0o600)
            peer = RangePeer(secret, maximum_seconds=max(1, min(300, int(commands.deadline - time.monotonic()))))
            cleanup.callback(peer.close)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            config, settings = configure_base(work / 'node', signed, peer.origin()['port'], language='c')
            owner.configure_http(settings, read_json(artifact / 'capsule.json'), peer, credential)
            destinations = settings['providers']['httpStreaming']['configuration']['destinations']
            require(len(destinations) == 2 and destinations[0]['origin'] == peer.origin()
                    and destinations[1]['origin'] == peer.origin('secondary')
                    and destinations[0]['redirectDestinations'] == []
                    and destinations[1]['redirectDestinations'] == []
                    and settings['providers']['httpStreaming']['configuration']['limits']['maximumRedirects'] == 0
                    and 'range' not in destinations[0]['allowedRequestHeaders'], 'c-range-provider-shape')
            destinations[0]['allowedRequestHeaders'].append('range')
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            stage = 'node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / owner.SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'c-stat-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'c-stat-signed-admission')
            target = deploy(client, source / 'deployment.json', published['data']['operation']['publication']['id'])
            require(target['grants'] == [], 'c-stat-no-ambient-grants')
            grants = install(client, node, target, peer.origin())
            target = deploy(client, source / 'deployment.json', target['publication'],
                            generation=str(target['generation']), grants=grants)
            stage = 'ten-signed-head-range-and-redirect-cells'
            record['cases'] = [cell(client, probe, target, peer, output, case) for case in CASES]
            final_peer = peer.observation()
            validate(final_peer)
            require(final_peer['acceptedConnections'] == final_peer['startedRequests'] == 8
                    and all(row['role'] == 'primary' for row in final_peer['requests'])
                    and peer.range_requests == 3 and peer.unsolicited_requests == 1
                    and peer.early_range_requests == 1,
                    'c-stat-eight-primary-contacts-three-ranges-one-unsolicited-one-early')
            record['exactRangeRequests'] = peer.range_requests
            record['unsolicitedRequests'] = peer.unsolicited_requests
            record['earlyRangeRequests'] = peer.early_range_requests
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'c-stat-after-deletes', 0)
            stop(client, node); record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = peer.close(); validate(record['peerShutdown'])
            require(record['peerShutdown']['openConnections'] == record['peerShutdown']['listeningOrigins'] == 0,
                    'c-stat-stopped-peer')
            cancellation.check()
        require(component == file_identity(artifact / 'component.wasm', 8 * 1024**2)
                and before == {name: file_identity(path) for name, path in native.items()}
                and time.monotonic() < commands.deadline and client.calls <= 384,
                'c-stat-final-original-inputs-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException:
        failed = True; record.update(status='failed', stage=stage)
        raise
    finally:
        if failed: write_json(output / 'FAILED.json', record)


def qualify(args):
    from tools import c_capsule_build, c_capsule_project, c_thread_runtime_fixture as fixture
    from tools.c_guest.standard_facilities import FETCH_PROFILE
    from tools.qualify_c_standard_facilities import http_sources, http_build_evidence
    from tools.qualify_java_server_lifecycle import ordinary_tuple
    from tools.qualify_java_server_lifecycle_suite import native as build_native
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-stat-unprivileged-linux-owner')
    stamp = os.environ.get('LSF_C_LIBFETCH_STARTED_NS', '')
    require(stamp.isascii() and stamp.isdigit() and len(stamp) <= 20, 'c-stat-existing-setup-clock')
    elapsed = (time.time_ns() - int(stamp)) / 1_000_000_000
    require(0 <= elapsed < 1315, 'c-stat-original-parent-clock')
    parent = time.monotonic() + 1320 - elapsed
    destination = args.output.absolute()
    require(destination != ROOT and ROOT not in destination.parents and destination not in ROOT.parents,
            'c-stat-owned-output-outside-checkout')
    output = fresh(destination)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1320, command_seconds=900)
    commands.deadline = parent - 5
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    result = {'schemaVersion': 'latent.c.http-stat.qualification.v1', 'status': 'incomplete',
              'full690Qualified': False, 'fullCCostModelQualified': False,
              'publisherAuthenticated': False, 'releasePublished': False,
              'limits': {'parentSeconds': 1320, 'commandSeconds': 900, 'cleanupReserveSeconds': 5,
                         'jobs': 2, 'components': 1, 'cells': 10, 'clientCalls': 384}}
    stage = 'source'
    def source_inputs(capture=False):
        rows = http_sources(commands, output, capture=capture, runtime_profile=FETCH_PROFILE)
        for name in (SELF, PROBE, WORKFLOW):
            rows[name] = file_identity(ROOT / name, 4 * 1024**2)
            if capture:
                q = output / 'owner-inputs' / name; q.parent.mkdir(parents=True, exist_ok=True)
                q.write_bytes(read_file(ROOT / name, 4 * 1024**2))
                require(file_identity(q, 4 * 1024**2) == rows[name], 'c-stat-owned-source-capture')
        require(len(rows) <= 256 and sum(row['bytes'] for row in rows.values()) <= 16 * 1024**2,
                'c-stat-original-source-count-byte-bounds')
        return rows
    try:
        source = source_identity(ROOT)
        head = commands.run('source-head', 'git', 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
        require(len(head) == 2 and all(len(v) == 40 and all(c in '0123456789abcdef' for c in v) for v in head),
                'c-stat-source-head-tree')
        commands.run('source-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        helpers = source_inputs(capture=True)
        result['source'] = {'head': head[0], 'tree': head[1], 'native': source, 'helpers': helpers}
        stage = 'fresh-native-products'
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        directory, receipt = build_native(commands, build_root, tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode()))
        native = {n: directory / n for n in ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
        result['nativeTuple'] = ordinary_tuple(receipt, native)
        stage = 'fresh-ordinary-component'
        sdk = inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
        project = fixture.prepare_http(output / 'project')
        (project / 'src/main.c').write_bytes(read_file(ROOT / PROBE, 65536))
        original = inventory(snapshot(project))
        installed = {n: getattr(args, n.replace('-', '_')).resolve(strict=True) for n in ('zig', 'wit-bindgen', 'wasm-tools')}
        tools = {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()}
        artifact = output / 'build'
        c_capsule_build.build(project, artifact, native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', installed=installed, _deadline=commands.deadline)
        result['build'] = http_build_evidence(artifact, original, runtime_profile=FETCH_PROFILE)
        stage = 'ten-signed-head-range-and-redirect-cells'
        result['node'] = run_node(artifact, native, output / 'node', commands.deadline)
        require(result['node']['status'] == 'passed'
                and [row['case'] for row in result['node']['cases']] == list(CASES), 'c-stat-exact-ten-outcomes')
        require(helpers == source_inputs() and source_identity(ROOT) == source
                and sdk == inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
                and original == inventory(snapshot(project))
                and result['nativeTuple'] == ordinary_tuple(receipt, native)
                and tools == {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()},
                'c-stat-all-actual-inputs-still-exact')
        commands.run('source-still-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        require(time.monotonic() < commands.deadline, 'c-stat-original-parent-deadline')
        result.update(status='passed', tools=tools, commands=commands.records)
        write_json(output / 'qualified.json', result)
        return result
    except BaseException:
        result.update(status='failed', stage=stage, commands=commands.records)
        write_json(output / 'FAILED.json', result)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('zig', 'wit-bindgen', 'wasm-tools', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    qualify(parser.parse_args())
