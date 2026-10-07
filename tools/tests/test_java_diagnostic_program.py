"""Review/expiry/ownership guard tests, not Java or native-node qualification."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
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

    def test_preparation_port_refuses_invalid_selection_and_preserves_bounded_peer_owner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, port in enumerate((False, True, -1, 1, 1023, 65536, "12345", None)):
                output = root / f"invalid-{index}"
                with patch.object(program, "clock") as clock, patch.object(program, "start_provider") as peer, \
                     self.subTest(port=port), self.assertRaisesRegex(WorkflowError, "unprivileged-loopback-port"):
                    program.prepare(Path("native"), Path("receipt"), Path("builds"), Path("releases"),
                                    output, provider_port=port)
                clock.assert_not_called(); peer.assert_not_called()
                self.assertFalse(output.exists())
            for selected_port in (0, 1024, 12345, 65535):
                output = root / f"selected-{selected_port}"
                actual_port = selected_port or 12345
                owner = object()
                with patch.object(program, "clock", return_value={"original": True}), \
                     patch.object(program, "deadline", return_value=150), \
                     patch.object(program, "inputs", return_value=({"latent": Path("cli")}, {})), \
                     patch.object(program, "RecordingClient", return_value=owner), \
                     patch.object(program, "start_provider", return_value=(owner, actual_port)) as peer, \
                     patch.object(program, "configure", side_effect=WorkflowError("original-node-refused")) as configure, \
                     patch.object(program, "session") as node, \
                     patch.object(program, "close_failed_provider", return_value={"closed": True}) as cleanup, \
                     self.subTest(port=selected_port), self.assertRaisesRegex(WorkflowError, "original-node-refused"):
                    program.prepare(Path("native"), Path("receipt"), Path("builds"), Path("releases"),
                                    output, provider_port=selected_port, ingress_port=23456)
                peer.assert_called_once_with(owner, output / "prepare-peer", maximum_seconds=1200,
                                             port=selected_port or None)
                configure.assert_called_once_with(output / "former-node", Path("releases"),
                                                  http=False, former_profile=True, ingress_port=0)
                cleanup.assert_called_once_with(owner); node.assert_not_called()
                record = json.loads((output / "PREPARE-FAILED.json").read_bytes())
                self.assertEqual(record["recipientPort"], actual_port)
                self.assertEqual(record["clock"], {"original": True})
                self.assertEqual([record[key] for key in (
                    "applicationCapabilityPolicyMutations", "guestInvocations", "providerRequests")], [0, 0, 0])
                self.assertFalse((output / "candidate.json").exists())

    def test_cli_forwards_prepare_port_and_refuses_execution_override(self):
        from contextlib import redirect_stderr
        from io import StringIO
        import sys
        from tools import qualify_java_preparation_diagnostics as entrypoint
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            arguments = []
            for name in ("native-directory", "native-receipt", "builds", "releases", "output"):
                arguments += ["--" + name, str(source)]
            for flags, port, ingress in (([], 0, 0), (["--provider-port", "12345"], 12345, 0),
                                        (["--ingress-port", "23456"], 0, 23456)):
                with patch.object(sys, "argv", ["diagnostics", "prepare", *arguments, *flags]), \
                     patch.object(program, "prepare") as prepare:
                    entrypoint.main()
                prepare.assert_called_once_with(source.resolve(), source.resolve(), source.resolve(),
                    source.resolve(), source.resolve(), former_child=True, provider_port=port, ingress_port=ingress)
            for flags in (["--provider-port", "1023"], ["--provider-port", "65536"],
                          ["--provider-port", "invalid"], ["--ingress-port", "1023"],
                          ["--ingress-port", "65536"], ["--ingress-port", "invalid"]):
                with patch.object(sys, "argv", ["diagnostics", "prepare", *arguments, *flags]), \
                     patch.object(program, "prepare") as prepare, redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    entrypoint.main()
                prepare.assert_not_called()
            for flag in ("--provider-port", "--ingress-port"):
                with patch.object(sys, "argv", ["diagnostics", "execute", *arguments, flag, "12345",
                                               "--approved-candidate-sha256", "0" * 64]), \
                     patch.object(program, "execute") as execute, redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    entrypoint.main()
                execute.assert_not_called()

    def test_explicit_ingress_port_preserves_config_bytes_and_rejects_invalid_selection(self):
        from tools.java_http_composition import node
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            releases = root / "releases"; releases.mkdir(); write_json(releases / "policy.json", {})
            original = root / "original"; original.mkdir()
            explicit = root / "explicit"; explicit.mkdir()
            with patch.object(node.socket, "socket") as sockets:
                reservation = sockets.return_value.__enter__.return_value
                reservation.getsockname.return_value = ("127.0.0.1", 23456)
                auto_config, auto_host = node.configure(original, releases)
                reservation.bind.assert_called_once_with(("127.0.0.1", 0))
                reservation.bind.reset_mock()
                config, host = node.configure(explicit, releases, ingress_port=23456)
                reservation.bind.assert_called_once_with(("127.0.0.1", 23456))
                drift = root / "drift"; drift.mkdir()
                reservation.getsockname.return_value = ("127.0.0.1", 23457)
                with self.assertRaisesRegex(WorkflowError, "original-ingress-port"):
                    node.configure(drift, releases, ingress_port=23456)
            self.assertEqual(config.read_bytes(), auto_config.read_bytes())
            self.assertEqual(host, auto_host)
            self.assertEqual(host, "localhost:23456")
            for index, port in enumerate((False, True, -1, 1, 1023, 65536, "23456", None)):
                output = root / f"invalid-{index}"
                with patch.object(node, "configure_node") as configure, patch.object(node.socket, "socket") as sockets, \
                     self.subTest(port=port), self.assertRaisesRegex(WorkflowError, "unprivileged-loopback-ingress-port"):
                    node.configure(output, releases, ingress_port=port)
                configure.assert_not_called(); sockets.assert_not_called(); self.assertFalse(output.exists())
                with patch.object(program, "clock") as clock, patch.object(program, "start_provider") as peer, \
                     self.assertRaisesRegex(WorkflowError, "unprivileged-loopback-ingress-port"):
                    program.prepare(Path("native"), Path("receipt"), Path("builds"), releases, output,
                                    ingress_port=port)
                clock.assert_not_called(); peer.assert_not_called(); self.assertFalse(output.exists())
            with patch.object(node, "configure_node") as configure, self.assertRaisesRegex(WorkflowError, "requires-http"):
                node.configure(root / "no-http", releases, http=False, ingress_port=23456)
            configure.assert_not_called()
            output = root / "current-preparation"
            with patch.object(program, "clock", return_value={"original": True}), \
                 patch.object(program, "deadline", return_value=150), \
                 patch.object(program, "inputs", return_value=({"latent": Path("cli")}, {})), \
                 patch.object(program, "start_provider", return_value=(object(), 12345)), \
                 patch.object(program, "configure", side_effect=WorkflowError("original-node-refused")) as configure, \
                 patch.object(program, "close_failed_provider", return_value={"closed": True}), \
                 self.assertRaisesRegex(WorkflowError, "original-node-refused"):
                program.prepare(Path("native"), Path("receipt"), Path("builds"), releases, output,
                                former_child=False, ingress_port=23456)
            configure.assert_called_once_with(output / "current-node", releases,
                                              http=True, former_profile=False, ingress_port=23456)


class JavaDiagnosticReviewTests(unittest.TestCase):
    def test_child_fuel_requires_declared_adapter_503_and_exact_guest_fuel_reason(self):
        from base64 import b64encode
        from contextlib import ExitStack
        from tools.java_http_composition import resource_diagnostics as resources
        from tools.java_http_composition import context
        from tools.java_http_composition.node import ADAPTER

        budget = {"cpuFuel": 10_000_000_000, "memoryBytes": 134217728,
                  "wallTimeLimitMillis": 120000, "childCalls": 4, "outboundRequests": 2,
                  "stateReadBytes": 0, "stateWriteBytes": 0, "blobReadBytes": 0,
                  "blobWriteBytes": 0, "logBytes": 0, "effectCount": 0}
        activation = "java-diagnostics-child-fuel"
        parent = {"activationId": activation, "parentActivationId": None, "rootActivationId": activation,
                  "principalKind": "administrator", "callerService": None,
                  "effectiveDeadlineUnixMillis": "200000", "grantedBudget": {**budget, "cpuFuel": resources.FUEL}}
        child = {"activationId": "actual-child", "parentActivationId": activation, "rootActivationId": activation,
                 "principalKind": "service", "callerService": ADAPTER, "terminalState": "resource_exhausted",
                 "effectiveDeadlineUnixMillis": "150000", "grantedBudget": {**budget,
                    "cpuFuel": 497234471, "memoryBytes": 62324736, "wallTimeLimitMillis": 59959,
                    "childCalls": 0, "outboundRequests": 1}, "diagnosticIsTerminal": True,
                 "diagnostic": {"stage": 5, "reason": 11}}
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(evidence=Path(temporary), call=lambda *args: {
                "data": {"finalConsumption": {"cpuFuel": 497234471}}})
            for public_status, reason in ((503, 11), (500, 11), (503, 1)):
                client.evidence = Path(temporary) / f"case-{public_status}-{reason}"
                client.evidence.mkdir()
                current_child = {**child, "diagnostic": {"stage": 5, "reason": reason}}
                payload = b64encode(json.dumps([{"status": public_status}]).encode()).decode()
                invocation = {"category": "success", "data": {"payload": {"data": payload}}}
                with ExitStack() as stack:
                    original = stack.enter_context(patch.object(resources, "invoke", return_value=invocation))
                    stack.enter_context(patch.object(context, "tree", return_value={"nodes": [parent, current_child]}))
                    stack.enter_context(patch.object(resources, "idle", return_value={"owners": 0}))
                    stack.enter_context(patch.object(resources, "fresh_status", return_value={"httpStatus": 200}))
                    with self.subTest(public_status=public_status, reason=reason):
                        if public_status == 500:
                            with self.assertRaisesRegex(WorkflowError, "original-child-trap-response"):
                                resources.fuel(client, {"adapter": {"budget": budget}}, "localhost:23456")
                        else:
                            result = resources.fuel(client, {"adapter": {"budget": budget}}, "localhost:23456")
                            self.assertEqual(result["status"], "passed" if reason == 11 else "typed-diagnostic-unexpected")
                            self.assertEqual(result["childStatus"]["finalConsumption"]["cpuFuel"], 497234471)
                        self.assertEqual(original.call_args.kwargs["budget_override"]["cpuFuel"], resources.FUEL)

    def test_current_program_calls_original_context_owner_and_preserves_service_admission_order(self):
        from contextlib import ExitStack
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            client, node = object(), object()
            targets = {"adapter": {"generation": "1", "grants": []}}
            prepared = {"publications": {"adapter": "original-adapter", "domain": "original-domain"}}
            missing = {"tree": {"nodes": [{"diagnostic": {"stage": 4, "reason": 8}}]}}
            with ExitStack() as stack:
                route = stack.enter_context(patch.object(program, "route"))
                stack.enter_context(patch.object(program.context, "capture_http", return_value=missing))
                service = stack.enter_context(patch.object(program, "service_grant", return_value="1"))
                stack.enter_context(patch.object(program, "deploy", return_value=targets["adapter"]))
                stack.enter_context(patch.object(program, "fresh_status", return_value={"status": "passed"}))
                stack.enter_context(patch.object(program.inspection, "authority", return_value={}))
                owner = stack.enter_context(patch.object(program.context, "qualify", autospec=True,
                                                         return_value={"status": "passed"}))
                stack.enter_context(patch.object(program.resource_diagnostics, "fuel", return_value={"status": "passed"}))
                stack.enter_context(patch.object(program.resource_diagnostics, "queue", return_value={"status": "passed"}))
                stack.enter_context(patch.object(provider_timeout, "qualify", return_value={"status": "passed"}))
                stack.enter_context(patch("tools.static_api.node.policy", return_value={"generation": "2"}))
                stack.enter_context(patch.object(program, "rebind", return_value={}))
                stack.enter_context(patch.object(history, "qualify", return_value={"status": "passed"}))
                result = program._current(client, node, targets, prepared, Path("releases"), "localhost:23456",
                                          12345, Path("peer"), output, None)
                self.assertEqual(result["status"], "passed")
                owner.assert_called_once_with(client, targets, Path("releases"), prepared["publications"], "localhost:23456", output)
                self.assertIs(result["initialMissingGrant"], missing)
                self.assertEqual(service.call_count, 2)
                self.assertEqual(route.call_count, 3)
                with self.assertRaisesRegex(WorkflowError, "service-admission-order"):
                    program._current(client, node, targets, prepared, Path("releases"), "localhost:23456",
                                     12345, Path("peer"), output, "unexpected-existing-grant")
                self.assertEqual(service.call_count, 2)

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
                                  "host": "localhost"}
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

    def test_original_boot_and_deadline_cannot_be_extended_or_expired(self):
        original = {"bootId": "original", "deadlineMonotonicNanos": "150000000000"}
        with patch.object(Path, "read_text", return_value="original"), patch.object(program.time, "monotonic", return_value=100):
            self.assertEqual(program.deadline(original), 150)
            for end in ("99000000000", "1001000000001", "false"):
                with self.assertRaises(WorkflowError): program.deadline({**original, "deadlineMonotonicNanos": end})
        with patch.object(Path, "read_text", return_value="new-boot"):
            with self.assertRaises(WorkflowError): program.deadline(original)

    def test_review_refuses_changed_bytes_nonzero_activity_and_unknown_physical_retirement(self):
        original = {"schemaVersion": program.SCHEMA, "status": "prepared", "applicationCapabilityPolicyMutations": 0,
            "guestInvocations": 0, "providerRequests": 0, "independentPolicyApprovalRequired": True,
            "cases": {"current": {"physical": {"cleanPhysicalRetirement": True}}}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, value in enumerate((original, {**original, "providerRequests": 1},
                {**original, "providerRequests": False}, {**original, "cases": {}},
                {**original, "cases": {"current": {"physical": {"cleanPhysicalRetirement": "unknown"}}}})):
                path = root / f"candidate-{index}.json"; write_json(path, value)
                approved = file_identity(path)["sha256"][7:]
                if index == 0: self.assertEqual(program._review(path, approved), original)
                else:
                    with self.assertRaises(WorkflowError): program._review(path, approved)
                with self.assertRaises(WorkflowError): program._review(path, "0" * 64)

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


if __name__ == "__main__":
    unittest.main()
