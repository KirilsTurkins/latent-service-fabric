"""Source-only compiler association/rollback oracles; no native execution claim."""
from __future__ import annotations

import base64
import copy
from contextlib import nullcontext
import gzip
import io
import json
from pathlib import Path
import socket
import tarfile
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.java_transaction_qualification import configuration as cfg, diagnostic_campaign as campaign
from tools.java_transaction_qualification import diagnostic_inputs as selected, evidence, http, inputs, policies, staging
from tools.rust_capsule_project import inventory
from tools.tests.test_java_transaction_provision import observation
from tools.tests.test_java_transaction_qualification import HEADERS, result


def compiler_files(*, memory=False):
    source, world = b"source-only fixture, never executed", b"world fixture, never compiled"
    companion, requirements = b"original source-only companion", evidence.encoded({"authority": {
        "installed": False, "ruleGranted": False, "executionQualified": False}})
    declaration = {"schemaVersion": "latent.java.transaction-diagnostic-inputs.v1",
        "selectors": dict(selected.SELECTORS) if memory else {name: selected.SELECTORS[name]
            for name in ("trapAfterStage", "loopAfterStage")}, "selectedBusinessDelta": "1",
        "freshInstanceRequired": True, "faultAfter": ["state-put", "captured-put-once-intent"],
        "originalSourceDigest": inputs.digest(b"original"), "sourceDigest": inputs.digest(source),
        "helperDigest": inputs.digest(b"helper"), "worldDigest": inputs.digest(world),
        "companionDigest": inputs.digest(companion), "requirementsDigest": inputs.digest(requirements)}
    flags = ["componentCompiled", "stateExecutionQualified", "cancellationQualified",
             "fuelExhaustionQualified", "freshInstanceQualified"]
    if memory:
        flags += ["memoryExhaustionQualified", "crashBeforeCommitQualified"]
    declaration.update({name: False for name in flags})
    project = {"src/dev/latent/app/Capsule.java": source, "wit/world.wit": world,
        "transaction-binding.json": companion, "deferred-http-requirements.json": requirements,
        "transaction-diagnostic-inputs.json": evidence.encoded(declaration),
        "transaction-profile.json": evidence.encoded({"hostAbiDigest": inputs.digest(b"abi")}),
        "capsule-project.json": evidence.encoded({"limits": selected.LIMITS})}
    files = {"project/" + name: raw for name, raw in project.items()}
    files.update({"source-inputs.json": inventory(project), "source.tar.gz": b"unexecuted source archive fixture",
                  "recipe-inputs.json": b"unexecuted recipe fixture", "compiler-inputs.json": b"unexecuted closure fixture",
                  "compiled/component.wasm": b"\0asm\x0d\0\x01\0source-only-format-fixture"})
    report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": "java", "variant": selected.NAME,
        "world": inputs.WORLD, "evidenceKind": "authored-component-compiler", "status": "compiled", "compiled": True,
        "workingTreeChanged": False, "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
        "sourceRevision": "a" * 40, "componentBytes": len(files["compiled/component.wasm"]),
        "componentDigest": inputs.digest(files["compiled/component.wasm"]), "hostAbiDigest": inputs.digest(b"abi"),
        "actualImports": sorted(inputs.REQUIRED_IMPORTS), "details": {"tools": [], "bindings": {},
            "commands": [{"stage": name, "exitCode": 0} for name in
                         ("java-to-c", "c-to-wasm", "component-new", "component-validate", "compiled-wit")]}}
    for field, path in (("sourceDigest", "source-inputs.json"), ("sourceArchiveDigest", "source.tar.gz"),
                        ("recipeDigest", "recipe-inputs.json"), ("companionDigest", "project/transaction-binding.json"),
                        ("deferredHttpRequirementsDigest", "project/deferred-http-requirements.json"),
                        ("diagnosticInputDigest", "project/transaction-diagnostic-inputs.json")):
        report[field] = inputs.digest(files[path])
    files["report.json"] = evidence.encoded(report)
    receipt = {"schemaVersion": "latent.java.transaction-diagnostic-compiler-process.v2", "sourceCommit": "a" * 40,
        "originalToolProducer": inputs.TOOL_PRODUCER_SOURCE, "compilerOnly": True, "compiled": True,
        "componentExportAvailable": True, "signedNodeExecutionQualified": False,
        "compilerClosure": {"bytes": len(files["compiler-inputs.json"]), "sha256": inputs.digest(files["compiler-inputs.json"])}}
    receipt.update({name: report[name] for name in
        ("componentDigest", "componentBytes", "companionDigest", "deferredHttpRequirementsDigest")})
    return files, receipt, {"diagnostic_source_commit": "a" * 40, "diagnostic_component_digest": report["componentDigest"]}


def capture(files):
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as target:
        for name, value in files.items():
            item = tarfile.TarInfo(selected.PREFIX + name)
            item.size = len(value)
            target.addfile(item, io.BytesIO(value))
    return gzip.compress(raw.getvalue(), mtime=0)


def terminal(kind="fuel"):
    state, code, reason = campaign.EXPECTED[kind]
    consumption = {name: "0" for name in campaign.WIDE}
    consumption.update(cpuFuel="1000000000", peakMemoryBytes="65536", wallTimeMicros="10000",
        stateReadBytes="128", stateWriteBytes=str(campaign.STAGE_WRITE_BYTES + 64),
        childCalls=0, outboundRequests=0, effectCount=1)
    status = {"activationId": "original-host-root", "phase": "terminal", "terminalState": state,
        "terminalOutcome": {"kind": "platform-failure", "error": {"code": code}},
        "terminalAtUnixMillis": "1", "finalConsumption": consumption}
    node = {"activationId": status["activationId"], "rootActivationId": status["activationId"],
        "parentActivationId": None, "phase": "terminal", "terminalState": state, "targetService": cfg.SERVICE,
        "principalKind": "user", "grantedBudget": {name: value if name in campaign.NARROW else str(value)
            for name, value in selected.LIMITS.items()}, "diagnosticIsTerminal": reason is not None,
        "diagnostic": None if reason is None else {"stage": 5, "reason": reason}}
    return status, node


def abort():
    item = SimpleNamespace(component_digest="sha256:" + "a" * 64)
    value = result("aborted")
    value.update(representation="receipt-only", result=None, **{"state-view": None, "effect-ids": []})
    value["abort-fence"] = {"command-id": value["command-id"], "attempt-id": value["attempt-id"],
        "transaction-id": "4" * 64, "owner-fence": base64.b64encode(bytes(32)).decode()}
    record = {"commandId": value["command-id"], "attemptId": value["attempt-id"],
        "outcome": "COMMAND_OUTCOME_ABORTED", "metadataDurable": True, "applicationStateCommitted": False,
        "commit": None, "source": {"publicationId": "original-publication", "componentDigest": item.component_digest},
        "key": {"clientKey": "original-key", "operation": "update",
            "namespace": {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": "1"}},
        "provenAbort": {"commandId": value["command-id"], "attemptId": value["attempt-id"], "transactionId": "4" * 64,
                       "ownerFence": {"encoding": "base64", "data": value["abort-fence"]["owner-fence"]}}}
    return item, value, record


class DiagnosticInputOracle(unittest.TestCase):
    def test_no_input_keeps_original_five_program_and_partial_pins_refuse(self):
        self.assertIsNone(selected.selection(SimpleNamespace()))
        with self.assertRaisesRegex(ValueError, "complete-explicit"):
            selected.selection(SimpleNamespace(diagnostic_source_commit="a" * 40))

    def test_exact_separate_compiler_materials_keep_runtime_qualification_false(self):
        files, receipt, pins = compiler_files()
        report, selectors = selected.validate(files, evidence.encoded(receipt), pins)
        self.assertEqual(selectors, {name: selected.SELECTORS[name] for name in ("trapAfterStage", "loopAfterStage")})
        self.assertIs(report["signedNodeExecutionQualified"], False)
        self.assertEqual(selected.archive(capture(files)), files)

    def test_source_only_memory_flag_does_not_create_a_compiled_selector(self):
        files, receipt, pins = compiler_files(memory=True)
        _, selectors = selected.validate(files, evidence.encoded(receipt), pins)
        self.assertEqual(selectors["memoryAfterStage"], "4294967292")
        original, _, _ = compiler_files()
        self.assertNotIn("memoryAfterStage", inputs.decode(original["project/transaction-diagnostic-inputs.json"])["selectors"])
        declaration = inputs.decode(files["project/transaction-diagnostic-inputs.json"])
        declaration["memoryExhaustionQualified"] = True
        project = {name[8:]: raw for name, raw in files.items() if name.startswith("project/")}
        with self.assertRaises(ValueError):
            selected.declaration(evidence.encoded(declaration), project)

    def test_mixed_source_component_closure_failed_compiler_and_inferred_grants_refuse(self):
        for change in ("source", "component", "closure", "compiler", "runtime", "imports", "limits", "boolean"):
            files, receipt, pins = compiler_files()
            report = inputs.decode(files["report.json"])
            if change == "source":
                pins["diagnostic_source_commit"] = "b" * 40
            elif change == "component":
                files["compiled/component.wasm"] += b"modified"
            elif change == "closure":
                files["compiler-inputs.json"] += b"modified"
            elif change == "compiler":
                report["details"]["commands"][0]["exitCode"] = 1
            elif change == "runtime":
                receipt["signedNodeExecutionQualified"] = True
            elif change == "imports":
                report["actualImports"].append("latent:http/client@0.2.0")
            else:
                limits = dict(selected.LIMITS, childCalls=False) if change == "boolean" else dict(selected.LIMITS, cpuFuel=2000000000)
                files["project/capsule-project.json"] = evidence.encoded({"limits": limits})
                project = {name[8:]: raw for name, raw in files.items() if name.startswith("project/")}
                files["source-inputs.json"] = inventory(project)
                report["sourceDigest"] = inputs.digest(files["source-inputs.json"])
            files["report.json"] = evidence.encoded(report)
            with self.subTest(change=change), self.assertRaises(ValueError):
                selected.validate(files, evidence.encoded(receipt), pins)

    def test_archive_links_escaping_duplicate_members_and_foreign_prefixes_refuse(self):
        for change in ("link", "escape", "duplicate", "foreign"):
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode="w") as target:
                name = selected.PREFIX + ("../outside" if change == "escape" else "report.json")
                if change == "foreign":
                    name = "foreign/report.json"
                member = tarfile.TarInfo(name)
                member.type = tarfile.SYMTYPE if change == "link" else tarfile.REGTYPE
                member.linkname = "outside" if change == "link" else ""
                member.size = 0
                target.addfile(member, io.BytesIO())
                if change == "duplicate":
                    target.addfile(member, io.BytesIO())
            with self.subTest(change=change), self.assertRaises(ValueError):
                selected.archive(gzip.compress(raw.getvalue()))

    def test_retained_capture_rechecks_original_bytes_and_refuses_changed_pin(self):
        files, receipt, pins = compiler_files()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            archive, process = root / "capture.gz", root / "receipt.json"
            archive.write_bytes(capture(files))
            process.write_bytes(evidence.encoded(receipt))
            args = SimpleNamespace(diagnostic_capture=archive, diagnostic_receipt=process, **pins,
                diagnostic_capture_digest=inputs.digest(archive.read_bytes()),
                diagnostic_receipt_digest=inputs.digest(process.read_bytes()))
            first = selected.load(args, root / "selected")
            self.assertEqual(first.observation(), selected.load(args, root / "selected").observation())
            (root / "selected/component.wasm").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "retained-diagnostic-evidence-drift"):
                selected.load(args, root / "selected")
            args.diagnostic_receipt_digest = "sha256:" + "f" * 64
            with self.assertRaisesRegex(ValueError, "pinned-diagnostic"):
                selected.load(args, root / "unselected")
            self.assertFalse((root / "unselected").exists())

    def test_diagnostic_program_cannot_silently_add_offline_node_sessions(self):
        values = dict.fromkeys(selected.ARGUMENTS, "supplied")
        with self.assertRaisesRegex(ValueError, "separate-bounded-candidates"):
            selected.selection(SimpleNamespace(**values, recovery_helper=Path("/actual-helper")))


class RollbackOracle(unittest.TestCase):
    def test_original_attempt_lookup_can_wait_for_claim_without_retrying_mutation_or_renewing_time(self):
        calls = []
        original = {"outcomeKnown": True, "category": "success", "data": {"command": {"attemptId": "original"}}}
        replies = iter(({"outcomeKnown": True, "category": "not-found", "data": {"command": None}}, original))
        def call(*args, **kwargs):
            calls.append((args, kwargs))
            return next(replies)
        client = SimpleNamespace(call=call)
        collector = campaign.DiagnosticCampaign.__new__(campaign.DiagnosticCampaign)
        collector.client, collector.publication = client, "publication:sha256:" + "a" * 64
        pending = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True))
        cutoff = time.monotonic() + 10
        with patch.object(campaign.lifecycle, "as_user", return_value=nullcontext()), patch.object(campaign.time, "sleep"):
            self.assertEqual(collector.original_attempt(pending, "original-key", cutoff), original["data"]["command"])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(args[:2] == ("transaction", "lookup") and args[-2:] == ("--client-key", "original-key")
                            and kwargs == {"codes": (0, 6)} for args, kwargs in calls))
        with self.assertRaisesRegex(ValueError, "not-running"):
            collector.original_attempt(pending, "original-key", time.monotonic() - 1)
        self.assertEqual(len(calls), 2)

    def test_unknown_lookup_and_exhausted_original_claim_read_bound_refuse_without_cancel(self):
        collector = campaign.DiagnosticCampaign.__new__(campaign.DiagnosticCampaign)
        collector.publication = "publication:sha256:" + "a" * 64
        pending = SimpleNamespace(thread=SimpleNamespace(is_alive=lambda: True))
        for outcome, category, reason, expected_calls in ((False, "not-found", "certainty", 1),
                (True, "platform-failure", "lookup-refusal", 1), (True, "not-found", "not-observed", 8)):
            calls = []
            def call(*args, **kwargs):
                calls.append((args, kwargs))
                return {"outcomeKnown": outcome, "category": category, "data": {"command": None}}
            collector.client = SimpleNamespace(call=call)
            with self.subTest(category=category, outcome=outcome), patch.object(campaign.lifecycle, "as_user", return_value=nullcontext()), \
                    patch.object(campaign.time, "sleep"), self.assertRaisesRegex(ValueError, reason):
                collector.original_attempt(pending, "original-key", time.monotonic() + 10)
            self.assertEqual(len(calls), expected_calls)
            self.assertTrue(all(args[:2] == ("transaction", "lookup") for args, _ in calls))

    def test_parallel_transport_and_lookup_evidence_share_one_finite_byte_reservation(self):
        with tempfile.TemporaryDirectory() as temporary:
            observed = evidence.Evidence(Path(temporary) / "original-evidence")
            observed.total = 33554432 - 7
            start, outcomes = threading.Barrier(3), []
            def writer(name):
                start.wait(timeout=2)
                try:
                    observed.write(name, b"four")
                    outcomes.append("retained")
                except ValueError:
                    outcomes.append("refused")
            owners = [threading.Thread(target=writer, args=(name,)) for name in ("http.body", "lookup.body")]
            for owner in owners:
                owner.start()
            start.wait(timeout=2)
            for owner in owners:
                owner.join(2)
                self.assertFalse(owner.is_alive())
            self.assertEqual(sorted(outcomes), ["refused", "retained"])
            self.assertEqual(len(observed.summary()["files"]), 1)
            self.assertEqual(observed.summary()["bytes"], 33554432 - 3)

    def test_each_fault_requires_original_terminal_accounting_and_fixed_producer_reason(self):
        for kind in campaign.EXPECTED:
            status, node = terminal(kind)
            self.assertEqual(campaign.staged_terminal(status, node, kind)["effectCount"], 1)

    def test_running_timeout_and_zero_stage_accounting_cannot_qualify_rollback(self):
        for change in ("running", "timeout", "no-effect", "no-put", "no-final", "external", "child", "boolean"):
            status, node = terminal()
            if change == "running":
                status["phase"] = node["phase"] = "running"
            elif change == "timeout":
                status["terminalState"] = node["terminalState"] = "deadline_exceeded"
            elif change == "no-effect":
                status["finalConsumption"]["effectCount"] = 0
            elif change == "no-put":
                status["finalConsumption"]["stateWriteBytes"] = str(campaign.STAGE_WRITE_BYTES)
            elif change == "no-final":
                status["finalConsumption"] = None
            elif change == "boolean":
                status["finalConsumption"]["effectCount"] = True
            else:
                status["finalConsumption"]["outboundRequests" if change == "external" else "childCalls"] = 1
            with self.subTest(change=change), self.assertRaises(ValueError):
                campaign.staged_terminal(status, node, "fuel")

    def test_reduced_or_inflated_grant_and_generic_resource_reason_do_not_qualify_memory(self):
        for change in ("grant", "generic", "trap", "nonterminal"):
            status, node = terminal("memory")
            if change == "grant":
                node["grantedBudget"]["memoryBytes"] = "134217728"
            elif change == "generic":
                node["diagnostic"]["reason"] = 12
            elif change == "trap":
                status["terminalState"] = node["terminalState"] = "guest_trap"
            else:
                node["diagnosticIsTerminal"] = False
            with self.subTest(change=change), self.assertRaises(ValueError):
                campaign.staged_terminal(status, node, "memory")

    def test_original_durable_abort_proof_matches_current_authorized_http_receipt(self):
        item, value, record = abort()
        campaign.aborted(record, value, item, "original-publication", "original-key")
        http.response(409, evidence.encoded(value), HEADERS)

    def test_missing_uncertain_committed_foreign_or_changed_abort_proof_cannot_qualify(self):
        for change in ("missing", "uncertain", "committed", "tenant", "source", "fence", "effect", "payload"):
            item, value, record = abort()
            if change == "missing":
                record["provenAbort"] = None
            elif change == "uncertain":
                record["outcome"] = "COMMAND_OUTCOME_RECOVERY_REQUIRED"
            elif change == "committed":
                record["applicationStateCommitted"] = True
            elif change == "tenant":
                record["key"]["namespace"]["tenant"] = "foreign"
            elif change == "source":
                record["source"]["publicationId"] = "current-publication"
            elif change == "fence":
                record["provenAbort"]["attemptId"] = "5" * 64
            elif change == "effect":
                value["effect-ids"] = ["6" * 64]
            else:
                value["result"] = {"invented": True}
            with self.subTest(change=change), self.assertRaises(ValueError):
                campaign.aborted(record, value, item, "original-publication", "original-key")

    def test_unchanged_query_and_absent_recipient_put_are_both_required(self):
        query = {"count": "0", "key-version": {"none": None}}
        recipient = dict.fromkeys(campaign.provider.COUNTERS, 0)
        campaign.unchanged(query, copy.deepcopy(query), recipient, dict(recipient))
        for after, counters in ((dict(query, count="1"), recipient),
                (dict(query, **{"key-version": {"some": [1]}}), recipient), (query, dict(recipient, puts=1))):
            with self.assertRaises(ValueError):
                campaign.unchanged(query, after, recipient, counters)

    def test_pending_transport_closes_and_joins_actual_socket_owner_without_claiming_abort(self):
        sent, received = socket.socketpair()
        received.settimeout(0.25)
        entered = threading.Event()
        class Transport:
            client = SimpleNamespace(deadline=time.monotonic() + 10)
            def socket(self, mode, request_owner):
                try:
                    request_owner.attach(received)
                    entered.set()
                    received.recv(1)
                    return {"status": 503}
                finally:
                    received.close()
                    request_owner.detach()
        try:
            pending = campaign.PendingHttp(Transport())
            self.assertTrue(entered.wait(1))
            pending.close()
            self.assertFalse(pending.thread.is_alive())
            self.assertTrue(pending.retired)
            self.assertTrue(pending.result is None or pending.result == {"status": 503})
            self.assertFalse(isinstance(pending.result, dict) and "abort-fence" in pending.result)
        finally:
            sent.close()


class DiagnosticProgramOracle(unittest.TestCase):
    def test_extra_publication_requires_explicit_fourth_native_effect_and_current_purpose_rules(self):
        value, operations, publications = observation()
        publication = "publication:sha256:" + "5" * 64
        publications[selected.NAME] = publication
        effect = dict(value["deferredHttp"][0], publication=publication,
                      dispatchSubject="actual-diagnostic-service", dispatchRecoveryScope="diagnostic-original-scope")
        value["deferredHttp"].append(effect)
        operations.append(dict(operations[0], publication=publication))
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations)
        hosts = policies.ObservedHosts.read(value, operations, diagnostic=True)
        with self.assertRaises(ValueError):
            policies.documents(hosts, publications)
        proposal = policies.documents(hosts, publications, diagnostic=True)
        self.assertEqual(len(proposal["bindings"]) + len(proposal["policies"]), 10)
        self.assertEqual(len(proposal["policies"][cfg.DISPATCH_POLICY]["rules"]), 4)
        last = proposal["policies"][cfg.DISPATCH_POLICY]["rules"][-1]
        self.assertEqual(last["principals"], [{"kind": "service", "subject": "actual-diagnostic-service"}])
        self.assertEqual(last["publications"], [publication])
        self.assertEqual(last["ceiling"]["inputBytes"], 27)
        self.assertTrue(all(len(row["operations"]) <= 16 for document in proposal["policies"].values()
                            for row in document["rules"]))

    def test_fifteen_operations_need_explicit_selection_and_original_bootstrap_remains_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = {"state": {"operations": [], "clockCheckpoint": "original"}}
            config = cfg.Configuration(root / "original", original, "localhost:1234", {})
            with self.assertRaises(ValueError):
                config.selected(root / "refused", [{}] * 15)
            target = config.selected(root / "selected", [{}] * 15, diagnostic=True)
            self.assertEqual(len(json.loads(target.read_bytes())["state"]["operations"]), 15)
            self.assertEqual(original["state"]["operations"], [])
            with self.assertRaises(ValueError):
                config.selected(root / "refused", [{}] * 16, diagnostic=True)

    def test_candidate_source_identity_pins_separate_diagnostic_selection(self):
        original = SimpleNamespace(native_source_commit="a" * 40, conductor_source_commit="b" * 40,
                                   portable=Path("/original-five"))
        self.assertEqual(set(staging.sources(original)), {"native", "conductor", "portable"})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            files, receipt, pins = compiler_files()
            archive, process = root / "capture.gz", root / "receipt.json"
            archive.write_bytes(capture(files))
            process.write_bytes(evidence.encoded(receipt))
            for name, value in dict(pins, diagnostic_capture=archive, diagnostic_receipt=process,
                diagnostic_capture_digest=inputs.digest(archive.read_bytes()),
                diagnostic_receipt_digest=inputs.digest(process.read_bytes())).items():
                setattr(original, name, value)
            observed = staging.sources(original)
            original.diagnostic_component_digest = "sha256:" + "9" * 64
            self.assertNotEqual(staging.sources(original), observed)


if __name__ == "__main__":
    unittest.main()
