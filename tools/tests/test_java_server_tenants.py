"""Source and policy controls; actual same-node execution is a separate gate."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from tools.java_capsule_project import ROOT, validate
from tools.java_server_tenant_project import create
from tools.java_server_tenants import TenantControls
from tools.java_server_node import grant_runtime, runtime_config
from tools.rust_capsule_project import snapshot


class SharedTenantServer(unittest.TestCase):
    def test_neutral_project_retains_original_sdk_helper_and_zero_egress_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "project")
            files = snapshot(project)
            declaration, _lock, _pins = validate(files)
            self.assertIsNone(declaration["tenant"])
            self.assertEqual(declaration["service"], "tenant-isolation-server")
            self.assertEqual(declaration["limits"]["outboundRequests"], 0)
            self.assertEqual(declaration["limits"]["memoryBytes"], 67108864)
            self.assertEqual(declaration["limits"]["cpuFuel"], 1000000000)
            self.assertEqual(declaration["limits"]["wallTimeLimitMillis"], 120000)
            self.assertEqual(files["src/outside/developer/routes/Router.java"],
                (ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes())
            self.assertIn(b'new Object[]{marker, input}', files["src/outside/developer/routes/TenantRoutes.java"])
            self.assertNotIn(b'dev.latent.guest', files["src/outside/developer/routes/TenantRoutes.java"])

    @unittest.skipUnless(shutil.which("javac"), "native JDK source control")
    def test_original_standard_api_handler_compiles_with_published_jdk_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / "project")
            result = subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", str(root / "classes"),
                *map(str, sorted((project / "src").rglob("*.java")))], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_second_scope_aliases_never_change_original_node_capacity_or_grant_authority(self):
        settings = {"cells": [{"capacity": 1}]}
        runtime_config(settings, "server")
        original = json.loads(json.dumps(settings["providers"]))
        observer = TenantControls(Path("unopened-fixture"))
        observer.configure(settings, "server")
        observer.configure_ingress(settings)
        self.assertIsNone(observer.grant_initial_http(None))
        self.assertEqual(settings["cells"], [{"capacity": 1}])
        self.assertEqual(settings["providers"]["bindings"][:3], original["bindings"])
        aliases = settings["providers"]["scalarAliases"]
        self.assertEqual({row["source"] for row in aliases}, {"clockMonotonic", "clockWall", "context"})
        self.assertTrue(all(row["identity"]["tenant"] == "foreign" for row in aliases))
        self.assertNotIn("activationRuntime", settings["providers"])
        self.assertNotIn("http", settings["providers"])

    def test_real_package_metadata_keeps_neutral_service_and_omits_tenant_without_rewriting_source(self):
        from unittest.mock import patch
        from tools.rust_capsule_build import package_inputs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / "project")
            files = snapshot(project)
            declaration, _lock, _pins = validate(files)
            output = root / "package-inputs"; output.mkdir()
            # Only unrelated compatibility/resource assembly is isolated here;
            # the real shared metadata emitter and fixture inputs remain in use.
            with patch("tools.rust_capsule_build.guest_compatibility_build.package_report"), \
                    patch("tools.rust_capsule_build.guest_resources.assemble", return_value=[]):
                package_inputs(output, declaration, {"exports": [], "imports": []}, files, b"metadata-control")
            manifest = json.loads((output / "capsule.json").read_bytes())
            deployment = json.loads((output / "deployment.json").read_bytes())
            self.assertEqual(manifest["metadata"]["name"], "tenant-isolation-server")
            self.assertNotIn("tenant", manifest["metadata"])
            self.assertNotIn("tenant", deployment["metadata"])
            self.assertEqual(deployment["spec"]["service"], manifest["metadata"]["name"])
            self.assertEqual(manifest["component"]["world"], declaration["world"])
            self.assertEqual(snapshot(project), files)
            from tools.qualify_java_server_tenants import select_initial_tenant
            signed_metadata = (output / "capsule.json").read_bytes()
            select_initial_tenant(output / "deployment.json")
            selected = json.loads((output / "deployment.json").read_bytes())
            deployment["metadata"]["tenant"] = "examples"
            self.assertEqual(selected, deployment)
            from tools.java_server_tenants import select_foreign_deployment
            foreign = select_foreign_deployment(selected)
            self.assertEqual(foreign["metadata"]["tenant"], "foreign")
            self.assertEqual(foreign["metadata"]["name"], selected["metadata"]["name"] + "-foreign")
            self.assertEqual(foreign["spec"], selected["spec"])
            self.assertEqual(selected, deployment)
            self.assertEqual((output / "capsule.json").read_bytes(), signed_metadata)
            self.assertEqual(snapshot(project), files)
            selected_bytes = (output / "deployment.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "tenant-isolation-neutral-deployment"):
                select_initial_tenant(output / "deployment.json")
            self.assertEqual((output / "deployment.json").read_bytes(), selected_bytes)

    def test_actual_tenant_workflow_creates_a_distinct_foreign_object_before_routes(self):
        from unittest.mock import Mock, patch
        from tools.phase2_operator_process import write_json
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture, client_root, route_root = (root / name for name in ("fixture", "client", "routes"))
            for directory in (fixture, client_root, route_root):
                directory.mkdir(mode=0o700)
            write_json(fixture / "release-set.json", {"tenant": None, "tenants": ["examples", "foreign"],
                "trust": "isolated-neutral-server-two-tenant-test-only"})
            name = "tenant-isolation-server"
            package = fixture / name
            package.mkdir()
            source = {"metadata": {"name": name, "tenant": "examples"},
                "spec": {"service": name, "grants": [], "resources": {"outboundRequests": 0}}}
            write_json(package / "deployment.json", source)
            original = (package / "deployment.json").read_bytes()
            client = SimpleNamespace(directory=client_root, executable="unused",
                cancellation=None, deadline=0)
            foreign = SimpleNamespace(directory=client_root / "foreign", call=Mock(return_value={
                "data": {"operation": {"publication": {"id": "foreign-publication"}}}}))
            captured = []
            def deploy(selected_client, path, publication):
                self.assertIs(selected_client, foreign)
                self.assertEqual(publication, "foreign-publication")
                captured.append(json.loads(path.read_bytes()))
                return {"name": captured[-1]["metadata"]["name"], "generation": "1"}
            with patch("tools.java_server_tenants.RecordingClient", return_value=foreign), \
                    patch("tools.java_server_tenants.deploy", side_effect=deploy), \
                    patch("tools.java_server_tenants.RecordedRouteClient", side_effect=RuntimeError("route-boundary")), \
                    self.assertRaisesRegex(RuntimeError, "^route-boundary$"):
                TenantControls(fixture)(client=client, node=SimpleNamespace(startup_record={"endpoint": "127.0.0.1:1"}),
                    record={"name": name}, publication="examples-publication", deployment={},
                    build=root / "unused-build", routes=SimpleNamespace(root=route_root, remove=Mock()),
                    manifests=[], mounts={}, route_client=None, evidence=root / "evidence",
                    check=None, denied_without_cell=None, grants=[], tls_context=object())
            self.assertEqual(len(captured), 1)
            self.assertEqual(captured[0]["metadata"], {"name": name + "-foreign", "tenant": "foreign"})
            self.assertEqual(captured[0]["spec"], source["spec"])
            self.assertEqual((package / "deployment.json").read_bytes(), original)

    def test_grants_require_exact_descriptor_tenant_and_separate_trigger_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            class Client:
                def __init__(self):
                    self.directory = directory
                    self.calls = []
                def call(self, *arguments):
                    self.calls.append(arguments)
            node = SimpleNamespace(startup_record={"providers": [{"id": name + "-foreign", "tenant": "foreign",
                "configurationDigest": "sha256:" + "a" * 64} for name in ("clockMonotonic", "clockWall", "context")]})
            client = Client()
            grants = grant_runtime(client, node, {"service": "server"}, "foreign-publication",
                tenant="foreign", principal="foreign-caller", suffix="-foreign")
            self.assertEqual(len(grants), 3)
            self.assertEqual(len(client.calls), 6)
            for name in ("clockMonotonic", "clockWall", "context"):
                policy = json.loads((directory / (name + "-policy.json")).read_bytes())
                self.assertEqual(policy["tenant"], "foreign")
                self.assertEqual(policy["rules"][0]["publications"], ["foreign-publication"])
                self.assertEqual(policy["rules"][0]["principals"], [{"kind": "trigger", "subject": "foreign-caller"}])
            node.startup_record["providers"][0]["tenant"] = "examples"
            with self.assertRaisesRegex(RuntimeError, "runtime-provider-tenant"):
                grant_runtime(client, node, {"service": "server"}, "foreign-publication",
                    tenant="foreign", principal="foreign-caller", suffix="-foreign")

    def test_runtime_grant_denial_requires_zero_guest_work_and_at_most_one_original_lease(self):
        import copy
        from tools.java_server_tenants import require_runtime_grant_denial
        consumption = {key: "0" for key in ("cpuFuel", "peakMemoryBytes", "stateReadBytes",
            "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes")}
        consumption.update(childCalls=0, outboundRequests=0, effectCount=0, wallTimeMicros="17")
        observed = {"terminalState": "rejected", "terminalOutcome": {"kind": "platform-failure",
            "error": {"code": "permission-denied", "retryable": False}}, "finalConsumption": consumption}
        before = {"cells": [{"class": "standard", "granted": "2"}]}
        after = {"cells": [{"class": "standard", "granted": "3"}]}
        self.assertEqual(require_runtime_grant_denial(observed, before, after), {"standard": 1})
        self.assertEqual(require_runtime_grant_denial(observed, before, before), {"standard": 0})
        for field in consumption.keys() - {"wallTimeMicros"}:
            for value in (1, "1", False, None):
                changed = copy.deepcopy(observed)
                changed["finalConsumption"][field] = value
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, "entered-guest"):
                    require_runtime_grant_denial(changed, before, after)
            changed = copy.deepcopy(observed)
            del changed["finalConsumption"][field]
            with self.subTest(missing=field), self.assertRaisesRegex(ValueError, "entered-guest"):
                require_runtime_grant_denial(changed, before, after)
        for field, value in (("terminalState", "completed"), ("terminalOutcome", None), ("finalConsumption", None)):
            changed = copy.deepcopy(observed); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_runtime_grant_denial(changed, before, after)
        for field, value in (("kind", "success"), ("error", None)):
            changed = copy.deepcopy(observed); changed["terminalOutcome"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_runtime_grant_denial(changed, before, after)
        for field, value in (("code", "unavailable"), ("retryable", True)):
            changed = copy.deepcopy(observed); changed["terminalOutcome"]["error"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                require_runtime_grant_denial(changed, before, after)
        for rows in ([{"class": "standard", "granted": "4"}],
                     [{"class": "standard", "granted": "1"}],
                     [{"class": "other", "granted": "3"}], after["cells"] * 2, []):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                require_runtime_grant_denial(observed, before, {"cells": rows})

    def test_runtime_grant_workflow_observes_the_original_foreign_root_and_pin(self):
        from unittest.mock import Mock, patch
        from tools import java_server_tenants as tenants
        foreign, client = object(), object()
        pin, expected = {"tenant": "foreign"}, {"selected": "original-foreign-pin"}
        before = {"cells": [{"class": "standard", "granted": "2"}]}
        after = {"cells": [{"class": "standard", "granted": "3"}]}
        consumption = {key: "0" for key in ("cpuFuel", "peakMemoryBytes", "stateReadBytes",
            "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes")}
        consumption.update(childCalls=0, outboundRequests=0, effectCount=0)
        observed = {"terminalState": "rejected", "terminalOutcome": {"kind": "platform-failure",
            "error": {"code": "permission-denied", "retryable": False}}, "finalConsumption": consumption}
        calls = []
        check = Mock(side_effect=lambda *args, **kwargs: calls.append((args, kwargs)))
        with patch.object(tenants, "roots", return_value=[{"activationId": "prior"}]) as roots, \
                patch.object(tenants, "execution_pin", return_value=expected) as select, \
                patch.object(tenants, "observe_idle", side_effect=[before, after]) as idle, \
                patch.object(tenants, "one_new_root", return_value="original-foreign-root") as root, \
                patch.object(tenants, "status", return_value=observed) as status:
            result = tenants.runtime_grant_denial(foreign, client, "server", pin, Path("evidence"), check)
        roots.assert_called_once_with(foreign, "server")
        select.assert_called_once_with(foreign, pin)
        root.assert_called_once_with(foreign, "server", {"prior"})
        status.assert_called_once_with(foreign, "original-foreign-root", expected, terminal="rejected")
        self.assertEqual(idle.call_args_list[0].args, (client, Path("evidence"), "before-foreign-runtime-grant-denial"))
        self.assertEqual(idle.call_args_list[1].args, (client, Path("evidence"), "after-foreign-runtime-grant-denial"))
        self.assertEqual(calls, [(("GET", "/hey", 403), {"authority": "foreign.server.test"})])
        self.assertEqual(result["retained"], observed)
        self.assertEqual(result["expectedPin"], expected)
        self.assertEqual(result["cellLeaseDelta"], {"standard": 1})
        self.assertEqual(result["status"], "denied-before-guest")


class OperatorTokenIsolation(unittest.TestCase):
    def setUp(self):
        self.pin = {"tenant": "foreign", "service": "server", "route": "server-foreign",
            "publication": "publication:sha256:" + "a" * 64, "revision": "revision-v1:sha256:" + "b" * 64,
            "deploymentGeneration": "2", "componentDigest": "sha256:" + "c" * 64}
        self.deployment = {"name": self.pin["route"], "service": self.pin["service"],
            "generation": self.pin["deploymentGeneration"], "publication": self.pin["publication"]}
        self.original_config, self.spoof_config = Path("authorized.json"), Path("spoof.json")

    def response(self, category, data, error=None):
        return {"schemaVersion": "latent.cli.result.v1", "command": "deployment get",
            "category": category, "outcomeKnown": True, "requestDispatched": True, "data": data, "error": error}

    def authorized(self):
        return self.response("success", {"deployment": {"generation": "2",
            "publication": {"tenant": "foreign", "id": self.pin["publication"]}, "manifest": {
                "metadata": {"name": self.pin["route"], "tenant": "foreign"}, "spec": {
                    "service": "server", "release": self.pin["componentDigest"],
                    "publication": self.pin["publication"]}}},
            "durability": None, "routeGeneration": None, "stateVersion": None})

    def route(self):
        return {"category": "success", "outcomeKnown": True, "data": {"snapshot": {
            "tenant": "foreign", "generation": "7", "snapshotDigest": "sha256:" + "d" * 64,
            "services": [{"tenant": "foreign", "routeId": self.pin["route"], "service": "server",
                "revisions": [{"revisionId": self.pin["revision"],
                    "releaseDigest": self.pin["componentDigest"], "weight": 10000}]}]}}}

    def not_found(self):
        return self.response("not-found", {"deployment": None, "durability": None,
            "routeGeneration": None, "stateVersion": None})

    def permission_denied(self):
        return self.response("platform-failure", {}, {"code": "permission-denied",
            "message": "The platform reported a failure.", "retryable": False, "details": []})

    def client(self, *, denied=None, exit_status=6, before=None, after=None, after_route=None,
               failure_stage=None, failure=None):
        from unittest.mock import Mock
        client = SimpleNamespace(config=self.original_config, last_exit_status=None, recorded=[])
        steps = [self.authorized() if before is None else before, self.route(),
            self.not_found() if denied is None else denied,
            self.authorized() if after is None else after, self.route() if after_route is None else after_route]
        def call(*arguments, **kwargs):
            ordinal = len(client.recorded)
            client.recorded.append((client.config, arguments, kwargs))
            self.assertLess(ordinal, 5)
            self.assertEqual(client.config, self.spoof_config if ordinal == 2 else self.original_config)
            self.assertEqual(arguments, ("route", "get") if ordinal in (1, 4)
                else ("deployment", "get", self.pin["route"]))
            self.assertEqual(kwargs, {"codes": (4, 6)} if ordinal == 2 else {})
            if ordinal == failure_stage:
                raise failure
            client.last_exit_status = exit_status if ordinal == 2 else 0
            return steps[ordinal]
        client.call = Mock(side_effect=call)
        return client

    def invoke(self, client):
        from tools.java_server_tenants import operator_token_denial
        return operator_token_denial(client, self.deployment, self.pin, self.spoof_config)

    def test_both_closed_denials_require_the_same_authorized_record_and_actual_route_pin(self):
        for code, denied in ((6, self.not_found()), (4, self.permission_denied())):
            with self.subTest(code=code):
                client = self.client(denied=denied, exit_status=code)
                observed = self.invoke(client)
                self.assertEqual(len(client.recorded), 5)
                self.assertEqual(client.config, self.original_config)
                self.assertEqual(observed["case"], "operator-token-cannot-select-other-tenant")
                self.assertEqual(observed["status"], "denied")
                self.assertEqual(observed["expectedPin"], self.pin)
                self.assertEqual(observed["authorizedBefore"], observed["authorizedAfter"])
                self.assertEqual(observed["authorizedBefore"]["lookup"], self.authorized())
                self.assertEqual(observed["authorizedBefore"]["executionPin"]["selected"], self.pin)
                self.assertEqual(observed["denial"], {"exitCode": code, "response": denied})

    def test_unknown_success_uncertain_malformed_and_metadata_revealing_denials_reject(self):
        import copy
        from tools.java_server_tenants import require_operator_token_denial
        cases = [(self.not_found(), value) for value in (0, 4, 5, True, None)]
        changes = [("schemaVersion", "future"), ("command", "deployment list"), ("category", "success"),
            ("category", "future"), ("outcomeKnown", False), ("outcomeKnown", 1),
            ("requestDispatched", False), ("requestDispatched", 1), ("extra", "private"), ("data", None),
            ("error", {"code": "not-found"})]
        for key, value in changes:
            changed = self.not_found(); changed[key] = value; cases.append((changed, 6))
        for key in ("deployment", "durability", "routeGeneration", "stateVersion", "metadata"):
            changed = self.not_found(); changed["data"][key] = "foreign-private"; cases.append((changed, 6))
        for key in self.not_found():
            changed = self.not_found(); del changed[key]; cases.append((changed, 6))
        for key, value in (("code", "unauthenticated"), ("code", "permission-denied-private"),
                ("message", "foreign-private"), ("retryable", True), ("retryable", 0),
                ("details", [{"metadata": "foreign-private"}]), ("extra", "foreign-private")):
            changed = self.permission_denied(); changed["error"][key] = value; cases.append((changed, 4))
        changed = self.permission_denied(); changed["data"]["deployment"] = self.authorized()["data"]["deployment"]
        cases.extend(((changed, 4), (self.permission_denied(), 6), (self.authorized(), 0), (None, 6), ([], 6)))
        for ordinal, (value, code) in enumerate(cases):
            with self.subTest(ordinal=ordinal), self.assertRaises(ValueError):
                require_operator_token_denial(copy.deepcopy(value), code)

    def test_authorized_lookup_must_prove_the_expected_foreign_object_before_spoofing(self):
        import copy
        cases = [self.not_found()]
        for target, key, value in (("record", "generation", "3"), ("publication", "tenant", "examples"),
                ("publication", "id", "publication:sha256:" + "e" * 64), ("metadata", "tenant", "examples"),
                ("metadata", "name", "another"), ("spec", "service", "another"),
                ("spec", "release", "sha256:" + "e" * 64), ("spec", "publication", "publication:sha256:" + "e" * 64)):
            changed = self.authorized(); record = changed["data"]["deployment"]
            selected = {"record": record, "publication": record["publication"],
                "metadata": record["manifest"]["metadata"], "spec": record["manifest"]["spec"]}[target]
            selected[key] = value; cases.append(changed)
        for ordinal, before in enumerate(cases):
            client = self.client(before=copy.deepcopy(before))
            with self.subTest(ordinal=ordinal), self.assertRaises(ValueError):
                self.invoke(client)
            self.assertEqual(len(client.recorded), 1)
            self.assertEqual(client.config, self.original_config)

    def test_authorized_envelopes_and_records_are_not_assumed_from_a_success_label(self):
        changes = [("outcomeKnown", 1), ("requestDispatched", False), ("category", "future"),
            ("error", {}), ("data", None), ("extra", "unknown")]
        for key, value in changes:
            before = self.authorized(); before[key] = value
            client = self.client(before=before)
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.invoke(client)
            self.assertEqual(len(client.recorded), 1)
        for value in (None, [], {}, {"manifest": []}):
            before = self.authorized(); before["data"]["deployment"] = value
            with self.subTest(record=value), self.assertRaises(ValueError):
                self.invoke(self.client(before=before))

    def test_after_lookup_preserves_the_full_record_and_catalog_identity(self):
        after = self.authorized()
        after["data"]["deployment"]["manifest"]["metadata"]["annotations"] = {"changed": "true"}
        route = self.route(); route["data"]["snapshot"]["generation"] = "8"
        digest = self.route(); digest["data"]["snapshot"]["snapshotDigest"] = "sha256:" + "e" * 64
        revision = self.route(); revision["data"]["snapshot"]["services"][0]["revisions"][0]["revisionId"] = "revision-v1:sha256:" + "e" * 64
        for arguments in ({"after": after}, {"after": self.not_found()}, {"after_route": route},
                          {"after_route": digest}, {"after_route": revision}):
            client = self.client(**arguments)
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                self.invoke(client)
            self.assertEqual(client.config, self.original_config)

    def test_denial_validation_and_call_failures_always_restore_original_config(self):
        bad = self.not_found(); bad["data"]["deployment"] = {"metadata": "foreign-private"}
        client = self.client(denied=bad)
        with self.assertRaises(ValueError):
            self.invoke(client)
        self.assertEqual(client.config, self.original_config)
        self.assertEqual(len(client.recorded), 3)
        for ordinal in (2, 3):
            original = RuntimeError("original bounded control failure")
            client = self.client(failure_stage=ordinal, failure=original)
            with self.subTest(stage=ordinal), self.assertRaises(RuntimeError) as observed:
                self.invoke(client)
            self.assertIs(observed.exception, original)
            self.assertEqual(client.config, self.original_config)
            self.assertEqual(len(client.recorded), ordinal + 1)

    def test_changed_selected_object_is_rejected_before_any_cli_call(self):
        from unittest.mock import Mock
        for key in ("name", "service", "generation", "publication"):
            original = self.deployment[key]; self.deployment[key] = "changed"
            client = SimpleNamespace(call=Mock())
            try:
                with self.subTest(key=key), self.assertRaises(ValueError):
                    self.invoke(client)
                client.call.assert_not_called()
            finally:
                self.deployment[key] = original


if __name__ == "__main__":
    unittest.main()
