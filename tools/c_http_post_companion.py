#!/usr/bin/env python3
"""Four signed ordinary-libfetch cells, using existing HTTP peer/owner boundaries."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import tomllib

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

CASES = ('post-echo', 'post-uncertain', 'post-cancel', 'fresh-get')
BODY = b'ordinary-post:value=42'
MEDIA = 'text/plain; charset=utf-8'
SELF = 'tools/c_http_post_companion.py'
PROBE = 'sdk/c-guest/runtime-fixtures/libfetch/post-probe.c'
HISTORICAL = 'docs/testing/evidence/c-http-pair-signed-2026-10-31.json'
HISTORICAL_SHA = '0a776706e869555594a6182daee69a4f452e8b96bc185ef57a72cda60f78d3f5'


def install(client, node, target, origin):
    """Exact selected paths only; no temporary broad POST or GET policy."""
    from tools import c_thread_runtime_node as owner
    from tools.guest_runtime_profiles import profiles
    from tools.static_api.node import policy
    grants = owner.install(client, node, target)
    rows = [row for row in node.startup_record['providers'] if row['capability'] == owner.HTTP]
    require(len(rows) == 1 and rows[0]['profile'] == 'bounded-streaming-http-identity-v1'
            and rows[0]['tenant'] == 'examples' and rows[0]['service'] == 'http-host'
            and rows[0]['configurationEpoch'] == '1', 'c-post-installed-http-provider')
    descriptor = rows[0]
    policy(client, 'provider-binding', 'http-installed', {'formatVersion': 1, 'tenant': 'examples',
        'capability': owner.HTTP, 'providerProfile': descriptor['profile'],
        'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
        'restriction': {'operations': []}})
    rules = []
    for method, paths in [('POST', ['/conformance/echo', '/conformance/mutation/close',
                                   '/conformance/mutation/pending']), ('GET', ['/conformance/json'])]:
        rules.append({'id': 'ordinary-libfetch-' + method.lower(), 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': owner.HTTP, 'operations': owner.HTTP_OPS,
            'resources': {'kind': 'http', 'origins': [origin], 'methods': [method],
                          'paths': paths, 'pathPrefixes': []},
            'ceiling': {'operations': 64, 'inputBytes': 65536, 'outputBytes': 262144,
                        'wallTimeMillis': 5000}})
    policy(client, 'policy', 'http-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': rules})
    grants.append({'capability': owner.HTTP, 'policy': 'http-allow'})
    # Same standard facilities as the already-qualified expanded profile.
    for name, (capability, profile, operation, kind) in profiles('c').items():
        rows = [row for row in node.startup_record['providers'] if row['id'] == name]
        require(len(rows) == 1 and rows[0]['capability'] == capability
                and rows[0]['profile'] == profile and rows[0]['tenant'] == 'examples'
                and rows[0]['service'] == 'runtime-host' and rows[0]['configurationEpoch'] == '1',
                'c-post-original-standard-provider')
        descriptor = rows[0]
        policy(client, 'provider-binding', name + '-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': [operation]}})
        policy(client, 'policy', name + '-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow',
            'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [target['service']], 'publications': [target['publication']],
            'capability': capability, 'operations': [operation], 'resources': {'kind': kind},
            'ceiling': {'operations': 4096, 'inputBytes': 128 if kind == 'random' else 0,
                        'outputBytes': 65536, 'wallTimeMillis': 5000}}]})
        grants.append({'capability': capability, 'policy': name + '-allow'})
    require(len(grants) == 6, 'c-post-exact-six-grants')
    return grants


def checksum(data):
    value = 0
    for byte in data:
        value = (value * 33 + byte) & 0xffffffff
    return f'{len(data)}:{value}'


def cell(client, node, probe, target, peer, output, case):
    from tools import c_thread_runtime_node as owner
    from tools.standard_http.observations import delta, require_one_committed_request, validate
    from tools.standard_http.vectors import DOMAIN, json_bytes
    require(case in CASES, 'c-post-closed-four-cells')
    vectors = dict(zip(CASES, ('method-bytes', 'commit-close', 'commit-pending', 'domain-json')))
    before, revision = peer.observation(), owner.selected_revision(client, target)
    validate(before)
    activation = 'c-libfetch-' + case
    process = owner.start_http_call(client, target, case + '\n' + peer.url(vectors[case]), activation)
    deadline, primary, barrier = min(client.deadline, time.monotonic() + 8), False, None
    try:
        while not process.owner.exited():
            client.cancellation.check()
            require(time.monotonic() < deadline, 'c-post-original-cell-deadline')
            process.drain(); peer.poll(min(0.02, max(0, deadline - time.monotonic())))
            observed = peer.observation(); validate(observed)
            change = delta(before, observed)
            if case == 'post-cancel' and barrier is None and change['committedMutations']:
                require_one_committed_request(before, observed)
                gates = peer.gates()
                require(len(gates) == 1 and gates[0].phase == 'headers'
                        and change['requests'][0]['state'] == 'held-headers'
                        and gates[0].generation == observed['generation']
                        and gates[0].request == change['requests'][0]['request'], 'c-post-actual-dispatch-gate')
                acknowledgement = client.call('activation', 'cancel', activation,
                                               '--reason', 'ordinary C POST after actual dispatch')
                require(acknowledgement['outcomeKnown'] is True
                        and acknowledgement['data']['disposition'] == 'accepted', 'c-post-known-cancel-once')
                barrier = {'peer': observed, 'cancellation': acknowledgement,
                           'externalCommitAlreadyObserved': True,
                           'guestErrnoOrResultAfterCancellationClaimed': False, 'rollbackClaimed': False}
                write_json(output / ('barrier-' + activation + '.json'), barrier)
                # Never release the held response to fabricate a guest result.
        row = owner.finish_call(client, process)
        write_json(output / ('invocation-' + activation + '.json'), row)
        response = row['response']
        require(row['processReaped'] is True and response['outcomeKnown'] is True
                and response['requestDispatched'] is True
                and response['data']['resolvedRevision'] == revision, 'c-post-known-current-reaped-invocation')
        if case == 'post-cancel':
            require(barrier is not None and row['exitCode'] == 4
                    and response['error']['code'] == 'cancelled', 'c-post-actual-cancellation-terminal')
        elif case == 'post-uncertain':
            require(row['exitCode'] == 3 and row['decoded'] == [{'err': 'uncertain'}],
                    'c-post-original-library-uncertain-error')
        else:
            expected = json_bytes(DOMAIN) if case == 'fresh-get' else json_bytes({
                'method': 'POST', 'bodyBase64': base64.b64encode(BODY).decode('ascii'),
                'contentLengthPresent': True, 'contentTypePresent': True, 'customHeaderBase64': None})
            require(row['exitCode'] == 0 and row['decoded'] == [{'ok': checksum(expected)}],
                    'c-post-exact-body-and-content-type-presence-result')
        consumed = response['data']['consumption']
        require(0 < owner.integer(consumed['cpuFuel']) <= 1_000_000_000
                and 0 < owner.integer(consumed['peakMemoryBytes']) <= 32 * 1024**2
                and owner.integer(consumed['outboundRequests']) == 1
                and all(owner.integer(consumed[k]) == 0 for k in ('stateReadBytes', 'stateWriteBytes',
                    'blobReadBytes', 'blobWriteBytes', 'logBytes', 'effectCount', 'childCalls')),
                'c-post-original-finite-runtime-authority')
        for _ in range(64):
            peer.poll(min(0.02, max(0, deadline - time.monotonic())))
            if peer.observation()['openConnections'] == 0:
                break
            require(time.monotonic() < deadline, 'c-post-peer-close-deadline')
        observed = peer.observation(); validate(observed); change = delta(before, observed)
        require(change['acceptedConnections'] == change['startedRequests'] == 1
                and len(change['requests']) == 1 and observed['openConnections'] == 0
                and change['rejectedRequests'] == change['connectionBoundRejections'] == 0,
                'c-post-one-contact-no-replay-no-live-peer-owner')
        request = change['requests'][0]
        method = 'GET' if case == 'fresh-get' else 'POST'
        body = b'' if method == 'GET' else BODY
        require(request['vector'] == vectors[case] and request['method'] == method
                and request['role'] == 'primary' and request['authorizationPresent'] is True
                and request['bodyBytes'] == len(body)
                and request['bodySha256'] == 'sha256:' + hashlib.sha256(body).hexdigest(),
                'c-post-actual-request-body-and-exact-vector')
        if case in ('post-uncertain', 'post-cancel'):
            require_one_committed_request(before, observed, vectors[case])
        else:
            require(change['committedMutations'] == 0, 'c-post-no-unrequested-peer-mutation')
        write_json(output / ('peer-' + activation + '.json'), observed)
        return {'case': case, 'activation': activation, 'exitCode': row['exitCode'],
                'peerDelta': change, 'barrier': barrier, 'rollbackClaimed': False,
                'retirement': owner.retire(client, probe, target, output, activation)}
    except BaseException:
        primary = True
        write_json(output / ('peer-failed-' + activation + '.json'), peer.observation())
        try:
            owner.retain_partial(process, output, activation)
        except BaseException:
            pass
        raise
    finally:
        owner.close_call(process, primary_failure=primary)


def qualify(args):
    from tools import c_capsule_build, c_capsule_project, c_thread_runtime_fixture as fixture
    from tools import c_thread_runtime_node as node
    from tools.build_observation import build_environment
    from tools.c_guest.standard_facilities import FETCH_STANDARD_PROFILE
    from tools.qualify_c_standard_facilities import http_sources, http_build_evidence
    from tools.qualify_java_server_lifecycle import ordinary_tuple
    from tools.qualify_java_server_lifecycle_suite import native as build_native
    from tools.rust_capsule_build import Commands
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-post-original-unprivileged-linux-owner')
    stamp = os.environ.get('LSF_C_LIBFETCH_STARTED_NS', '')
    require(stamp.isascii() and stamp.isdigit() and len(stamp) <= 20, 'c-post-existing-setup-clock')
    elapsed = (time.time_ns() - int(stamp)) / 1_000_000_000
    require(0 <= elapsed < 1315, 'c-post-original-parent-clock')
    parent = time.monotonic() + 1320 - elapsed
    destination = args.output.absolute()
    require(destination != ROOT and ROOT not in destination.parents and destination not in ROOT.parents,
            'c-post-owned-output-outside-checkout')
    output = fresh(destination)
    commands = Commands(ROOT, output, build_environment(output), deadline_seconds=1320, command_seconds=900)
    commands.deadline = parent - 5
    commands.environment.update(CARGO_TARGET_DIR=os.environ.get('CARGO_TARGET_DIR', str(ROOT / 'target')),
        CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0')
    result = {'schemaVersion': 'latent.c.http-post.qualification.v1', 'status': 'incomplete',
              'scope': 'four-original-libfetch-post-uncertain-cancel-fresh-get-cells',
              'full690Qualified': False, 'fullCCostModelQualified': False,
              'publisherAuthenticated': False, 'releasePublished': False,
              'contentTypePresenceOnly': True, 'exactContentTypeValueRuntimeQualified': False,
              'nativeBinaryBytesIndependentlyRetained': False,
              'limits': {'parentSeconds': 1320, 'commandSeconds': 900, 'cleanupReserveSeconds': 5,
                         'jobs': 2, 'components': 1, 'cells': 4, 'clientCalls': 384,
                         'clientRetentionBytes': 4 * 1024**2, 'clientSeconds': 240}}
    stage = 'source'
    def source_inputs(capture=False):
        rows = http_sources(commands, output, capture=capture, runtime_profile=FETCH_STANDARD_PROFILE)
        for name in (SELF, PROBE, HISTORICAL, ".github/workflows/c-http-post-companion.yml"):
            rows[name] = file_identity(ROOT / name, 4 * 1024**2)
            if capture:
                q = output / 'owner-inputs' / name; q.parent.mkdir(parents=True, exist_ok=True)
                q.write_bytes(read_file(ROOT / name, 4 * 1024**2))
                require(file_identity(q, 4 * 1024**2) == rows[name], 'c-post-owned-source-capture')
        require(len(rows) <= 256 and sum(row['bytes'] for row in rows.values()) <= 16 * 1024**2,
                'c-post-original-source-count-byte-bounds')
        return rows
    try:
        source = source_identity(ROOT)
        head = commands.run('source-head', 'git', 'rev-parse', 'HEAD', 'HEAD^{tree}').decode().splitlines()
        require(len(head) == 2 and all(len(v) == 40 and all(c in '0123456789abcdef' for c in v) for v in head),
                'c-post-source-head-tree')
        commands.run('source-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        helpers = source_inputs(capture=True)
        result['source'] = {'head': head[0], 'tree': head[1], 'native': source, 'helpers': helpers}
        historical = read_file(ROOT / HISTORICAL, 65536)
        require(hashlib.sha256(historical).hexdigest() == HISTORICAL_SHA, 'c-post-immutable-historical-boundary-reference')
        old = json.loads(historical)
        require(old['run'] == 41204486731 and old['nativeBoundaryControlsPassed'] == 4,
                'c-post-four-historical-controls-only')
        result['historicalBoundaryControls'] = {'source': old['source'], 'run': old['run'],
            'evidence': file_identity(ROOT / HISTORICAL), 'passed': 4, 'rerunByThisProgramme': False,
            'currentSourceQualificationClaimed': False}
        stage = 'fresh-five-ordinary-native-products'
        build_root = output / 'native-build'; build_root.mkdir(mode=0o700)
        directory, receipt = build_native(commands, build_root, tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode()))
        native = {n: directory / n for n in ('latent', 'latentd', 'package', 'capsule_contracts', 'capsule_authoring')}
        result['nativeTuple'] = ordinary_tuple(receipt, native)
        stage = 'one-fresh-ordinary-component'
        sdk = inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
        project = fixture.prepare_http_standard(output / 'project')
        (project / 'src/main.c').write_bytes(read_file(ROOT / PROBE, 65536))
        original = inventory(snapshot(project))
        installed = {n: getattr(args, n.replace('-', '_')).resolve(strict=True) for n in ('zig', 'wit-bindgen', 'wasm-tools')}
        tools = {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()}
        artifact = output / 'build'
        c_capsule_build.build(project, artifact, native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', installed=installed, _deadline=commands.deadline)
        result['build'] = http_build_evidence(artifact, original, runtime_profile=FETCH_STANDARD_PROFILE)
        stage = 'four-signed-ordinary-post-cells'
        state = {'calls': 0, 'controlAttempts': 0, 'retainedBytes': 0}
        result['node'] = node.run_http(artifact, native, output / 'node', deadline=commands.deadline,
            runtime_profile=FETCH_STANDARD_PROFILE, client_kind='libfetch-post', client_state=state,
            client_deadline=float(min(commands.deadline, time.monotonic() + 240)))
        require(result['node']['status'] == 'passed'
                and [row['case'] for row in result['node']['cases']] == list(CASES), 'c-post-exact-four-outcomes')
        require(helpers == source_inputs() and source_identity(ROOT) == source
                and sdk == inventory(c_capsule_project.sdk_inputs(ROOT, threading=True))
                and original == inventory(snapshot(project))
                and result['nativeTuple'] == ordinary_tuple(receipt, native)
                and tools == {n: file_identity(p, 512 * 1024**2) for n, p in installed.items()},
                'c-post-all-actual-inputs-still-exact')
        result.update(status='passed', sharedClientCounters=state, tools=tools, commands=commands.records)
        commands.run('source-still-clean', 'git', 'diff', '--exit-code', 'HEAD', '--')
        require(time.monotonic() < commands.deadline, 'c-post-original-parent-deadline')
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
