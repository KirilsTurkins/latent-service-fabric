#!/usr/bin/env python3
"""Run one exact signed Java state-value component with native witnesses.

This isolated fixture grants only state, staging and deferred-dispatch authority;
no immediate HTTP authority is granted to the guest. It retains failed evidence.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import socket
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import run_java_transaction_http_qualification as terminal
from tools import run_java_early_http_qualification as early
from tools.build_observation import build_environment, file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification import configuration as cfg, current_recipient, diagnostic_campaign
from tools.java_transaction_qualification import http, inputs, lifecycle, packaging, policies, acceptance_inputs, staging
from tools.java_transaction_qualification.campaign import Campaign, command_input, precondition, rpc_result
from tools.java_transaction_qualification.current_inputs import CurrentSelection
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, native
from tools.phase2_operator_process import bounded_receipt, read_json, write_json
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import fresh, read_file

NAME = 'put-once-values'
COLLECTORS = ('tools/run_java_values_qualification.py',
              'tools/java_transaction_qualification/acceptance_inputs.py',
              'docs/testing/evidence/java-values-capture-5f-2026-11-05.json')


def selection(path, expected):
    inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink()
                   and re.fullmatch(r'sha256:[0-9a-f]{64}', expected or ''), 'explicit-values-selection')
    raw = read_file(path, 8192)
    inputs.require(inputs.digest(raw) == expected, 'values-selection-digest')
    value = inputs.decode(raw, 8192)
    inputs.require(set(value) == {'schemaVersion', 'selection'}
                   and value['schemaVersion'] == 'latent.java.values-selection.v1'
                   and isinstance(value['selection'], dict)
                   and set(value['selection']) == early.terminal_current_fields(), 'closed-values-selection')
    row = value['selection']
    result = CurrentSelection(row['sourceCommit'], row['variant'], row['reportDigest'],
                              row['componentDigest'], row['compilerInputsDigest'])
    result._validate((NAME,))
    return result


def operations(item, publication, incarnation):
    raw = read_file(item.directory / 'project/transaction-binding.json', 131072)
    companion = inputs.decode(raw)
    inputs.require(inputs.digest(raw) == item.companion_digest and item.name == NAME
        and item.requirements_digest is not None and companion['capsule'] == cfg.SERVICE
        and companion['deployment'] == companion['binding'] == cfg.DEPLOYMENT
        and companion['namespace'] == cfg.NAMESPACE
        and re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication)
        and re.fullmatch(r'[0-9a-f]{64}', incarnation), 'values-original-operation-identities')
    inputs.require(companion['operations'] == [
        {'operation': name, 'mode': 'strict-command' if name == 'update' else 'fresh-query',
         'inputFormat': 'lsf-wit-values-v1', 'resultFormat': 'lsf-wit-values-v1'}
        for name in ('update', 'query', 'scan')], 'values-exact-operations')
    rows = []
    for name in ('update', 'query', 'scan'):
        row = {'tenant': cfg.TENANT, 'componentDigest': item.component_digest, 'publication': publication,
            'contract': cfg.CONTRACT, 'function': name, 'deployment': cfg.DEPLOYMENT, 'route': cfg.DEPLOYMENT,
            'binding': cfg.DEPLOYMENT, 'companionDigest': item.companion_digest, 'incarnation': 1,
            'resultPolicy': cfg.RESULT_POLICY, 'statePolicies': [cfg.STATE_POLICY]}
        if name == 'update':
            row['deferredHttp'] = {'requirementsDigest': item.requirements_digest, 'providerId': 'http',
                'providerIncarnation': incarnation, 'credentialReference': 'java-current-http',
                'stagingBinding': 'java-staging-installed', 'stagingPolicies': [cfg.STAGING_POLICY],
                'dispatchBinding': 'java-dispatch-installed', 'dispatchPolicies': [cfg.DISPATCH_POLICY],
                'dispatchAuthority': {'formatVersion': 1, 'mode': 'signed-service-integration'}}
        rows.append(row)
    return rows


def package(args, item, output, timeout):
    output = fresh(output)
    commands = Commands(output, output, build_environment(output), deadline_seconds=timeout,
                        command_seconds=min(timeout, 600))
    packaging.prepare(item, output / NAME, args.contracts_tool, args.signer, commands)
    commands.run('values-signing', args.signer, 'fixture-sign-java-values-input',
                 output / 'signed', item.compiler_source, output / NAME)
    releases = read_json(output / 'signed/release-set.json')
    inputs.require(releases['schemaVersion'] == 'latent.component.signing-fixture.v1'
        and releases['trust'] == 'ephemeral-native-package-test-only' and len(releases['releases']) == 1
        and releases['releases'][0]['componentDigest'] == item.component_digest
        and releases['releases'][0]['name'] == 'java718-' + NAME, 'exact-values-signed-package')
    write_json(output / 'package-fixture-receipt.json', {'passed': True, 'commands': commands.records,
        'input': item.observation(), 'guestCompiledAgain': False, 'signedExecutionQualified': False})
    return output / 'signed'


def execute(client, configuration, path, signed, item, publication, documents, receipts, peer, node):
    campaign = Campaign(client, configuration, path, signed, (item,), {NAME: publication}, documents, receipts, peer, node)
    before, current = campaign.query(0)
    inputs.require(current['key-version'] == {'none': None}, 'values-initial-key-absent')
    observed = []
    for key, selector, expected in (('java-values-high-bit', 4294967280, 9223372036854775808),
                                    ('java-values-unsigned-maximum', 4294967281, 18446744073709551615)):
        condition = precondition(current)
        body = command_input(selector)
        result = campaign.result(campaign.socket('command', original_key=key, body=body, condition=condition))
        inputs.require(result['disposition'] == 'committed' and http.aggregate(result)['count'] == str(expected),
                       'actual-full-width-unsigned-command-result')
        durable = lifecycle.lookup(client, publication, key)
        rpc_result(durable, result, publication, key)
        effect = campaign.wait_effect(publication, key, result)
        recipient = campaign.peer_record(result['effect-ids'][0])
        replay = campaign.result(campaign.socket('command', original_key=key, body=body, condition=condition))
        http.replay(result, replay)
        query, current = campaign.query(expected)
        # The guest throws unless the UTF-8 key/value and absent option survive
        # a fresh query; each entry also enforces a new static instance.
        observed.append({'command': result, 'durable': durable, 'effect': effect,
                         'recipientAcceptance': recipient, 'query': query, 'replay': replay})
    node.stop()
    peer.stop()
    client.evidence.passed('signed-java-state-value-roundtrips', {'before': before, 'cases': observed,
        'recipientDeliveryQualified': False})
    return {'before': before, 'cases': observed, 'recipientDeliveryQualified': False}


def parse():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cli', 'node', 'aot-compiler', 'contracts-tool', 'signer', 'capture', 'selection',
                 'current-http-endpoint', 'current-http-installation', 'current-http-tls', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('selection-digest', 'native-source-commit', 'conductor-source-commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    inputs.require(sys.platform == 'linux' and sys.version_info >= (3, 13)
        and 0 < args.timeout <= 1200 and all(re.fullmatch(r'[0-9a-f]{40}', value)
        for value in (args.native_source_commit, args.conductor_source_commit)), 'explicit-values-linux-sources')
    for name in ('cli', 'node', 'aot_compiler', 'contracts_tool', 'signer'):
        path = getattr(args, name)
        inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink(), 'actual-native-executable')
    inputs.require(args.capture.is_absolute() and args.capture.is_dir() and not args.capture.is_symlink()
                   and args.output.is_absolute(), 'explicit-values-roots')
    selection(args.selection, args.selection_digest)
    terminal.current_endpoint(args)
    terminal.current_installation(args)
    return args


def collector_identity():
    root = Path(__file__).resolve().parents[1]
    return terminal.collector_identity() | {
        name: file_identity(root / name, 'collector', 262144)['digest'] for name in COLLECTORS}


def environment(client, args, work, signed, item):
    endpoint = terminal.current_endpoint(args)
    installation = terminal.current_installation(args)
    tls = work / 'tls'
    tls.mkdir(mode=0o700)
    for name in ('ca.der', 'server.pem', 'key.pem'):
        with (tls / name).open('xb') as target:
            target.write(read_file(args.current_http_tls / name, 65536))
        (tls / name).chmod(0o600)
    credential_root = work / 'credentials'
    credential_root.mkdir(mode=0o700)
    credential = credential_root / 'put-once-header'
    with credential.open('xb') as output:
        output.write(b'Bearer ' + os.urandom(32).hex().encode())
    credential.chmod(0o600)
    recipient_root, node_root = work / 'recipient', work / 'node'
    recipient_root.mkdir(mode=0o700)
    node_root.mkdir(mode=0o700)
    declaration = work / 'current-http-endpoint.json'
    write_json(declaration, endpoint)
    declaration.chmod(0o600)
    peer = lifecycle.Peer(client, recipient_root, tls, credential, endpoint['endpointIncarnation'],
                          port=endpoint['origin']['port'], current_declaration=declaration)
    try:
        configuration = cfg.configure(node_root, signed, args.aot_compiler, tls, None, peer.port, credential,
                                      deferred_endpoint=endpoint, current_http_installation=installation)
        preview = inputs.decode(native(client, args.node, 'values-http-native-preview',
            'inspect-configured-http-effects', '--config', configuration.path, timeout=120), 65536)
        inputs.require(set(preview) == {'schemaVersion', 'adapters'}
            and preview['schemaVersion'] == 'latent.configured-http-effect-inspection.v1'
            and len(preview['adapters']) == 1, 'actual-java-values-preview')
        marker = inputs.decode(read_file(item.directory / 'project/java-current-http-profile.json', 8192))
        inputs.require(preview['adapters'][0]['profile']['idempotency_profile'] == marker['idempotencyProfile'],
                       'actual-values-profile-matches-capture')
        client.evidence.record('values-native-preview', preview)
        lifecycle.admission_lease_interval(client)
        node = lifecycle.Node(client, args.node, node_root, current_publication_program=True,
                              current_program='early-http')
        return peer, configuration, node
    except BaseException:
        peer.close()
        raise


def run(args):
    work = fresh(args.output)
    work.chmod(0o700)
    evidence = Evidence(work / 'evidence')
    client_root = work / 'client'
    client_root.mkdir(mode=0o700)
    record = {'schemaVersion': 'latent.java.values-qualification.v1', 'passed': False,
        'trust': 'ephemeral-native-package-test-only', 'nativeSourceCommit': args.native_source_commit,
        'conductorSourceCommit': args.conductor_source_commit, 'sourceIdentityKind': 'supplied-build-identity',
        'guestCompiledAgain': False, 'signedGuestExecutionQualified': False,
        'valueRoundtripQualified': False, 'packagedDistributionQualified': False}
    started = time.monotonic()
    stage, node, peer, client = 'identity', None, None, None
    try:
        with owned_cancellation() as cancellation:
            clock = staging.clock(args.timeout)
            deadline = staging.deadline(clock, args.timeout)
            selected = selection(args.selection, args.selection_digest)
            item = acceptance_inputs.load(args.capture, selected)
            tools = {name: file_identity(getattr(args, name), name, 1073741824)
                     for name in ('cli', 'node', 'aot_compiler', 'contracts_tool', 'signer')}
            collectors = collector_identity()
            record.update(nativeTools=tools, collectorDigests=collectors, input=item.observation(),
                compilerSourceCommit=item.compiler_source, selectionDigest=args.selection_digest,
                currentHttpEndpoint=terminal.current_endpoint(args),
                currentHttpInstallationInputs=terminal.current_installation_identity(args))
            client = RecordingClient(args.cli, client_root, cancellation, deadline, evidence, phase4=True)
            primary = None
            try:
                stage = 'package'
                signed = package(args, item, work / 'packages', max(1, int(min(600, deadline - time.monotonic()))))
                evidence.record('values-signed-package', read_json(work / 'packages/package-fixture-receipt.json'))
                stage = 'bootstrap'
                peer, configuration, node = environment(client, args, work, signed, item)
                stage = 'publish'
                node.start(configuration.path, current_session='publish')
                publication = early.publish(client, signed, item)
                node.stop()
                lifecycle.admission_lease_interval(client)
                rows = operations(item, publication, peer.incarnation)
                path = configuration.selected(configuration.path.parent / 'values-runtime.json', rows)
                stage = 'inspection'
                value = inputs.decode(native(client, args.node, 'values-host-inspection',
                    'inspect-transaction-hosts', '--config', path, timeout=120), 262144)
                hosts = policies.ObservedHosts.read(value, rows, intent_operation='http', single_http=True)
                documents = policies.documents(hosts, {NAME: publication}, current_http_endpoint=terminal.current_endpoint(args),
                                               single_http=True)
                inputs.require({row['capability'] for row in documents['deploymentGrants']} == {
                    policies.STATE_CONTRACT, policies.INTENT_CONTRACT, *[v[0] for v in cfg.CLOCKS.values()]},
                    'values-guest-has-no-immediate-http-grant')
                evidence.record('values-native-hosts', value)
                evidence.record('values-policy-proposals', documents)
                lifecycle.admission_lease_interval(client)
                stage = 'authority'
                node.start(configuration.path, current_session='authority')
                receipts = policies.apply(client, documents)
                lifecycle.deploy(client, signed, item, publication, documents['deploymentGrants'], configuration.authority)
                node.stop()
                lifecycle.admission_lease_interval(client)
                stage = 'namespace-create'
                node.start(path, current_session='namespace-create')
                lifecycle.create_namespace(client, item, publication)
                node.stop()
                lifecycle.admission_lease_interval(client)
                stage = 'actual-java-values'
                node.start(path, current_session='early-http-runtime')
                record['campaign'] = execute(client, configuration, path, signed, item, publication,
                                             documents, receipts, peer, node)
                inputs.require(node.ordinal == 4 and node.restore_authority_sessions == 0 and len(node.shutdown) == 4,
                               'exact-values-four-retired-sessions')
                evidence.passed('values-physical-retirement', {'nodeSessions': node.shutdown, 'recipient': peer.shutdown})
                stage = 'identity-recheck'
                inputs.require(acceptance_inputs.load(args.capture, selection(args.selection, args.selection_digest)) == item
                    and collector_identity() == collectors
                    and {name: file_identity(getattr(args, name), name, 1073741824) for name in tools} == tools,
                    'values-qualification-input-changed')
                record.update(passed=True, signedGuestExecutionQualified=True, valueRoundtripQualified=True)
            except BaseException as error:
                primary = error
                raise
            finally:
                terminal.close_owners(record, cancellation, node, peer, primary=primary)
    except BaseException as error:
        terminal.failure(record, stage, error)
        record['valueRoundtripQualified'] = False
    finally:
        record.update(seconds=round(time.monotonic() - started, 6), cliProcesses=client.calls if client else 0,
                      measuredCases=list(evidence.cases))
        if not terminal.finalize_inventory(record, evidence, 'inventory'):
            record['valueRoundtripQualified'] = False
        write_json(work / 'campaign-receipt.json', record)
    print(bounded_receipt(record))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(run(parse()))
