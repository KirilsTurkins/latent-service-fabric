"""Bounds and fixture identities, not a substitute for real T1 qualification."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.phase2_operator_process import WorkflowError, read_json, write_json
from tools.phase3_web_assets import immutable_assets, revoked_assets
from tools.phase3_web_qualification import renewal, trigger_lifecycle
from tools.run_angular_t1_workflow import QualificationClient
from tools.phase3_web_scenario import (
    MEDIA, MIB, PREPARATION_MILLIS, budget, configure_angular_node, deployment_manifest,
    fixture_metadata, invocation_arguments, invoke, prepare, publish, selected_client_asset, tree_inventory,
)


def client(root):
    return SimpleNamespace(directory=root, deadline=time.monotonic() + 30,
                           cancellation=SimpleNamespace(check=lambda: None), call=Mock())


class AngularT1WorkflowTests(unittest.TestCase):
    def test_publication_busy_retries_only_identical_uncommitted_operation(self):
        caller = client(Path("unused"))
        rejected = {"category": "platform-failure", "error": {"code": "unavailable"}, "outcomeKnown": False}
        absent = {"outcomeKnown": False, "data": {"operation": None}}
        receipt = {"operationId": "publish-angular", "publication": {"tenant": "tests"},
                   "actor": {"subject": "workflow-operator"}, "replayed": False}
        accepted = {"category": "success", "outcomeKnown": True, "data": {"operation": receipt, "auditAck": {}}}
        caller.call.side_effect = [rejected, absent, accepted]
        with patch("tools.phase3_web_scenario.time.sleep"):
            self.assertEqual(publish(caller, Path("fixture"), "angular"), receipt)
        self.assertEqual(caller.call.call_args_list[0].args, caller.call.call_args_list[2].args)
        self.assertEqual(caller.call.call_args_list[1].args, ("web", "operation", "publish-angular"))
        self.assertLessEqual(caller.call.call_args_list[2].kwargs["timeout"], caller.call.call_args_list[0].kwargs["timeout"])
        self.assertEqual(caller.publication_refusals[0]["outcomeKnown"], False)

        publication = "publication:sha256:" + "a" * 64
        record = {"packageDigest": "sha256:" + "b" * 64}
        renewal_receipt = {
            "operationId": "renew-angular",
            "publication": {"id": publication, "tenant": "tests"},
            "actor": {"subject": "workflow-operator"},
            "resultingGeneration": "2",
        }
        unavailable = {"category": "platform-failure", "error": {"code": "unavailable"},
                       "outcomeKnown": False}
        absent = {"outcomeKnown": False, "data": {"operation": None}}
        accepted = {"category": "success", "outcomeKnown": True,
                    "data": {"operation": renewal_receipt, "auditAck": {}}}
        caller = client(Path("unused"))
        caller.call.side_effect = [unavailable, absent, accepted]
        with patch("tools.phase3_web_qualification.prepare",
                   side_effect=[{"category": "platform-failure"}, None]), \
             patch("tools.phase3_web_qualification.invoke"), \
             patch("tools.phase3_web_qualification.deploy", return_value={"generation": "2"}), \
             patch("tools.phase3_web_qualification.time.sleep"):
            _, renewed = renewal(caller, Path("fixture"), record, publication, {"generation": "1"})
        self.assertEqual(renewed, renewal_receipt)
        self.assertEqual(caller.call.call_args_list[0].args, caller.call.call_args_list[2].args)
        self.assertEqual(caller.call.call_args_list[1].args, ("web", "operation", "renew-angular"))

        caller = client(Path("unused"))
        caller.call.side_effect = [
            unavailable,
            {"outcomeKnown": True, "data": {"operation": renewal_receipt}},
        ]
        with patch("tools.phase3_web_qualification.prepare",
                   side_effect=[{"category": "platform-failure"}, None]), \
             patch("tools.phase3_web_qualification.invoke"), \
             patch("tools.phase3_web_qualification.deploy", return_value={"generation": "2"}):
            _, renewed = renewal(caller, Path("fixture"), record, publication, {"generation": "1"})
        self.assertEqual(renewed, renewal_receipt)
        self.assertEqual(caller.call.call_count, 2)

    def test_publication_refusal_does_not_replay_denial_or_committed_uncertainty(self):
        for rejected, lookup, expected_calls in (
            ({"category": "platform-failure", "error": {"code": "permission-denied"}}, None, 1),
            ({"category": "platform-failure", "error": {"code": "unavailable"}},
             {"outcomeKnown": True, "data": {"operation": {"replayed": True}}}, 2),
        ):
            caller = client(Path("unused"))
            caller.call.side_effect = [rejected, lookup]
            with self.assertRaises(WorkflowError):
                publish(caller, Path("fixture"), "angular")
            self.assertEqual(caller.call.call_count, expected_calls)
        caller = client(Path("unused"))
        caller.call.side_effect = [{"category": "platform-failure", "error": {"code": "unavailable"}, "outcomeKnown": False},
                                 {"outcomeKnown": False, "data": {"operation": None}}] * 3
        with patch("tools.phase3_web_scenario.time.sleep"), self.assertRaisesRegex(WorkflowError, "admission-busy"):
            publish(caller, Path("fixture"), "angular")
        self.assertEqual(caller.call.call_count, 6)

    def test_trigger_deletion_checks_one_explicit_mutation_and_its_retained_generation(self):
        triggers = {"alice.angular.test": "alice", "bob.angular.test": "bob", "foreign.angular.test": "foreign"}
        responses = [
            {"data": {"nextPageToken": None, "triggers": [
                {"manifest": {"metadata": {"name": name}}} for name in triggers.values()]}},
            {"data": {"stateVersion": "7", "trigger": {"generation": "6"}}},
            {"outcomeKnown": True, "data": {"generation": "6", "stateVersion": "8"}},
            {"outcomeKnown": True, "data": {"disposition": "found", "executionPermission": False,
                                          "receipt": {"objectGeneration": "6", "stateVersion": "8"}}},
            {"data": {"trigger": None}},
        ]
        caller = client(Path("unused"))
        caller.call.side_effect = responses
        with patch("tools.phase3_web_qualification.http_response") as request:
            result = trigger_lifecycle(caller, None, triggers)
            self.assertTrue(result["removedGenerationPreserved"])
            self.assertEqual(caller.call.call_count, 5)
            self.assertEqual(caller.call.call_args_list[2].args,
                             ("trigger", "delete", "bob", "--operation-id", "delete-bob-trigger",
                              "--expected-generation", "6", "--expected-state-version", "7"))
            request.assert_called_once_with(caller, None, "bob.angular.test", expected=404)
        uncertain = copy.deepcopy(responses)
        uncertain[2]["outcomeKnown"] = False
        caller.call.reset_mock(side_effect=True)
        caller.call.side_effect = uncertain
        with self.assertRaisesRegex(WorkflowError, "angular-trigger-delete-outcome"):
            trigger_lifecycle(caller, None, triggers)
        self.assertEqual(caller.call.call_count, 3)

    def test_failure_diagnostic_adds_only_a_fixed_operation_name(self):
        caller = QualificationClient.__new__(QualificationClient)
        with patch("tools.phase2_operator_process.Client.call", side_effect=WorkflowError("bounded-code")) as invoked:
            with self.assertRaisesRegex(WorkflowError, "^web-renew-evidence:bounded-code$"):
                caller.call("--rpc-timeout-ms", "30000", "web", "renew-evidence", "--evidence", "/private/node/path")
            self.assertEqual(invoked.call_count, 1)
            with self.assertRaisesRegex(WorkflowError, "^unclassified:bounded-code$"):
                caller.call("/private/node/path", "secret-value")

    def test_asset_checks_pin_publication_bytes_and_never_use_rendered_html(self):
        publication = "publication:sha256:" + "a" * 64
        content = b"actual immutable browser bytes"
        asset = {"path": "/client/main.js", "size": len(content), "mediaType": "text/javascript",
                 "digest": "sha256:" + hashlib.sha256(content).hexdigest()}
        headers = {"content-type": asset["mediaType"], "content-length": str(asset["size"]),
                   "cache-control": "private, max-age=31536000, immutable",
                   "x-content-type-options": "nosniff", "etag": '"identity-sha256-' + "b" * 64 + '"'}

        def response(_client, _node, host, path, method="GET", expected=200, **_options):
            self.assertTrue(path.startswith("/_lsf/assets/" + publication + "/"))
            if expected in (403, 404, (403, 404)):
                return b"", {}
            return (content if method == "GET" and expected == 200 else b""), headers

        with patch("tools.phase3_web_assets.http_response", side_effect=response) as requests:
            result = immutable_assets(None, None, {"assets": [asset]}, publication)
            self.assertEqual(result["verifiedAssets"], 1)
            self.assertEqual(requests.call_count, 7)
            revoked = revoked_assets(None, None, {"assets": [asset]}, publication)
            self.assertTrue(revoked["revokedGetAndHeadDenied"])
            self.assertEqual(requests.call_count, 9)
        with patch("tools.phase3_web_assets.http_response", return_value=(b"corrupt", headers)):
            with self.assertRaisesRegex(WorkflowError, "angular-asset-content-identity"):
                immutable_assets(None, None, {"assets": [asset]}, publication)

    def test_configuration_keeps_external_profile_protected_key_and_independent_compile_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, node = root / "fixture", root / "node"
            fixture.mkdir()
            node.mkdir()
            write_json(fixture / "policy.json", {"formatVersion": 1})
            compiler = root / "compiler"
            compiler.write_bytes(b"bounded approved binary fixture")
            path, configured = configure_angular_node(client(root), node, fixture, compiler)
            self.assertEqual(read_json(path), configured)
            self.assertEqual(configured["securityProfile"], "external-capsule-v1")
            self.assertEqual(configured["supplyChain"]["mode"], "enforced")
            self.assertEqual(configured["rendererProfile"], "angular-ssr-component-v1")
            self.assertEqual(configured["execution"]["maximumWallTimeMillis"], 5000)
            self.assertEqual(configured["isolatedAot"]["process"]["jobTimeoutMillis"], PREPARATION_MILLIS)
            self.assertEqual(configured["isolatedAot"]["keyFile"], "native.key")
            self.assertEqual(len((node / "native.key").read_bytes()), 32)
            self.assertNotIn(bytes([83]) * 32, path.read_bytes())
            self.assertFalse((node / "data").exists())
            self.assertNotIn("providers", configured)
            self.assertEqual(configured["httpIngress"]["authentication"]["mode"], "public-origins")

    def test_prepare_is_one_explicit_call_and_never_claims_execution_authority(self):
        prepared = client(Path("unused"))
        publication = "publication:sha256:" + "a" * 64
        prepared.call.return_value = {"outcomeKnown": True, "data": {
            "prepared": True, "executionAuthorized": False,
            "publication": {"id": publication}, "lifecycleGeneration": "7"}}
        prepare(prepared, publication, 7)
        prepared.call.assert_called_once()
        arguments = prepared.call.call_args
        self.assertEqual(arguments.args[:4], ("--rpc-timeout-ms", str(PREPARATION_MILLIS), "web", "prepare"))
        self.assertEqual(arguments.kwargs["timeout"], 310)
        for field, value in (("executionAuthorized", True), ("prepared", False), ("lifecycleGeneration", "8")):
            changed = copy.deepcopy(prepared.call.return_value)
            changed["data"][field] = value
            prepared.call.return_value = changed
            with self.subTest(field=field), self.assertRaises(WorkflowError):
                prepare(prepared, publication, 7)

    def test_selected_deployment_never_fabricates_a_capsule_or_capability_grant(self):
        record = {"service": "angular-hello", "componentDigest": "sha256:" + "b" * 64}
        selected = "publication:sha256:" + "a" * 64
        manifest = deployment_manifest(record, selected)
        self.assertEqual(manifest["spec"]["publication"], selected)
        self.assertEqual(manifest["spec"]["release"], record["componentDigest"])
        self.assertEqual(manifest["spec"]["grants"], [])
        self.assertEqual(manifest["spec"]["resources"], budget())
        self.assertEqual(budget()["memoryBytes"], 256 * MIB)
        self.assertEqual(budget()["outboundRequests"], 0)

    def test_public_web_invocation_has_no_guest_supplied_actor_or_tenant(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            arguments = invocation_arguments(client(root), {"service": "angular-hello"}, "/spin", "cancel")
            request = read_json(root / "cancel-input.json")
            self.assertEqual(len(request), 1)
            self.assertNotIn("principal", request[0])
            self.assertNotIn("tenant", request[0])
            self.assertEqual(request[0]["path"], "/spin")
            self.assertEqual(request[0]["query"], {"none": None})
            self.assertEqual(request[0]["media-type"], {"none": None})
            self.assertEqual(arguments[:3], ["--rpc-timeout-ms", "5000", "invoke"])
            self.assertNotIn("outboundRequests", read_json(root / "cancel-budget.json"))

    def test_inventory_hashes_large_artifacts_incrementally_with_finite_total(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "image").write_bytes(b"x" * 32768)
            (root / "lock").touch()
            observed = tree_inventory(root, client(root), maximum_bytes=32768)
            self.assertEqual(observed["image"][0], 32768)
            self.assertEqual(observed["lock"], (0, None))
            with self.assertRaisesRegex(WorkflowError, "angular-inventory-bytes"):
                tree_inventory(root, client(root), maximum_bytes=32767)
            expired = client(root)
            expired.deadline = time.monotonic() - 1
            with self.assertRaisesRegex(WorkflowError, "workflow-deadline"):
                tree_inventory(root, expired)

    def test_render_checks_the_actual_cli_publication_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = "publication:sha256:" + "a" * 64
            record = {"service": "angular-hello", "componentDigest": "sha256:" + "b" * 64,
                      "assets": [{"path": "/client/main.js", "mediaType": "text/javascript"}]}
            html = ('<h1 ngh="0">workflow-operator</h1><script type="module" src="/_lsf/assets/'
                    + selected + '/client/main.js"></script>').encode()
            values = [{"status": 200, "body-base64": base64.b64encode(html).decode()}]
            caller = client(root)
            caller.call.return_value = {"outcomeKnown": True, "data": {
                "payload": {"encoding": "base64", "mediaType": MEDIA,
                            "data": base64.b64encode(json.dumps(values).encode()).decode()},
                "resolvedRevision": {"publicationId": selected, "releaseDigest": record["componentDigest"],
                                     "revisionId": "revision"}}}
            self.assertEqual(invoke(caller, record, selected, "first")["revision"], "revision")
            caller.call.return_value["data"]["resolvedRevision"]["publicationId"] = None
            with self.assertRaisesRegex(WorkflowError, "selected-render-publication"):
                invoke(caller, record, selected, "second")

    def test_rendered_script_must_use_the_exact_selected_publication(self):
        publication = "publication:sha256:" + "a" * 64
        record = {"assets": [{"path": "/client/main.js", "mediaType": "text/javascript"}]}
        selected = "/_lsf/assets/" + publication + "/client/main.js"
        selected_client_asset(record, publication, '<script src="' + selected + '"></script>')
        for locator in ("/client/main.js", selected.replace("a" * 64, "b" * 64), selected + "?alias=1"):
            with self.subTest(locator=locator), self.assertRaisesRegex(WorkflowError, "angular-client-asset-publication"):
                selected_client_asset(record, publication, '<script src="' + locator + '"></script>')

    def test_fixture_requires_actual_observation_and_independent_package_identity(self):
        metadata = {"schemaVersion": "latent.phase3.angular.fixture.v1", "tenant": "tests",
                    "actualAngularBuild": True, "reproducibility": "not-checked",
                    "dependencyCompleteness": "declared-inputs-incomplete", "fixtures": [
                        {"name": name, "packageDigest": "sha256:" + digit * 64,
                         "componentDigest": "sha256:" + "d" * 64}
                        for name, digit in (("angular", "a"), ("alternate", "b"), ("missing-sbom", "c"))]}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "fixture.json"
            write_json(path, metadata)
            self.assertEqual(set(fixture_metadata(root)[1]), {"angular", "alternate", "missing-sbom"})
            for field, value in (("actualAngularBuild", False), ("reproducibility", "reproducible"),
                                 ("dependencyCompleteness", "complete")):
                changed = copy.deepcopy(metadata)
                changed[field] = value
                path.write_text(json.dumps(changed), encoding="utf-8")
                with self.subTest(field=field), self.assertRaises(WorkflowError):
                    fixture_metadata(root)


if __name__ == "__main__":
    unittest.main()
