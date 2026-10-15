#!/usr/bin/env python3
"""Finite separate signed pending-effect backup, restore and explicit no-redrive close.

Uses the same frozen native tuple, six captured inputs and original owner limits.
This creates one fresh private root and retains every failure. It does not qualify
a packaged operator distribution, immediate HTTP denial or the Phase 4 gate.
"""
from __future__ import annotations

from pathlib import Path
import sys
import time

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import run_java_transaction_http_qualification as terminal
from tools.build_observation import file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification import current_campaign, inputs, packaging, staging
from tools.java_transaction_qualification.campaign import Campaign
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient
from tools.java_transaction_qualification.pending_campaign import PendingCampaign
from tools.phase2_operator_process import bounded_receipt, read_json, write_json
from tools.rust_capsule_project import fresh

EXTRA_COLLECTORS = ('tools/run_java_pending_recovery_qualification.py',
                    'tools/java_transaction_qualification/pending_campaign.py',
                    'tools/java_transaction_qualification/pending_controls.py')


def parse():
    args = terminal.parse()
    inputs.require(args.current_selections is not None and args.current_http_endpoint is not None
                   and args.recovery_helper is not None and args.resume_candidate is None
                   and not args.prepare_authority_only, 'explicit-separate-current-pending-inputs')
    return args


def collector_identity():
    root = Path(__file__).resolve().parents[1]
    return terminal.collector_identity() | {
        name: file_identity(root / name, 'collector', 262144)['digest'] for name in EXTRA_COLLECTORS}


def run(args):
    work = fresh(args.output)
    work.chmod(0o700)
    evidence = Evidence(work / 'evidence')
    client_root = work / 'client'
    client_root.mkdir(mode=0o700)
    record = {'schemaVersion': 'latent.java-transaction.pending-recovery.v1', 'passed': False,
              'trust': 'ephemeral-native-package-test-only', 'nativeSourceCommit': args.native_source_commit,
              'recoverySourceCommit': args.recovery_source_commit, 'conductorSourceCommit': args.conductor_source_commit,
              'sourceIdentityKind': 'supplied-build-identity', 'guestCompiledAgain': False,
              'signedPendingRestoreCloseQualified': False,
              'packagedDistributionQualified': False, 'immediateHttpDenialQualified': False,
              'postStageImmediateHttpRollbackQualified': False}
    started = time.monotonic()
    stage, node, peer, client = 'identity', None, None, None
    try:
        with owned_cancellation() as cancellation:
            clock = staging.clock(args.timeout)
            deadline = staging.deadline(clock, args.timeout)
            tools, collectors = terminal.tool_identity(args), collector_identity()
            items, diagnostic = terminal.loaded_inputs(args, work)
            record.update(nativeTools=tools, collectorDigests=collectors, compilerSourceCommit=items[0].compiler_source)
            terminal.input_identity(record, items, diagnostic)
            record['currentHttpEndpoint'] = terminal.current_endpoint(args)
            record['currentHttpEndpointInput'] = file_identity(args.current_http_endpoint, 'endpoint-declaration', 8192)
            record['currentHttpInstallationInputs'] = terminal.current_installation_identity(args)
            client = RecordingClient(args.cli, client_root, cancellation, deadline, evidence, phase4=True)
            try:
                stage = 'package'
                selected = current_campaign.selections(args.portable, args.current_selections,
                                                       args.current_selections_digest)
                signed = packaging.package_current(selected, work / 'packages', args.contracts_tool, args.signer,
                    timeout=max(1, int(min(600, deadline - time.monotonic()))))
                evidence.record('actual-package-fixture', read_json(work / 'packages/package-fixture-receipt.json'))
                stage = 'bootstrap'
                peer, configuration, node = terminal.prepare_environment(client, args, work, signed,
                                                                         node_program='pending-close')
                stage = 'current-authority'
                full_path, publications, proposals, receipts = terminal.provision(
                    client, args, signed, items, peer, configuration, node)
                stage = 'actual-signed-pending-recovery'
                campaign = Campaign(client, configuration, full_path, signed, items, publications,
                                    proposals, receipts, peer, node)
                record['campaign'] = PendingCampaign(campaign, args.recovery_helper, work / 'pending-recovery').execute()
                node.stop()
                peer.stop()
                inputs.require(node.ordinal == 7 and node.restore_authority_sessions == 1
                               and len(node.shutdown) == 7 and peer.session == 1,
                               'original-bounded-pending-session-program')
                evidence.passed('actual-pending-physical-retirement', {
                    'ordinaryNodeSessions': 6, 'restoreAuthoritySessions': 1,
                    'originalNodeReports': node.shutdown, 'recipient': peer.shutdown})
                stage = 'identity-recheck'
                inputs.require(terminal.tool_identity(args) == tools and collector_identity() == collectors,
                               'qualification-input-changed')
                terminal.recheck_inputs(args, work, record)
                record.update(passed=True, signedPendingRestoreCloseQualified=True)
            finally:
                with cancellation.defer():
                    if node is not None:
                        node.close()
                    if peer is not None:
                        peer.close()
                cancellation.check()
    except BaseException as error:
        terminal.failure(record, stage, error)
        record['signedPendingRestoreCloseQualified'] = False
    finally:
        record.update(seconds=round(time.monotonic() - started, 6),
                      cliProcesses=client.calls if client else 0, measuredCases=list(evidence.cases))
        record['evidenceInventory'] = evidence.record('inventory', evidence.summary())
        write_json(work / 'campaign-receipt.json', record)
    print(bounded_receipt(record))
    return 0 if record['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(run(parse()))
