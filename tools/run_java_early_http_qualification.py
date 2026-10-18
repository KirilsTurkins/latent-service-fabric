#!/usr/bin/env python3
"""Execute one exact early-HTTP capture through fresh signed current owners.

Four node sessions, one actual command and immutable replay; no compiler,
deferred-effect grant, restore authority or packaged distribution qualification.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import run_java_transaction_http_qualification as terminal
from tools.build_observation import build_environment, file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification import configuration as cfg, early_http_campaign as campaign
from tools.java_transaction_qualification import early_http_inputs, inputs, lifecycle, packaging, policies, staging
from tools.java_transaction_qualification.current_inputs import CurrentSelection
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, native
from tools.phase2_operator_process import bounded_receipt, read_json, write_json
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import fresh, read_file

EXTRA_COLLECTORS = ('tools/run_java_early_http_qualification.py',
                    'tools/java_transaction_qualification/early_http_inputs.py',
                    'tools/java_transaction_qualification/early_http_campaign.py',
                    'docs/testing/evidence/java-early-http-rebuilt-capture-2026-10-13.json',
                    'docs/testing/evidence/java-early-http-reconstructed-capture-2026-10-15.json')


def selection(path, expected):
    require = inputs.require
    require(path.is_absolute() and path.is_file() and not path.is_symlink()
            and isinstance(expected, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', expected),
            'explicit-early-selection-input')
    raw = read_file(path, 8192)
    require(inputs.digest(raw) == expected, 'early-selection-document-changed')
    value = inputs.decode(raw, 8192)
    require(set(value) == {'schemaVersion', 'selection'}
            and value['schemaVersion'] == 'latent.java.early-http-selection.v1'
            and isinstance(value['selection'], dict)
            and set(value['selection']) == terminal_current_fields(), 'closed-single-early-selection')
    row = value['selection']
    selected = CurrentSelection(row['sourceCommit'], row['variant'], row['reportDigest'],
                                row['componentDigest'], row['compilerInputsDigest'])
    selected._validate(('forbidden-http-before-stage',))
    return selected


def terminal_current_fields():
    from tools.java_transaction_qualification.current_campaign import FIELDS
    return FIELDS


def parse():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cli', 'node', 'aot-compiler', 'contracts-tool', 'signer', 'capture', 'selection', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('selection-digest', 'native-source-commit', 'conductor-source-commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout', type=int, default=1200)
    args = parser.parse_args()
    inputs.require(sys.platform == 'linux' and sys.version_info >= (3, 13), 'linux-python313-required')
    inputs.require(0 < args.timeout <= 1200 and all(re.fullmatch(r'[0-9a-f]{40}', value)
                   for value in (args.native_source_commit, args.conductor_source_commit)),
                   'original-early-source-and-deadline')
    for name in ('cli', 'node', 'aot_compiler', 'contracts_tool', 'signer'):
        path = getattr(args, name)
        inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink(),
                       'actual-native-executable-required')
    inputs.require(args.capture.is_absolute() and args.capture.is_dir() and not args.capture.is_symlink()
                   and args.output.is_absolute(), 'explicit-early-roots')
    selection(args.selection, args.selection_digest)
    return args


def collector_identity():
    root = Path(__file__).resolve().parents[1]
    return terminal.collector_identity() | {
        name: file_identity(root / name, 'collector', 262144)['digest'] for name in EXTRA_COLLECTORS}


def package(args, item, output, timeout):
    output = fresh(output)
    commands = Commands(output, output, build_environment(output), deadline_seconds=timeout,
                        command_seconds=min(timeout, 600))
    packaging.prepare(item, output / item.name, args.contracts_tool, args.signer, commands)
    mode = signing_mode(item)
    commands.run('early-http-signing', args.signer, mode,
                 output / 'signed', item.compiler_source, output / item.name)
    releases = read_json(output / 'signed/release-set.json')
    inputs.require(releases['schemaVersion'] == 'latent.component.signing-fixture.v1'
                   and releases['trust'] == 'ephemeral-native-package-test-only'
                   and len(releases['releases']) == 1
                   and releases['releases'][0]['componentDigest'] == item.component_digest
                   and releases['releases'][0]['name'] == 'java718-' + item.name,
                   'exact-single-early-signed-package')
    write_json(output / 'package-fixture-receipt.json', {'passed': True, 'commands': commands.records,
        'input': item.observation(), 'guestCompiledAgain': False, 'signedExecutionQualified': False})
    return output / 'signed'


def signing_mode(item):
    packet = read_json(Path(__file__).resolve().parents[1] /
        'docs/testing/evidence/java-early-http-rebuilt-capture-2026-10-13.json')
    report = inputs.digest(read_file(item.directory / 'report.json', 262144))
    if report == 'sha256:bd40833f7f527f42d5f4a088cbcc093bdcd023060e91fb948f2505f8aaf5d2b7':
        reconstructed = read_json(Path(__file__).resolve().parents[1] /
            'docs/testing/evidence/java-early-http-reconstructed-capture-2026-10-15.json')
        inputs.require(report == reconstructed['materials']['report']['sha256']
                       and item.compiler_source == reconstructed['sourceCommit']
                       and item.component_digest == reconstructed['materials']['component']['sha256'],
                       'reconstructed-early-captured-component-and-source')
        return 'fixture-sign-reconstructed-early-http-input'
    rebuilt = packet['materials']['report']['sha256']
    if report == rebuilt:
        inputs.require(item.compiler_source == packet['sourceCommit']
                       and item.component_digest == packet['materials']['component']['sha256'],
                       'rebuilt-early-captured-component-and-source')
        return 'fixture-sign-rebuilt-early-http-input'
    return 'fixture-sign-early-http-input'


def publish(client, signed, item):
    releases = read_json(signed / 'release-set.json')
    inputs.require(int(releases['expiresAtUnixSeconds']) > time.time() + 300, 'fresh-early-synthetic-trust')
    root = signed / ('java718-' + item.name)
    operation = 'java-early-http-publish'
    data = client.call('release', 'publish-package', root / 'package', '--evidence', root / 'evidence/index.json',
        '--operation-id', operation, '--expected-generation', '0')['data']
    actual = data['operation']
    publication = actual['publication']['id']
    inputs.require(data['release']['digest'] == item.component_digest
                   and re.fullmatch(r'publication:sha256:[0-9a-f]{64}', publication)
                   and client.call('release', 'operation', operation)['data']['receipt'] == actual,
                   'actual-early-admission-and-operation-replay')
    client.evidence.passed('publish-early-http', {'admission': actual, 'componentDigest': item.component_digest})
    return publication


def run(args):
    work = fresh(args.output)
    work.chmod(0o700)
    evidence = Evidence(work / 'evidence')
    client_root = work / 'client'
    client_root.mkdir(mode=0o700)
    record = {'schemaVersion': 'latent.java.early-http-qualification.v1', 'passed': False,
        'trust': 'ephemeral-native-package-test-only', 'nativeSourceCommit': args.native_source_commit,
        'conductorSourceCommit': args.conductor_source_commit, 'sourceIdentityKind': 'supplied-build-identity',
        'guestCompiledAgain': False, 'signedGuestExecutionQualified': False,
        'immediateHttpDenialQualified': False, 'postStageRollbackQualified': False,
        'packagedDistributionQualified': False}
    started = time.monotonic()
    stage, client, node = 'identity', None, None
    try:
        with owned_cancellation() as cancellation:
            clock = staging.clock(args.timeout)
            deadline = staging.deadline(clock, args.timeout)
            selected = selection(args.selection, args.selection_digest)
            item = early_http_inputs.load(args.capture, selected)
            tools = {name: file_identity(getattr(args, name), name, 1073741824)
                     for name in ('cli', 'node', 'aot_compiler', 'contracts_tool', 'signer')}
            collectors = collector_identity()
            record.update(nativeTools=tools, collectorDigests=collectors, input=item.observation(),
                          compilerSourceCommit=item.compiler_source, selectionDigest=args.selection_digest)
            client = RecordingClient(args.cli, client_root, cancellation, deadline, evidence, phase4=True)
            primary = None
            try:
                stage = 'package'
                signed = package(args, item, work / 'packages', max(1, int(min(600, deadline - time.monotonic()))))
                evidence.record('early-signed-package', read_json(work / 'packages/package-fixture-receipt.json'))
                stage = 'bootstrap'
                native(client, args.signer, 'early-tls', 'fixture-tls', work / 'tls')
                credentials = work / 'credentials'
                credentials.mkdir(mode=0o700)
                credential = credentials / 'unused-http-credential'
                with credential.open('xb') as output:
                    output.write(b'LSF-PUBLIC-EARLY-HTTP-TEST-ONLY')
                credential.chmod(0o600)
                node_root = work / 'node'
                node_root.mkdir(mode=0o700)
                # Current protected clock owns initialization. No collector
                # checkpoint or deferred dispatcher is selected by this fixture.
                configuration = cfg.configure(node_root, signed, args.aot_compiler, work / 'tls', None,
                    52027, credential, protected_clock_only=True)
                configuration.value['providers']['http'].pop('deferred', None)
                for binding in configuration.value['providers']['bindings']:
                    binding['consumerService'] = campaign.SERVICE
                bootstrap = node_root / 'early-bootstrap.json'
                write_json(bootstrap, configuration.value)
                configuration = cfg.Configuration(bootstrap, configuration.value,
                                                  configuration.authority, configuration.recipient_origin)
                node = lifecycle.Node(client, args.node, node_root, current_publication_program=True,
                                      current_program='early-http')
                stage = 'publish'
                node.start(configuration.path, current_session='publish')
                publication = publish(client, signed, item)
                node.stop()
                lifecycle.admission_lease_interval(client)
                rows = campaign.operations(item, publication)
                path = configuration.selected(node_root / 'early-runtime.json', rows)
                stage = 'inspection'
                hosts = inputs.decode(native(client, args.node, 'early-host-inspection', 'inspect-transaction-hosts',
                                             '--config', path, timeout=120), 262144)
                documents = campaign.proposals(hosts, publication)
                evidence.record('early-native-hosts', hosts)
                evidence.record('early-policy-proposals', documents)
                lifecycle.admission_lease_interval(client)
                stage = 'authority'
                node.start(configuration.path, current_session='authority')
                receipts = policies.apply(client, documents)
                target = campaign.metadata(client, signed, item, publication, documents['deploymentGrants'])
                campaign.bind_routes(client, configuration.authority, item, target)
                node.stop()
                lifecycle.admission_lease_interval(client)
                stage = 'namespace-create'
                node.start(path, current_session='namespace-create')
                lifecycle.create_namespace(client, item, publication)
                node.stop()
                lifecycle.admission_lease_interval(client)
                stage = 'actual-early-http'
                node.start(path, current_session='early-http-runtime')
                record['campaign'] = campaign.execute(client, configuration, path, signed, item,
                                                      publication, documents, receipts, node)
                inputs.require(node.ordinal == 4 and node.restore_authority_sessions == 0 and len(node.shutdown) == 4,
                               'exact-early-four-retired-sessions')
                evidence.passed('early-physical-retirement', {'nodeSessions': node.shutdown})
                stage = 'identity-recheck'
                inputs.require(early_http_inputs.load(args.capture, selection(args.selection, args.selection_digest)) == item
                    and collector_identity() == collectors
                    and {name: file_identity(getattr(args, name), name, 1073741824) for name in tools} == tools,
                    'early-qualification-input-changed')
                record.update(passed=True, signedGuestExecutionQualified=True, immediateHttpDenialQualified=True)
            except BaseException as error:
                primary = error
                raise
            finally:
                terminal.close_owners(record, cancellation, node, None, primary=primary)
    except BaseException as error:
        terminal.failure(record, stage, error)
        record['immediateHttpDenialQualified'] = False
    finally:
        record.update(seconds=round(time.monotonic() - started, 6), cliProcesses=client.calls if client else 0,
                      measuredCases=list(evidence.cases))
        if not terminal.finalize_inventory(record, evidence, 'inventory'):
            record['immediateHttpDenialQualified'] = False
        write_json(work / 'campaign-receipt.json', record)
    print(bounded_receipt(record))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(run(parse()))
