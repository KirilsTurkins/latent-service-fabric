"""Review/expiry/ownership guard tests, not Java or native-node qualification."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.guest_runtime_profiles import profiles
from tools.java_http_composition import diagnostic_program as program, history_diagnostics as history
from tools.java_http_composition import native_inputs, policy_proposals as proposals, provider_timeout
from tools.java_http_composition.node import DOMAIN, SERVICE_CAPABILITY, TENANT, CHILD_SUBJECT
from tools.phase2_operator_process import WorkflowError, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT
from tools.sdk_provider_scenario import start_provider
from tools.static_api.node import policy


def selected():
    rows = [{"id": name, "tenant": TENANT, "service": "runtime-host", "capability": contract,
             "profile": profile, "configurationEpoch": "1", "configurationDigest": "sha256:" + "a" * 64}
            for name, (contract, profile, _operation, _kind) in profiles("java").items()]
    rows += [{"id": "localService", "tenant": TENANT, "service": DOMAIN, "capability": SERVICE_CAPABILITY,
              "profile": "lsf-local-service-invocation-v1", "configurationEpoch": "1",
              "configurationDigest": "sha256:" + "b" * 64},
             {"id": "http", "tenant": TENANT, "service": "http-host", "capability": provider_timeout.CAPABILITY,
              "profile": "bounded-http-v1", "configurationEpoch": "1", "configurationDigest": "sha256:" + "c" * 64}]
    pubs = {name: f"publication:sha256:{index:064x}" for index, name in enumerate(native_inputs.COMPONENTS, 1)}
    return {"providers": rows}, pubs


def tree(nodes=(), token=None, *, available=True, expired=False):
    return {"schemaVersion": 1, "historyAvailable": available, "cursorExpired": expired,
            "nodes": [{"activationId": name, "state": state} for name, state in nodes], "nextPageToken": token,
            "externalCompletion": "unknown"}


class JavaDiagnosticPolicyTests(unittest.TestCase):
    def test_program_has_eight_initial_records_four_revisions_and_original_narrow_scopes(self):
        startup, publications = selected()
        result = proposals.program(startup, publications, 12345)
        self.assertEqual((result["initialCount"], result["revisionCount"]), (8, 4))
        self.assertFalse(result["authorityApplied"])
        http = result["initial"][1]["document"]["rules"][0]
        self.assertEqual(http["resources"], {"kind": "http", "origins": [{"scheme": "http", "host": "localhost", "port": 12345}],
                                           "methods": ["GET"], "paths": ["/allowed"], "pathPrefixes": []})
        self.assertEqual(http["ceiling"], {"operations": 1, "inputBytes": 4096, "outputBytes": 14336, "wallTimeMillis": 1000})
        self.assertEqual(http["publications"], [publications["domain"]])
        self.assertEqual(http["principals"][-1], {"kind": "service", "subject": CHILD_SUBJECT})
        self.assertEqual([row["expectedGeneration"] for row in result["revisions"]], ["1", "2", "1", "2"])
        self.assertEqual(result["revisions"][2]["document"]["rules"], [])

    def test_http_ceiling_covers_actual_provider_copy_reservation_without_changing_wire_limits(self):
        from tools.phase3_management_scenario import http_provider
        with tempfile.TemporaryDirectory() as temporary:
            installed = http_provider(Path(temporary), TENANT, 12345)
        limits = installed["configuration"]["limits"]
        self.assertEqual(limits, {"maximumRequestBodyBytes": 4096, "maximumResponseBodyBytes": 4096,
            "maximumEncodedResponseBytes": 8192, "maximumHeaderBytes": 4096,
            "maximumHeaders": 16, "maximumRedirects": 0})
        reservation = (limits["maximumResponseBodyBytes"] + 2 * limits["maximumHeaderBytes"]
                       + limits["maximumHeaders"] * 64 + 1024)
        self.assertEqual(reservation, 14336)
        self.assertGreater(reservation, limits["maximumEncodedResponseBytes"])
        startup, publications = selected()
        policy = proposals.http(startup, publications["domain"], 12345)[1]["document"]["rules"][0]
        self.assertEqual(policy["ceiling"]["outputBytes"], reservation)
        self.assertEqual(policy["ceiling"], {"operations": 1, "inputBytes": 4096,
            "outputBytes": reservation, "wallTimeMillis": 1000})

    def test_missing_duplicate_foreign_or_changed_native_profiles_cannot_create_review_bytes(self):
        original, pubs = selected()
        mutations = []
        missing = deepcopy(original); missing["providers"].pop(); mutations.append(missing)
        duplicate = deepcopy(original); duplicate["providers"].append(duplicate["providers"][0]); mutations.append(duplicate)
        for field, value in (("tenant", "foreign"), ("profile", "unknown"), ("configurationEpoch", "2"),
                             ("configurationDigest", "arbitrary-diagnostic-string")):
            changed = deepcopy(original); changed["providers"][0][field] = value; mutations.append(changed)
        for startup in mutations:
            with self.subTest(startup=startup), self.assertRaises(WorkflowError):
                proposals.program(startup, pubs, 12345)
        for port in (False, 0, 65536):
            with self.assertRaises(WorkflowError): proposals.program(original, pubs, port)

    def test_review_hash_is_exact_original_policy_owner_file_bytes(self):
        startup, pubs = selected()
        row = proposals.program(startup, pubs, 12345)["initial"][0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            client = SimpleNamespace(directory=directory, calls=0,
                call=lambda *args: {"outcomeKnown": True, "data": {"receipt": {"operationId": row["id"] + "-0"}}})
            policy(client, row["kind"], row["id"], row["document"])
            actual = (directory / (row["id"] + "-0.json")).read_bytes()
            self.assertEqual(actual, proposals.review_bytes(row["document"]))
            self.assertEqual(proposals.reviewed({"initial": [row], "revisions": []})["initial"][0]["sha256"],
                             hashlib.sha256(actual).hexdigest())

    def test_wrong_clock_changes_only_original_service_principal_and_restore_is_original_document(self):
        startup, pubs = selected(); result = proposals.program(startup, pubs, 12345)
        original = next(row["document"] for row in result["initial"] if row["id"] == "clockMonotonic-allow")
        wrong = result["revisions"][0]["document"]
        self.assertEqual(wrong["rules"][0]["principals"][:2], original["rules"][0]["principals"][:2])
        self.assertEqual(result["revisions"][1]["document"], original)
        absent = deepcopy(original); absent["rules"][0]["principals"].pop()
        with self.assertRaises(WorkflowError): proposals.wrong_clock(absent)


class JavaDiagnosticHistoryTests(unittest.TestCase):
    def test_paging_preserves_unique_membership_while_observed_outcomes_may_progress(self):
        first = tree((("root", "running"),), "opaque-token")
        client = SimpleNamespace(call=lambda *args: {"data": tree((("child", "completed"),))})
        observed = history.collect(client, ("activation", "tree", "root"), first, tree=True)
        self.assertEqual(observed["activationIds"], ["root", "child"])
        self.assertEqual(len(observed["pages"]), 2)

    def test_duplicate_membership_cycles_wrong_versions_and_byte_bounds_refuse(self):
        first = tree((("root", "running"),), "token")
        for reply in (tree((("root", "completed"),)), tree((("child", "running"),), "token")):
            client = SimpleNamespace(call=lambda *args, reply=reply: {"data": reply})
            with self.assertRaises(WorkflowError): history.collect(client, (), first, tree=True)
        for field, value in (("schemaVersion", True), ("schemaVersion", 999), ("cursorExpired", "false"),
                             ("nextPageToken", "x" * 161), ("nodes", [{"activationId": "x" * 513}]),
                             ("externalCompletion", "mutation-completed")):
            invalid = tree(); invalid[field] = value
            with self.assertRaises(WorkflowError): history.page(invalid, tree=True)
        huge = tree((("root", "completed"),)); huge["opaque"] = "x" * 65536
        with self.assertRaises(WorkflowError): history.page(huge, tree=True)

    def test_expiry_requires_explicit_cursor_expiration_and_empty_retained_history(self):
        self.assertTrue(history.expired(tree(available=False, expired=True)))
        for reply in (tree(available=False), tree(expired=True), tree((("root", "completed"),), available=False, expired=True),
                      tree(token="token", available=False, expired=True)):
            self.assertFalse(history.expired(reply))

    def test_foreign_tree_cursor_and_roots_cannot_disclose_records_and_invoke_role_cannot_read(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            config = directory / "original-client.json"
            write_json(config, {"profiles": [{"token": "operator", "tenant": TENANT}]})
            calls = []
            def read(*args, **_kwargs):
                token = json.loads(client.config.read_text())["profiles"][0]["token"]
                calls.append((token, args))
                if token == history.inspection.INVOKER_TOKEN:
                    return {"category": "platform-failure", "error": {"code": "permission-denied"}}
                return {"category": "success", "data": {**tree(available=False, expired=True),
                    "retainedHistoryOnly": True, "externalCompletion": "unknown"}}
            client = SimpleNamespace(config=config, directory=directory, call=read)
            with patch.object(history.inspection, "owners", return_value={"active": 0}):
                observed = history.authority(client, "original-root", "original-cursor")
            self.assertEqual(set(observed), {"wrong-tenant", "invoke-only"})
            self.assertEqual(client.config, config)
            self.assertEqual(len(calls), 4)
            self.assertIn("original-cursor", calls[0][1])
            client.call = lambda *_args, **_kwargs: {"category": "success", "data": {
                **tree((("foreign-secret-root", "completed"),)), "retainedHistoryOnly": True,
                "externalCompletion": "unknown"}}
            with patch.object(history.inspection, "owners", return_value={"active": 0}), self.assertRaises(WorkflowError):
                # Use a separate owned location; prior probe records are retained.
                client.directory = directory / "failure"; client.directory.mkdir()
                history.authority(client, "original-root", "original-cursor")
            self.assertEqual(client.config, config)


class JavaDiagnosticMaterialTests(unittest.TestCase):
    def builds(self, output):
        builds = output / "builds"; builds.mkdir()
        adaptations = {"domain": {"sourceDigest": "sha256:" + "a" * 64, "witDigest": "sha256:" + "b" * 64,
            "providerTimeoutMillis": 250, "domainOutboundRequests": 1,
            "templateDigest": file_identity(ROOT / "sdk/java-guest/templates/http-status.java")["sha256"],
            "recipeDigest": file_identity(ROOT / "tools/java_http_composition/provider_timeout.py")["sha256"]}}
        for name in native_inputs.COMPONENTS:
            root = builds / name; root.mkdir()
            (root / "component.wasm").write_bytes(b"explicit-unit-fixture-not-compiled")
            source = {"src/dev/latent/app/Capsule.java": {"digest": "sha256:" + "a" * 64},
                "wit/world.wit": {"digest": "sha256:" + "b" * 64},
                "capsule-project.json": {"digest": "sha256:" + "c" * 64}}
            write_json(root / "source-inputs.json", source)
            write_json(root / "build-observation.json", {"unitFixture": True})
            write_json(root / "surface.json", {"imports": [provider_timeout.CAPABILITY] if name == "domain" else []})
            write_json(root / "BUILD-COMPLETE.json", {"formatVersion": 1, "commands": [{"exitCode": 0}],
                "componentDigest": file_identity(root / "component.wasm")["sha256"],
                "sourceDigest": file_identity(root / "source-inputs.json")["sha256"],
                "observationDigest": file_identity(root / "build-observation.json")["sha256"]})
            if name in ("adapter", "adapter-next"):
                adaptations[name] = {"sourceDigest": "sha256:" + "a" * 64,
                    "descriptorDigest": "sha256:" + "c" * 64, "adapterOutboundRequests": 2}
        write_json(output / "diagnostic-adaptations.json", adaptations)
        return builds

    def test_unadapted_foreign_recipe_changed_component_and_uncompiled_source_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); builds = self.builds(output)
            observed = native_inputs.compiler(builds)
            self.assertEqual(set(observed["components"]), set(native_inputs.COMPONENTS))
            self.assertFalse(observed["hermetic"])
            path = output / "diagnostic-adaptations.json"; original = path.read_bytes()
            for document in ({}, {**json.loads(original), "domain": {**json.loads(original)["domain"],
                              "sourceDigest": "sha256:" + "0" * 64}},
                             {**json.loads(original), "domain": {**json.loads(original)["domain"],
                              "recipeDigest": "sha256:" + "0" * 64}}):
                path.write_text(json.dumps(document))
                with self.assertRaises(WorkflowError): native_inputs.compiler(builds)
            path.write_bytes(original)
            (builds / "domain/component.wasm").write_bytes(b"changed-component")
            with self.assertRaises(WorkflowError): native_inputs.compiler(builds)

    def test_native_receipt_byte_and_elf_identity_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); receipt = root / "receipt.json"
            outputs = {}
            for name in native_inputs.EXECUTABLES:
                (root / name).write_bytes(b"\x7fELFexplicit-unit-fixture-not-executable")
                row = file_identity(root / name); outputs[name] = {"sha256": row["sha256"][7:], "bytes": row["bytes"]}
            write_json(receipt, {"allOriginal23VectorsPassed": True, "allAddedRegressionVectorsPassed": True,
                "allExecutableBytesReverified": True, "sourceIdentity": {"sourceDirty": False,
                    "sourceVolumeReadOnly": True, "commit": "a" * 40, "tree": "b" * 40},
                "outputs": outputs, "completeCI": False})
            _binaries, result = native_inputs.native(root, receipt)
            self.assertFalse(result["completeCI"])
            self.assertFalse(result["authenticatedPackagedRuntime"])
            (root / "latentd").write_bytes(b"changed-original-node")
            with self.assertRaises(WorkflowError): native_inputs.native(root, receipt)

    def test_signed_inputs_keep_original_component_source_and_separate_enforced_policy(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary); compiled = native_inputs.compiler(self.builds(output))
            releases = output / "releases"; releases.mkdir()
            write_json(releases / "policy.json", {"explicitTestPolicy": True})
            rows = []
            for name in native_inputs.COMPONENTS:
                selected = releases / ("java-http-" + name); selected.mkdir()
                component = compiled["components"][name]["component"]["sha256"]
                source = compiled["components"][name]["source"]["sha256"]
                write_json(selected / "build-observation.json", {"componentDigest": component,
                    "source": {"snapshotDigest": source}})
                rows.append({"name": selected.name, "componentDigest": component, "sourceSnapshotDigest": source})
            marker = {"schemaVersion": "latent.capsule.demo.v1", "tenant": TENANT,
                "trust": "isolated-short-lived-demo-only", "expiresAtUnixSeconds": 1,
                "policyDigest": file_identity(releases / "policy.json")["sha256"], "releases": rows}
            path = releases / "release-set.json"; write_json(path, marker)
            self.assertTrue(native_inputs.signed(releases, compiled)["ordinaryNativeAdmissionRequired"])
            marker["releases"][0]["sourceSnapshotDigest"] = "sha256:" + "0" * 64
            path.write_text(json.dumps(marker))
            with self.assertRaises(WorkflowError): native_inputs.signed(releases, compiled)
            marker["releases"][0]["sourceSnapshotDigest"] = compiled["components"]["domain"]["source"]["sha256"]
            path.write_text(json.dumps(marker))
            (releases / "policy.json").write_bytes(b"changed-enforced-policy")
            with self.assertRaises(WorkflowError): native_inputs.signed(releases, compiled)

    def test_retained_peer_port_is_fixed_and_drift_retires_the_original_owner(self):
        from unittest.mock import Mock
        process = Mock(); process.line.return_value = {"port": 12345}
        client = SimpleNamespace(deadline=200, environment={}, cancellation=Mock())
        with patch("tools.sdk_provider_scenario.Process", return_value=process) as launch, \
             patch("tools.sdk_provider_scenario.time.monotonic", return_value=100):
            self.assertEqual(start_provider(client, Path("controlled"), port=12345)[1], 12345)
            self.assertEqual(launch.call_args.args[0][-2:], ["--port", "12345"])
            process.line.return_value = {"port": 12346}
            with self.assertRaises(WorkflowError): start_provider(client, Path("controlled"), port=12345)
            process.close.assert_called_once()
        for port in (False, 0, 65536, "12345"):
            with patch("tools.sdk_provider_scenario.Process") as launch, \
                 patch("tools.sdk_provider_scenario.time.monotonic", return_value=100), self.assertRaises(WorkflowError):
                start_provider(client, Path("controlled"), port=port)
            launch.assert_not_called()

    def test_original_input_failure_is_preserved_before_peer_node_or_authority_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "attempt"
            with patch.object(program, "clock", return_value={"original": True}), \
                 patch.object(program, "deadline", return_value=150), \
                 patch.object(program, "inputs", side_effect=WorkflowError("original-input-refused")), \
                 patch.object(program, "start_provider") as peer, patch.object(program, "session") as node, \
                 self.assertRaises(WorkflowError):
                program.prepare(Path("native"), Path("receipt"), Path("builds"), Path("releases"), output)
            peer.assert_not_called(); node.assert_not_called()
            record = json.loads((output / "PREPARE-FAILED.json").read_bytes())
            self.assertEqual(record["reason"], "original-input-refused")
            self.assertEqual(record["applicationCapabilityPolicyMutations"], 0)
            self.assertEqual(record["guestInvocations"], 0)
            self.assertFalse((output / "candidate.json").exists())


class JavaDiagnosticReviewTests(unittest.TestCase):
    def test_prepare_session_captures_store_only_after_reaped_shutdown(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "node"; work.mkdir()
            output = Path(temporary) / "prepare"
            node = SimpleNamespace(buffers=[bytearray(), bytearray()], close=Mock())
            client = SimpleNamespace(node=node)
            order = []
            def stopped(_node):
                order.append("reaped")
                return {"reaped": True}
            def captured(_work, _deadline, evidence):
                self.assertEqual(evidence, output)
                self.assertEqual(order, ["reaped", "verified"])
                order.append("captured")
                return {"sha256": "sha256:" + "a" * 64}
            with patch.object(program, "owned_cancellation", return_value=nullcontext(None)), \
                 patch.object(program, "deadline", return_value=100), \
                 patch.object(program, "RecordingClient", return_value=client), \
                 patch.object(program, "connect", return_value=node), \
                 patch.object(program, "idle"), patch.object(program, "stop"), \
                 patch.object(program, "stopped_record", side_effect=stopped), \
                 patch.object(provider_timeout, "verify_shutdown", side_effect=lambda _row: order.append("verified")), \
                 patch.object(program, "private_store", side_effect=captured):
                with program.session(Path("node"), Path("cli"), work, Path("config"), output,
                                     {"original": True}, ordinal=1) as (_client, _node, physical):
                    self.assertFalse(physical["cleanPhysicalRetirement"])
            self.assertEqual(order, ["reaped", "verified", "captured"])
            self.assertTrue(physical["cleanPhysicalRetirement"])
            self.assertEqual(physical["privateStoreCapture"]["sha256"], "sha256:" + "a" * 64)

    def test_prepared_execution_creates_each_session_output_once_and_retires_both_owners(self):
        from contextlib import ExitStack
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            prepared = {}
            for name in ("former", "current"):
                work = output / (name + "-node"); work.mkdir()
                config = work / "node.json"; write_json(config, {})
                prepared[name] = {"configFile": "node.json", "configSha256": file_identity(config, 262144),
                                  "host": "localhost", "physical": {"privateStoreCapture": {"source": "stopped"}}}
            candidate = {"clock": {"original": True}, "inputs": {}, "recipientPort": 12345, "cases": prepared}
            client = SimpleNamespace(node=None)
            node = SimpleNamespace(buffers=[bytearray(), bytearray()], close=Mock())
            with ExitStack() as stack:
                stack.enter_context(patch.object(program, "_review", return_value=candidate))
                stack.enter_context(patch.object(program, "deadline", return_value=150))
                stack.enter_context(patch.object(program, "inputs", return_value=(
                    {"latent": Path("cli"), "latentd": Path("node")}, {})))
                stack.enter_context(patch.object(program, "RecordingClient", return_value=client))
                stack.enter_context(patch.object(program, "start_provider", return_value=(object(), 12345)))
                stack.enter_context(patch.object(program, "close_failed_provider", return_value={"closed": True}))
                connect = stack.enter_context(patch.object(program, "connect", return_value=node))
                stop = stack.enter_context(patch.object(program, "stop"))
                stack.enter_context(patch.object(program, "idle"))
                stack.enter_context(patch.object(program, "stopped_record", return_value={"closed": True}))
                stack.enter_context(patch.object(program, "private_store", return_value={"source": "stopped"}))
                stack.enter_context(patch.object(provider_timeout, "verify_shutdown"))
                stack.enter_context(patch.object(provider_timeout, "stop_peer", return_value={"closed": True}))
                stack.enter_context(patch.object(program, "_admit", return_value=({}, None)))
                stack.enter_context(patch.object(program, "_former", return_value={"status": "passed"}))
                stack.enter_context(patch.object(program, "_current", return_value={"status": "passed"}))
                result = program.execute(Path("native"), Path("receipt"), Path("builds"), Path("releases"),
                                         output, approved_sha256="0" * 64)
            self.assertEqual(result["status"], "passed")
            self.assertEqual(set(result["cases"]), {"former", "current"})
            self.assertEqual(connect.call_count, 2)
            self.assertEqual(stop.call_count, 2)
            self.assertEqual(node.close.call_count, 2)
            for name in ("former", "current"):
                self.assertTrue((output / (name + "-execute") / "physical-retirement.json").is_file())
                self.assertTrue(result["cases"][name]["physical"]["cleanPhysicalRetirement"])
            self.assertFalse(result["allAcceptanceCriteriaPassed"])
            self.assertFalse(result["packagedDistributionQualified"])

    def test_execution_refuses_private_store_drift_before_node_reconnect(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            work = output / "current-node"; work.mkdir()
            config = work / "node.json"; write_json(config, {})
            original = {"sha256": "sha256:" + "a" * 64}
            candidate = {"clock": {"original": True}, "inputs": {}, "recipientPort": 12345,
                         "cases": {"current": {"configFile": "node.json",
                             "configSha256": file_identity(config, 262144),
                             "physical": {"privateStoreCapture": original}}}}
            with patch.object(program, "_review", return_value=candidate), \
                 patch.object(program, "deadline", return_value=100), \
                 patch.object(program, "inputs", return_value=({"latent": Path("cli"),
                     "latentd": Path("node")}, {})), \
                 patch.object(program, "RecordingClient", return_value=SimpleNamespace()), \
                 patch.object(program, "start_provider", return_value=(object(), 12345)), \
                 patch.object(program, "close_failed_provider", return_value={"closed": True}), \
                 patch.object(program, "private_store", return_value={"sha256": "sha256:" + "b" * 64}), \
                 patch.object(program, "connect") as connect, self.assertRaises(WorkflowError):
                program.execute(Path("native"), Path("receipt"), Path("builds"), Path("releases"),
                                output, approved_sha256="0" * 64)
            connect.assert_not_called()
            self.assertFalse((output / "execution.json").exists())
            self.assertEqual(json.loads((output / "EXECUTION-FAILED.json").read_bytes())["reason"],
                             "java-diagnostic-retained-private-store-drift")

    def test_original_boot_and_deadline_cannot_be_extended_or_expired(self):
        original = {"bootId": "original", "deadlineMonotonicNanos": "150000000000"}
        with patch.object(Path, "read_text", return_value="original"), patch.object(program.time, "monotonic", return_value=100):
            self.assertEqual(program.deadline(original), 150)
            for end in ("99000000000", "1001000000001", "false"):
                with self.assertRaises(WorkflowError): program.deadline({**original, "deadlineMonotonicNanos": end})
        with patch.object(Path, "read_text", return_value="new-boot"):
            with self.assertRaises(WorkflowError): program.deadline(original)

    def test_review_refuses_changed_bytes_nonzero_activity_and_unknown_physical_retirement(self):
        raw_inventory = b'{"data":{"kind":"directory"}}'
        capture = {"root": "data", "entries": 1, "files": 0, "ownerUid": 1000, "ownerGid": 1000,
                   "sha256": "sha256:" + hashlib.sha256(raw_inventory).hexdigest(), "bytes": len(raw_inventory)}
        original = {"schemaVersion": program.SCHEMA, "status": "prepared", "applicationCapabilityPolicyMutations": 0,
            "guestInvocations": 0, "providerRequests": 0, "independentPolicyApprovalRequired": True,
            "cases": {"current": {"physical": {"cleanPhysicalRetirement": True,
                "privateStoreCapture": capture}}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "current-prepare"; evidence.mkdir()
            (evidence / "private-store-capture.json").write_bytes(raw_inventory)
            for index, value in enumerate((original, {**original, "providerRequests": 1},
                {**original, "providerRequests": False}, {**original, "cases": {}},
                {**original, "cases": {"current": {"physical": {"cleanPhysicalRetirement": "unknown"}}}},
                {**original, "cases": {"current": {"physical": {"cleanPhysicalRetirement": True}}}})):
                path = root / f"candidate-{index}.json"; write_json(path, value)
                approved = file_identity(path)["sha256"][7:]
                if index == 0: self.assertEqual(program._review(path, approved), original)
                else:
                    with self.assertRaises(WorkflowError): program._review(path, approved)
                with self.assertRaises(WorkflowError): program._review(path, "0" * 64)
            (evidence / "private-store-capture.json").write_bytes(b"changed")
            with self.assertRaises(WorkflowError): program._review(root / "candidate-0.json",
                file_identity(root / "candidate-0.json")["sha256"][7:])

    def test_current_policy_absence_is_authoritative_known_and_scoped_before_any_mutation(self):
        row = {"kind": "policy", "id": "original-policy"}
        for category, known in (("success", True), ("not-found", False), ("not-found", True)):
            calls = []
            def read(*args, **kwargs):
                calls.append(args)
                return {"category": category, "outcomeKnown": known, "data": {"stateVersion": "0"}}
            client = SimpleNamespace(call=read)
            if category == "not-found" and known:
                self.assertEqual(len(program._absent_policies(client, {"initial": [row]})), 1)
            else:
                with self.assertRaises(WorkflowError): program._absent_policies(client, {"initial": [row]})
            self.assertEqual(calls, [("policy", "--kind", "policy", "get", "--id", "original-policy")])


@unittest.skipUnless(sys.platform == "linux" and hasattr(os, "geteuid"), "Linux descriptor scan")
class JavaDiagnosticPrivateStoreTests(unittest.TestCase):
    def test_shared_scan_accepts_coupled_links_and_refuses_external_links_and_symlinks(self):
        from tools.container_runtime import storage
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); root.chmod(0o700)
            work = root / "work"; work.mkdir(mode=0o700)
            data = work / "data"; data.mkdir(mode=0o700)
            (data / "a").write_bytes(b"retained-original")
            os.link(data / "a", data / "b")
            owner = (os.geteuid(), os.getegid())
            def scan(): return storage.scan(work, time.monotonic() + 5, roots=("data",), owner=owner)
            observed = scan()
            self.assertEqual(observed["data/a"]["linkGroup"], observed["data/b"]["linkGroup"])
            self.assertEqual(observed["data/a"]["links"], 2)
            os.link(data / "a", root / "outside")
            with self.assertRaisesRegex(Exception, "snapshot-hardlink-outside-coupled-roots"): scan()
            (root / "outside").unlink()
            (data / "link").symlink_to("a")
            with self.assertRaises(Exception): scan()

    def test_shared_scan_refuses_mutation_and_entry_byte_time_limits(self):
        from tools.container_runtime import storage
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary) / "work"; work.mkdir(mode=0o700)
            data = work / "data"; data.mkdir(mode=0o700)
            source = data / "a"; source.write_bytes(b"two bytes")
            owner = (os.geteuid(), os.getegid())
            with patch.object(storage, "MAX_ENTRIES", 1), self.assertRaises(Exception):
                storage.scan(work, time.monotonic() + 5, roots=("data",), owner=owner)
            with patch.object(storage, "MAX_BYTES", 1), self.assertRaises(Exception):
                storage.scan(work, time.monotonic() + 5, roots=("data",), owner=owner)
            with self.assertRaises(Exception):
                storage.scan(work, time.monotonic() - 1, roots=("data",), owner=owner)
            with source.open("rb") as stream, self.assertRaisesRegex(Exception, "file-read-time-bound"):
                storage.files.digest_fd(stream.fileno(), deadline=time.monotonic() - 1)
            original = storage.files.digest_fd
            def mutate(fd, maximum, **options):
                result = original(fd, maximum, **options)
                source.write_bytes(b"new bytes")
                return result
            with patch.object(storage.files, "digest_fd", side_effect=mutate), \
                 self.assertRaisesRegex(Exception, "snapshot-source-changed"):
                storage.scan(work, time.monotonic() + 5, roots=("data",), owner=owner)


if __name__ == "__main__":
    unittest.main()
