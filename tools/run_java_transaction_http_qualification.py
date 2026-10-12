#!/usr/bin/env python3
"""Qualify preserved signed Java guests using actual already-built Phase 4 owners.

The current version-2 startup declaration is explicit; HTTP installation and
offline recovery observations still require the current installed owners.
A refusal remains failed evidence.

Linux/Python 3.13. This creates one private disposable root and retains every
failed attempt. It invokes no compiler, installs no inferred grant and cannot
qualify a packaged developer distribution or the full Phase 4 completion gate.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import sys
import time

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import file_identity
from tools.build_process_signals import owned_cancellation
from tools.java_transaction_qualification import configuration as cfg, inputs, lifecycle, packaging, policies, staging
from tools.java_transaction_qualification import diagnostic_inputs
from tools.java_transaction_qualification.campaign import Campaign
from tools.java_transaction_qualification.evidence import Evidence, RecordingClient, native
from tools.java_transaction_qualification.offline_campaign import OfflineCampaign
from tools.phase2_operator_process import bounded_receipt, read_json, write_json
from tools.rust_capsule_project import fresh

COLLECTORS = ("tools/run_java_transaction_http_qualification.py", "tools/phase2_operator_process.py",
    "tools/phase2_operator_scenario.py", "tools/build_process_linux.py", "tools/build_process_signals.py",
    "tools/static_api/node.py", "tools/java_transaction_qualification/inputs.py",
    "tools/java_transaction_qualification/packaging.py", "tools/java_transaction_qualification/evidence.py",
    "tools/java_transaction_qualification/configuration.py", "tools/java_transaction_qualification/policies.py",
    "tools/java_transaction_qualification/lifecycle.py", "tools/java_transaction_qualification/http.py",
    "tools/java_transaction_qualification/campaign.py", "tools/java_transaction_qualification/provider.py",
    "tools/java_transaction_qualification/recovery.py", "tools/java_transaction_qualification/offline_campaign.py",
    "tools/java_transaction_qualification/staging.py", "tools/java_transaction_qualification/native_store.py",
    "tools/java_transaction_qualification/diagnostic_inputs.py",
    "tools/java_transaction_qualification/diagnostic_campaign.py",
    "tools/java_transaction_qualification/current_inputs.py",
    "tools/java_transaction_qualification/current_campaign.py")
COLLECTORS += ("tools/java_transaction_qualification/refusal_observation.py",
               "tools/java_transaction_qualification/state_configuration.py",
               "tools/java_transaction_qualification/restore_installation.py",
               "tools/java_transaction_qualification/restore_authority.py",
               "tools/java_transaction_qualification/current_recipient.py")
REMAINING = ["reviewed-schema-and-restore-original-results", "trap-and-fuel-after-staging",
             "cancellation-before-commit", "memory-exhaustion-before-commit", "crash-before-commit",
             "pending-effect-restore-reconciliation", "full-retention-horizon-expiry",
             "authenticated-clean-host-packaged-distribution"]


def parse():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cli", "node", "aot-compiler", "contracts-tool", "signer", "portable", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--native-source-commit", required=True, help="Exact source supplied by the binary build owner")
    parser.add_argument("--conductor-source-commit", required=True, help="Separate frozen collector source identity")
    parser.add_argument("--recovery-helper", type=Path, help="Optional actual installed native recovery executable")
    parser.add_argument("--recovery-source-commit", help="Must match the original coherent native build source")
    parser.add_argument("--prepare-authority-only", action="store_true", help="Stop before candidate policy mutations")
    parser.add_argument("--resume-candidate", type=Path, help="Consume the exact stopped original candidate once")
    parser.add_argument("--candidate-digest", help="Exact retained candidate digest supplied after review")
    parser.add_argument("--current-selections", type=Path, help="Separate explicit current six-component material selections")
    parser.add_argument("--current-selections-digest", help="Exact selection-document digest; historical r3 pins remain unchanged")
    parser.add_argument("--current-http-endpoint", type=Path,
                        help="Explicit current endpoint declaration matching the fresh six-component captures")
    parser.add_argument("--current-http-installation", type=Path,
                        help="Exact complete HTTP installation used by the native constructor preview")
    parser.add_argument("--current-http-tls", type=Path,
                        help="Exact private test TLS fixture corresponding to the selected installation roots")
    for name in diagnostic_inputs.ARGUMENTS:
        parser.add_argument("--" + name.replace("_", "-"), type=Path if name in
                            {"diagnostic_capture", "diagnostic_receipt"} else str,
                            help="Optional separate compiler capture; all six diagnostic inputs must be pinned")
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    inputs.require(sys.platform == "linux" and sys.version_info >= (3, 13), "linux-python313-required")
    inputs.require(0 < args.timeout <= 1200
                   and all(re.fullmatch(r"[0-9a-f]{40}", value)
                           for value in (args.native_source_commit, args.conductor_source_commit)),
                   "original-qualification-source-and-deadline")
    for name in ("cli", "node", "aot_compiler", "contracts_tool", "signer"):
        path = getattr(args, name)
        inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink(), "actual-native-executable-required")
    inputs.require(args.portable.is_absolute() and args.portable.is_dir() and not args.portable.is_symlink()
                   and args.output.is_absolute(), "original-qualification-roots")
    recovery_input(args)
    diagnostic_inputs.selection(args)
    staging.mode(args)
    current_mode(args)
    return args


def current_mode(args):
    selected = getattr(args, "current_selections", None)
    selected_digest = getattr(args, "current_selections_digest", None)
    inputs.require((selected is None) == (selected_digest is None), "paired-current-java-campaign-inputs")
    if getattr(args, "current_http_endpoint", None) is not None:
        inputs.require(selected is not None, "current-http-requires-explicit-current-captures")
        current_endpoint(args)
        current_installation(args)
    else:
        inputs.require(getattr(args, "current_http_installation", None) is None
                       and getattr(args, "current_http_tls", None) is None,
                       "current-installation-requires-explicit-endpoint")
    if selected is not None:
        inputs.require(args.resume_candidate is None and not args.prepare_authority_only
                       and all(getattr(args, name, None) is None for name in diagnostic_inputs.ARGUMENTS),
                       "current-campaign-cannot-adopt-historical-candidate-or-diagnostic")
        from tools.java_transaction_qualification import current_campaign
        current_campaign.selections(args.portable, selected, selected_digest)


def current_endpoint(args):
    path = getattr(args, "current_http_endpoint", None)
    if path is None:
        return None
    from tools.java_transaction_qualification.current_recipient import endpoint
    inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink(),
                   "explicit-current-http-endpoint-file")
    from tools.rust_capsule_project import read_file
    value = inputs.decode(read_file(path, 8192), 8192)
    inputs.require(isinstance(value, dict)
                   and value == endpoint(value["origin"], value["endpointIncarnation"]),
                   "closed-current-http-endpoint")
    return value


def current_installation(args):
    from tools.rust_capsule_project import read_file
    path, tls = getattr(args, "current_http_installation", None), getattr(args, "current_http_tls", None)
    inputs.require(isinstance(path, Path) and path.is_absolute() and path.is_file() and not path.is_symlink()
                   and isinstance(tls, Path) and tls.is_absolute() and tls.is_dir() and not tls.is_symlink(),
                   "explicit-current-installation-and-tls-inputs")
    value = inputs.decode(read_file(path, 65536), 65536)
    inputs.require(isinstance(value, dict) and set(value) == {
                       "identity", "configuration", "credentialDirectory", "credentials", "deferred"}
                   and value["identity"] == {"id": "http", "tenant": cfg.TENANT, "service": "runtime-host", "epoch": 1}
                   and value["deferred"] == [current_endpoint(args)]
                   and isinstance(value["credentials"], list) and len(value["credentials"]) == 1,
                   "closed-current-http-installation")
    credential = value["credentials"][0]
    inputs.require(isinstance(credential, dict) and set(credential) == {"reference", "file", "destination", "header"}
                   and credential["reference"] == "java-current-http"
                   and type(credential["destination"]) is int and credential["destination"] == 0
                   and credential["header"] == "authorization",
                   "exact-current-http-credential-reference")
    configuration = value["configuration"]
    inputs.require(isinstance(configuration, dict) and set(configuration) == {
                       "formatVersion", "publicRoots", "extraRoots", "limits", "destinations"}
                   and type(configuration["formatVersion"]) is int and configuration["formatVersion"] == 1
                   and configuration["publicRoots"] is False
                   and configuration["extraRoots"] == [list(read_file(tls / "ca.der", 65536))]
                   and configuration["limits"] == {
                       "maximumRequestBodyBytes": 27, "maximumResponseBodyBytes": 2048,
                       "maximumEncodedResponseBytes": 2048, "maximumHeaderBytes": 8192,
                       "maximumHeaders": 32, "maximumRedirects": 0},
                   "exact-current-http-configured-roots-and-ceilings")
    for name in ("ca.der", "server.pem", "key.pem"):
        read_file(tls / name, 65536)
    return value


def current_installation_identity(args):
    current_installation(args)
    return {"installation": file_identity(args.current_http_installation, "http-installation", 65536),
            "tls": {name: file_identity(args.current_http_tls / name, "test-tls-input", 65536)
                    for name in ("ca.der", "server.pem", "key.pem")}}


def recovery_input(args):
    inputs.require((args.recovery_helper is None) == (args.recovery_source_commit is None),
                   "paired-native-recovery-inputs-required")
    if args.recovery_helper is not None:
        path = args.recovery_helper
        inputs.require(path.is_absolute() and path.is_file() and not path.is_symlink()
                       and args.recovery_source_commit == args.native_source_commit,
                       "coherent-original-native-recovery-source-required")


def tool_identity(args):
    names = ("cli", "node", "aot_compiler", "contracts_tool", "signer")
    if args.recovery_helper is not None:
        names += ("recovery_helper",)
    return {name: file_identity(getattr(args, name), name, 1073741824) for name in names}


def collector_identity():
    root = Path(__file__).resolve().parents[1]
    return {name: file_identity(root / name, "collector", 262144)["digest"] for name in COLLECTORS}


def prepare_environment(client, args, work, signed):
    endpoint = current_endpoint(args)
    installation = None
    if endpoint is None:
        native(client, args.signer, "fixture-tls", "fixture-tls", work / "tls")
    else:
        from tools.rust_capsule_project import read_file
        installation = current_installation(args)
        tls = work / "tls"
        tls.mkdir(mode=0o700)
        for name in ("ca.der", "server.pem", "key.pem"):
            with (tls / name).open("xb") as target:
                target.write(read_file(args.current_http_tls / name, 65536))
            (tls / name).chmod(0o600)
    if endpoint is None:
        native(client, args.signer, "fixture-clock", "fixture-state-clock", work / "clock", lifecycle.NODE_ID)
        clock = read_json(work / "clock/clock-bootstrap.json")
        checkpoint = work / "clock/state-clock.json"
        client.evidence.record("fresh-native-clock", clock)
    else:
        checkpoint = None
        client.evidence.record("current-protected-state-clock-selection", {
            "owner": "native-version-2-protected-state-owner", "collectorGeneratedCheckpoint": False})
    credential_root = work / "credentials"
    credential_root.mkdir(mode=0o700)
    token = os.urandom(32).hex().encode()
    credential = credential_root / "put-once-header"
    with credential.open("xb") as output:
        # The shared native credential owner injects this exact header value;
        # it does not invent an authentication scheme from a secret file.
        output.write(b"Bearer " + token)
    credential.chmod(0o600)
    peer_token = work / "recipient-token"
    with peer_token.open("xb") as output:
        output.write(token)
    peer_token.chmod(0o600)
    recipient_root, node_root = work / "recipient", work / "node"
    recipient_root.mkdir(mode=0o700)
    node_root.mkdir(mode=0o700)
    if endpoint is None:
        peer = lifecycle.Peer(client, recipient_root, work / "tls", peer_token, os.urandom(32).hex())
    else:
        declaration = work / "current-http-endpoint.json"
        write_json(declaration, endpoint)
        declaration.chmod(0o600)
        peer = lifecycle.Peer(client, recipient_root, work / "tls", credential, endpoint["endpointIncarnation"],
                              port=endpoint["origin"]["port"], current_declaration=declaration)
    try:
        selection = {} if endpoint is None else {"deferred_endpoint": endpoint,
                                                 "current_http_installation": installation}
        configuration = cfg.configure(node_root, signed, args.aot_compiler, work / "tls", checkpoint,
                                      peer.port, credential, **selection)
        client.evidence.record("bootstrap-configuration", configuration.value)
        if endpoint is not None:
            preview = inputs.decode(native(client, args.node, "current-http-native-preview",
                "inspect-configured-http-effects", "--config", configuration.path, timeout=120), 65536)
            inputs.require(isinstance(preview, dict) and set(preview) == {"schemaVersion", "adapters"}
                           and preview["schemaVersion"] == "latent.configured-http-effect-inspection.v1"
                           and isinstance(preview["adapters"], list) and len(preview["adapters"]) == 1,
                           "actual-current-configured-http-preview")
            profile = preview["adapters"][0]["profile"]["idempotency_profile"]
            from tools.transaction_guest_project import CURRENT_HTTP_PROFILE
            from tools.java_transaction_qualification import current_campaign
            selected, _diagnostic = current_campaign.load(args)
            for item in selected:
                if item.requirements_digest:
                    marker = inputs.decode(read_file(item.directory / "project" / CURRENT_HTTP_PROFILE, 8192), 8192)
                    inputs.require(marker["idempotencyProfile"] == profile,
                                   "actual-current-preview-matches-every-captured-http-profile")
            client.evidence.record("actual-current-http-constructor-preview", preview)
        return peer, configuration, lifecycle.Node(client, args.node, node_root)
    except BaseException:
        peer.close()
        raise


def prepare_authority(client, args, signed, items, peer, configuration, node, *, retained=False):
    node.start(configuration.path)
    publications = lifecycle.publish(client, signed, items)
    catalog = staging.catalog(client, publications) if retained else None
    node.stop()
    lifecycle.admission_lease_interval(client)
    selection = {} if not getattr(peer, "current_http", False) else {"credential_reference": "java-current-http"}
    operations = cfg.installed(items, publications, peer.incarnation, **selection)
    diagnostic = any(item.name == diagnostic_inputs.NAME for item in items)
    full_path = configuration.selected(configuration.path.parent / "installed-node.json", operations, diagnostic=diagnostic)
    selection = {} if not getattr(peer, "current_http", False) else {"intent_operation": "http"}
    hosts = lifecycle.inspect(client, args.node, full_path, operations, **selection)
    proposals = policies.documents(hosts, publications, diagnostic=diagnostic)
    client.evidence.record("actual-native-hosts", hosts.value)
    client.evidence.record("reviewed-policy-proposals", proposals)
    mutations = policies.prepare_mutations(client, proposals) if retained else None
    if retained:
        client.evidence.record("reviewed-policy-mutations", mutations)
    return full_path, publications, proposals, catalog, hosts.value, mutations


def admit_authority(client, signed, items, configuration, node, full_path, publications, proposals):
    # Explicit normal authenticated mutations turn these proposals into actual
    # current decisions. The inspection and configuration alone grant nothing.
    node.start(configuration.path)
    actual_receipts = policies.apply(client, proposals)
    client.evidence.record("authenticated-policy-receipts", actual_receipts)
    legacy = next(item for item in items if item.name == "put-once-legacy-v1")
    current_v2 = configuration.value["state"]["formatVersion"] == 2
    if current_v2:
        lifecycle.create_namespace(client, legacy, publications[legacy.name])
    node.stop()
    lifecycle.admission_lease_interval(client)
    node.start(full_path)
    if not current_v2:
        lifecycle.create_namespace(client, legacy, publications[legacy.name])
    return full_path, publications, proposals, actual_receipts


def provision(client, args, signed, items, peer, configuration, node):
    full_path, publications, proposals, _, _, _ = prepare_authority(
        client, args, signed, items, peer, configuration, node)
    return admit_authority(client, signed, items, configuration, node, full_path, publications, proposals)


def resume_authority(client, args, configuration, node, full_path, prepared):
    hosts = lifecycle.inspect(client, args.node, full_path, read_json(full_path)["state"]["operations"],
                              stage="transaction-host-recheck")
    inputs.require(hosts.value == prepared["hosts"], "original-native-profile-drift")
    node.start(configuration.path)
    inputs.require(staging.catalog(client, prepared["publications"]) == prepared["catalog"],
                   "original-current-catalog-drift")
    # Apply the original documents with absent-row generation zero. Neither
    # currentness observation can refresh a precondition or widen a grant.
    receipts = policies.apply_retained(client, prepared["proposals"], prepared["mutations"])
    client.evidence.record("authenticated-policy-receipts", receipts)
    node.stop()
    lifecycle.admission_lease_interval(client)
    node.start(full_path)
    return receipts


def execute_campaign(client, args, work, record, configuration, node, peer,
                     signed, items, full_path, publications, proposals, receipts, diagnostic=None):
    campaign = Campaign(client, configuration, full_path, signed, items, publications, proposals, receipts, peer, node)
    campaign.diagnostic = diagnostic
    record["campaign"] = campaign.execute()
    for name in record["campaign"].get("qualifiedDiagnosticScenarios", []):
        record["remainingScenarios"].remove(name)
    if args.recovery_helper is not None:
        record["offlineCampaign"] = OfflineCampaign(campaign, args.recovery_helper, work / "offline-recovery").execute()
        record["remainingScenarios"].remove("reviewed-schema-and-restore-original-results")
    node.stop()
    peer.stop()
    client.evidence.passed("actual-physical-retirement", {
        "cleanNodeSessions": len(node.shutdown), "originalNodeReports": node.shutdown, "recipient": peer.shutdown})


def failure(record, stage, error):
    record.update(passed=False, signedGuestExecutionQualified=False, failedStage=stage, failureType=type(error).__name__)
    reason = str(error)
    if re.fullmatch(r"[a-z0-9][a-z0-9:-]{0,191}", reason):
        record["fixedFailureReason"] = reason


def loaded_inputs(args, work):
    if getattr(args, "current_selections", None) is not None:
        from tools.java_transaction_qualification import current_campaign
        selected = current_campaign.load(args)
        if current_endpoint(args) is not None:
            from tools.rust_capsule_project import read_file
            from tools.transaction_guest_project import CURRENT_HTTP_PROFILE
            for item in selected[0]:
                if item.requirements_digest:
                    marker = inputs.decode(read_file(item.directory / "project" / CURRENT_HTTP_PROFILE, 8192), 8192)
                    inputs.require(marker["schemaVersion"] == "latent.java.current-http-source-input.v1",
                                   "all-mutating-current-http-captures-required")
        return selected
    original = inputs.load(args.portable)
    diagnostic = diagnostic_inputs.load(args, work / "diagnostic-input")
    if diagnostic is not None:
        legacy = next(item for item in original if item.name == "put-once-legacy-v1")
        inputs.require(diagnostic.item.companion_digest == legacy.companion_digest
                       and diagnostic.item.requirements_digest == legacy.requirements_digest
                       and diagnostic.item.host_abi_digest == legacy.host_abi_digest,
                       "same-original-diagnostic-companion-requirements-and-abi")
    return original + ((diagnostic.item,) if diagnostic is not None else ()), diagnostic


def input_identity(record, items, diagnostic):
    record["originalInputs"] = [item.observation() for item in items if item.name != diagnostic_inputs.NAME]
    if diagnostic is not None:
        record["diagnosticInput"] = diagnostic.observation()


def recheck_inputs(args, work, record):
    items, diagnostic = loaded_inputs(args, work)
    observed = {}
    input_identity(observed, items, diagnostic)
    inputs.require(observed["originalInputs"] == record["originalInputs"]
                   and observed.get("diagnosticInput") == record.get("diagnosticInput"),
                   "qualification-input-changed")
    if current_endpoint(args) is not None:
        inputs.require(record["currentHttpEndpoint"] == current_endpoint(args)
                       and record["currentHttpEndpointInput"] ==
                       file_identity(args.current_http_endpoint, "endpoint-declaration", 8192),
                       "current-http-endpoint-input-changed")
        inputs.require(record["currentHttpInstallationInputs"] == current_installation_identity(args),
                       "current-http-installation-input-changed")


def run(args):
    if args.resume_candidate is not None:
        return resume(args)
    work = fresh(args.output)
    work.chmod(0o700)
    evidence = Evidence(work / "evidence")
    client_root = work / "client"
    client_root.mkdir(mode=0o700)
    record = {"schemaVersion": "latent.java-transaction.focused-native.v1", "passed": False,
        "trust": "ephemeral-native-package-test-only", "nativeSourceCommit": args.native_source_commit,
        "conductorSourceCommit": args.conductor_source_commit, "sourceIdentityKind": "supplied-build-identity",
        "compilerSourceCommit": inputs.COMPILER_SOURCE, "guestCompiledAgain": False,
        "packagedDistributionQualified": False, "remainingScenarios": list(REMAINING)}
    if args.recovery_helper is not None:
        record["recoverySourceCommit"] = args.recovery_source_commit
    stage, node, peer, client, prepared = "identity", None, None, None, None
    started = time.monotonic()
    try:
        with owned_cancellation() as cancellation:
            original_clock = staging.clock(args.timeout)
            deadline = staging.deadline(original_clock, args.timeout)
            tools, collectors = tool_identity(args), collector_identity()
            items, diagnostic = loaded_inputs(args, work)
            record["compilerSourceCommit"] = items[0].compiler_source
            record.update(nativeTools=tools, collectorDigests=collectors)
            input_identity(record, items, diagnostic)
            endpoint = current_endpoint(args)
            if endpoint is not None:
                record["currentHttpEndpoint"] = endpoint
                record["currentHttpEndpointInput"] = file_identity(args.current_http_endpoint, "endpoint-declaration", 8192)
                record["currentHttpInstallationInputs"] = current_installation_identity(args)
            client = RecordingClient(args.cli, client_root, cancellation, deadline, evidence)
            try:
                stage = "package"
                package_timeout = max(1, int(min(600, deadline - time.monotonic())))
                if getattr(args, "current_selections", None) is not None:
                    from tools.java_transaction_qualification import current_campaign
                    selected = current_campaign.selections(args.portable, args.current_selections,
                                                           args.current_selections_digest)
                    signed = packaging.package_current(selected, work / "packages", args.contracts_tool,
                                                       args.signer, timeout=package_timeout)
                else:
                    signed = packaging.package(args.portable, work / "packages", args.contracts_tool, args.signer,
                        timeout=package_timeout, diagnostic=None if diagnostic is None else diagnostic.item)
                evidence.record("actual-package-fixture", read_json(work / "packages/package-fixture-receipt.json"))
                stage = "bootstrap"
                peer, configuration, node = prepare_environment(client, args, work, signed)
                stage = "current-authority"
                if args.prepare_authority_only:
                    full_path, publications, proposals, catalog, hosts, mutations = prepare_authority(
                        client, args, signed, items, peer, configuration, node, retained=True)
                    peer.stop()
                    prepared = {"bootstrap": configuration.path.relative_to(work).as_posix(),
                        "full": full_path.relative_to(work).as_posix(), "signed": signed.relative_to(work).as_posix(),
                        "authority": configuration.authority, "origin": configuration.recipient_origin,
                        "publications": publications, "proposals": proposals, "mutations": mutations, "catalog": catalog, "hosts": hosts}
                else:
                    full_path, publications, proposals, receipts = provision(
                        client, args, signed, items, peer, configuration, node)
                    stage = "actual-http"
                    execute_campaign(client, args, work, record, configuration, node, peer,
                                     signed, items, full_path, publications, proposals, receipts, diagnostic)
                stage = "identity-recheck"
                inputs.require(tool_identity(args) == tools and collector_identity() == collectors,
                               "qualification-input-changed")
                recheck_inputs(args, work, record)
                if prepared is None:
                    record.update(passed=True, signedGuestExecutionQualified=True)
            finally:
                # Cleanup is finite and owned even when a mutation, observation
                # or signal fails. A missing native report is never synthesized.
                with cancellation.defer():
                    if node is not None:
                        node.close()
                    if peer is not None:
                        peer.close()
                cancellation.check()
    except BaseException as error:
        failure(record, stage, error)
        # The exact original bounded subprocess/socket observations remain in
        # the private evidence directory; no error message is public authority.
    finally:
        record.update(seconds=round(time.monotonic() - started, 6),
                      cliProcesses=client.calls if client else 0, measuredCases=list(evidence.cases))
        record["evidenceInventory"] = evidence.record("inventory-staged" if prepared is not None else "inventory", evidence.summary())
        if prepared is not None and "failedStage" not in record:
            try:
                record["candidate"] = staging.capture(work, original_clock, args, record, prepared, client, node, peer)
                record.update(authorityPrepared=True, candidatePolicyMutations=0, signedGuestExecutionQualified=False)
            except BaseException as error:
                failure(record, "candidate-capture", error)
        write_json(work / "campaign-receipt.json", record)
    print(bounded_receipt(record))
    return 0 if record["passed"] or record.get("authorityPrepared") else 1


def resume(args):
    work = args.output
    record = {"schemaVersion": "latent.java-transaction.focused-native.v1", "passed": False,
        "trust": "ephemeral-native-package-test-only", "nativeSourceCommit": args.native_source_commit,
        "conductorSourceCommit": args.conductor_source_commit, "sourceIdentityKind": "supplied-build-identity",
        "compilerSourceCommit": inputs.COMPILER_SOURCE, "guestCompiledAgain": False,
        "packagedDistributionQualified": False, "remainingScenarios": list(REMAINING),
        "retainedCandidateDigest": args.candidate_digest}
    stage, node, peer, client, evidence = "retained-candidate", None, None, None, None
    claimed = False
    started = time.monotonic()
    try:
        tools, collectors = tool_identity(args), collector_identity()
        retained, deadline = staging.retain(args, tools, collectors)
        items, diagnostic = loaded_inputs(args, work)
        recheck_inputs(args, work, retained)
        evidence = Evidence.retain(work / "evidence", retained["evidence"])
        with owned_cancellation() as cancellation:
            staging.claim(work, args.candidate_digest)
            claimed = True
            client = RecordingClient(args.cli, work / "client", cancellation, deadline, evidence)
            client.calls = retained["cliCalls"]
            prepared = retained["prepared"]
            configuration = staging.configuration(work, prepared)
            full_path, signed = staging.path(work, prepared["full"]), staging.path(work, prepared["signed"])
            publications, proposals = prepared["publications"], prepared["proposals"]
            release_set = read_json(signed / "release-set.json")
            inputs.require(int(release_set["expiresAtUnixSeconds"]) > time.time() + 300, "original-candidate-package-expired")
            node = lifecycle.Node(client, args.node, staging.path(work, retained["node"]["directory"]))
            node.ordinal, node.shutdown = retained["node"]["ordinal"], retained["node"]["shutdown"]
            record.update(nativeTools=tools, collectorDigests=collectors, originalInputs=retained["originalInputs"],
                          originalCampaignClock=retained["clock"])
            if diagnostic is not None:
                record["diagnosticInput"] = diagnostic.observation()
            if args.recovery_helper is not None:
                record["recoverySourceCommit"] = args.recovery_source_commit
            try:
                prior = retained["recipient"]
                peer = lifecycle.Peer(client, staging.path(work, prior["directory"]), staging.path(work, prior["tls"]),
                    staging.path(work, prior["credential"]), prior["incarnation"], session=prior["session"] + 1, port=prior["port"])
                stage = "current-authority-recheck"
                receipts = resume_authority(client, args, configuration, node, full_path, prepared)
                legacy = next(item for item in items if item.name == "put-once-legacy-v1")
                lifecycle.create_namespace(client, legacy, publications[legacy.name])
                stage = "actual-http"
                execute_campaign(client, args, work, record, configuration, node, peer,
                                 signed, items, full_path, publications, proposals, receipts, diagnostic)
                stage = "identity-recheck"
                inputs.require(tool_identity(args) == tools and collector_identity() == collectors,
                    "qualification-input-changed")
                recheck_inputs(args, work, retained)
                record.update(passed=True, signedGuestExecutionQualified=True)
            finally:
                with cancellation.defer():
                    if node is not None:
                        node.close()
                    if peer is not None:
                        peer.close()
                cancellation.check()
    except BaseException as error:
        failure(record, stage, error)
    finally:
        record.update(seconds=round(time.monotonic() - started, 6), cliProcesses=client.calls if client else 0,
                      measuredCases=list(evidence.cases) if evidence else [])
        if evidence is not None and claimed:
            record["evidenceInventory"] = evidence.record("inventory", evidence.summary())
            write_json(work / "campaign-resume-receipt.json", record)
    print(bounded_receipt(record))
    return 0 if record["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run(parse()))
