"""Compiler-declaration and route-tool conformance; native model evidence only."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools import server_routes, server_source as source
from tools.dev_workflow.common import DevError, digest, encode
from tools.rust_capsule_project import inventory, read_json


def fixture():
    files = {"src/IndependentServer.java": b"// captured independent helper\nserver.createContext(\"/api/hey\", handler);\n"}
    selected = {"schemaVersion": source.PROFILE, "id": "lsf.java.httpserver.buffered.v1", "language": "java",
        "sourceApis": ["com.sun.net.httpserver.HttpServer.create", "com.sun.net.httpserver.HttpServer.createContext"],
        "compilerDigest": digest(b"pinned-compiler"), "adapter": {"kind": "automatic", "digest": digest(b"automatic-adapter")},
        "runtimeDigest": digest(b"captured-class-library"), "initialization": "fresh-original-entrypoint",
        "target": {"contract": source.WEB, "function": "handle", "profile": "buffered-v1"},
        "limits": {"endpoints": source.MAX_ENDPOINTS, "contexts": source.MAX_CONTEXTS, "requestBodyBytes": 65536,
                   "responseBodyBytes": 262144, "headers": 64, "headerBytes": 16384},
        "unsupported": ["HttpServer.setExecutor", "ServerSocket.accept"]}
    plan = {"initializer": "IndependentServer.main", "extraction": "compiler-ast", "endpoints": [
        {"id": "server", "bind": {"address": "wildcard", "port": 8080, "backlog": 0}, "contexts": [
            {"path": "/api/hey", "match": "literal-prefix", "handler": "IndependentServer.lambda$0",
             "source": {"path": "src/IndependentServer.java", "line": 2, "column": 1}}]}]}
    # This intentionally synthetic signature is used only for metadata tests.
    # Production calls inspect against the final component and authoritative WIT.
    declaration = source.emit(files, b"model-component", encode(selected), plan,
                              {"types": {}, "functions": {"handle": {"model": True}}})
    mounts = {"schemaVersion": source.CONFIGURATION, "profileDigest": declaration["profileDigest"], "mounts": [
        {"endpoint": "server", "name": "independent", "scheme": "http", "host": "app.example.invalid",
         "path": "/api", "pathMatch": "prefix", "methods": ["GET", "HEAD"], "dispatch": "guest"}]}
    pin = {"tenant": "examples", "service": "examples/server", "route": "server", "publication": "publication:" + digest(b"actual-package"),
           "revision": "revision-v1:" + digest(b"actual-revision"), "deploymentGeneration": "17",
           "componentDigest": declaration["componentDigest"]}
    return files, selected, plan, declaration, mounts, pin


def triggers(declaration, mounts, pin):
    return server_routes.plan(encode(declaration), encode(mounts), pin,
        source_digest=declaration["sourceDigest"], profile_digest=declaration["profileDigest"])


class CatalogModel:
    """A finite catalog model, never presented as authenticated node evidence."""
    def __init__(self):
        self.version = 17
        self.triggers = {}
        self.operations = {}
        self.mutations = []
        self.calls = []
        self.reject = False
        self.lose_reply = False
        self.crash = False
        self.forged = None

    def result(self, data, *, category="success", known=True):
        return {"schemaVersion": "latent.cli.result.v1", "outcomeKnown": known, "category": category, "data": copy.deepcopy(data)}

    def call(self, *arguments):
        self.calls.append(tuple(map(str, arguments)))
        command = arguments[1]
        if command == "get":
            trigger = self.triggers.get(arguments[2])
            return self.result({"stateVersion": str(self.version), "trigger": trigger},
                               category="success" if trigger else "not-found")
        if command == "operation":
            receipt = self.forged or self.operations.get(arguments[2])
            return self.result({"receipt": receipt, "disposition": "found" if receipt else "unknown"}, known=receipt is not None)
        self.mutations.append(command)
        if self.crash:
            raise OSError("model client lost before response")
        if self.reject:
            return self.result({}, category="platform-failure")
        values = {str(arguments[i]): str(arguments[i + 1]) for i in range(3, len(arguments), 2)}
        expected_generation = values["--expected-generation"]
        expected_state = values["--expected-state-version"]
        assert int(expected_state) == self.version
        if command == "apply":
            manifest = read_json(Path(arguments[2]))
            name = manifest["metadata"]["name"]
        else:
            name = arguments[2]
            manifest = self.triggers[name]["manifest"]
        actual = self.triggers[name]["generation"] if name in self.triggers else "0"
        assert expected_generation == actual
        self.version += 1
        target = manifest["spec"]["target"]
        receipt = {"operationId": values["--operation-id"], "tenant": manifest["metadata"]["tenant"], "triggerId": name,
            "action": "TRIGGER_OPERATION_ACTION_" + command.upper(), "expectedGeneration": expected_generation,
            "expectedStateVersion": expected_state, "objectGeneration": str(self.version) if command == "apply" else actual,
            "stateVersion": str(self.version), "receiptDigest": digest(encode(manifest)),
            "target": {"kind": "application", "publication": {"tenant": manifest["metadata"]["tenant"], "id": target["publication"]},
                       "deploymentId": target["route"], "deploymentGeneration": str(target["deploymentGeneration"]),
                       "revision": target["revision"]}}
        self.operations[values["--operation-id"]] = receipt
        if command == "apply":
            self.triggers[name] = {"manifest": manifest, "generation": str(self.version)}
        else:
            del self.triggers[name]
        return self.result({"receipt": receipt}, known=not self.lose_reply)


class ServerSource(unittest.TestCase):
    def setUp(self):
        self.files, self.profile, self.plan, self.declaration, self.mounts, self.pin = fixture()

    def test_bound_declaration_changes_for_source_component_profile_and_registration(self):
        value = source.validate(encode(self.declaration), component_digest=digest(b"model-component"),
                                source_digest=digest(inventory(self.files)), profile_digest=digest(encode(self.profile)))
        self.assertEqual(value["authority"], "none")
        for field in ("componentDigest", "sourceDigest", "profileDigest"):
            arguments = {"component_digest": value["componentDigest"], "source_digest": value["sourceDigest"], "profile_digest": value["profileDigest"]}
            arguments[{"componentDigest": "component_digest", "sourceDigest": "source_digest", "profileDigest": "profile_digest"}[field]] = digest(b"changed")
            with self.assertRaisesRegex(DevError, "stale"):
                source.validate(encode(value), **arguments)
        changed = copy.deepcopy(self.plan)
        changed["endpoints"][0]["bind"]["port"] = 9090
        second = source.emit(self.files, b"model-component", encode(self.profile), changed,
                             {"types": {}, "functions": {"handle": {"model": True}}})
        self.assertNotEqual(value["configurationDigest"], second["configurationDigest"])

    def test_final_signature_inspection_rejects_same_name_with_wrong_web_type(self):
        graph = read_json(Path(__file__).parent / "fixtures/server-source/web-graph.json")
        class Commands:
            def __init__(self, final):
                self.final, self.calls = final, []
            def run(self, stage, *arguments):
                self.calls.append((stage, tuple(map(str, arguments))))
                return encode(self.final if stage == "server-final-wit" else graph)
        commands = Commands(graph)
        exported = source.inspect(commands, Path("wasm-tools"), Path("component.wasm"), Path("captured-web-wit"))
        self.assertEqual(set(exported["functions"]), {"handle"})
        self.assertEqual(len(commands.calls), 2)
        for mutation in ("async", "parameter", "return"):
            final = copy.deepcopy(graph)
            application = next(row for row in final["interfaces"] if "handle" in row["functions"])
            if mutation == "async":
                application["functions"]["handle"]["kind"] = "freestanding"
            elif mutation == "parameter":
                application["functions"]["handle"]["params"][0]["type"] = "string"
            else:
                application["functions"]["handle"]["result"] = "string"
            with self.assertRaisesRegex(DevError, "final-web-signature"):
                source.inspect(Commands(final), Path("wasm-tools"), Path("component.wasm"), Path("captured-web-wit"))

    def test_tampering_or_extending_closed_declaration_is_rejected(self):
        for field, selected in (("authority", "public"), ("initializer", "Different.main"), ("componentDigest", digest(b"other"))):
            bad = copy.deepcopy(self.declaration)
            bad[field] = selected
            with self.assertRaises(DevError):
                source.validate(encode(bad))
        bad = {**self.declaration, "publication": self.pin["publication"]}
        with self.assertRaises(DevError):
            source.validate(encode(bad))

    def test_static_location_must_be_in_captured_inputs_without_executing_them(self):
        self.files["src/IndependentServer.java"] += b"throw new AssertionError(\"must never execute on compiler host\");\n"
        source.emit(self.files, b"model-component", encode(self.profile), self.plan,
                    {"types": {}, "functions": {"handle": {}}})
        for location in ({"path": "src/Missing.java", "line": 1, "column": 1},
                         {"path": "src/IndependentServer.java", "line": 999, "column": 1},
                         {"path": "../outside.java", "line": 1, "column": 1}):
            bad = copy.deepcopy(self.plan)
            bad["endpoints"][0]["contexts"][0]["source"] = location
            with self.assertRaises(DevError):
                source.endpoints(bad["endpoints"], self.files)

    def test_duplicate_and_dynamic_or_unbounded_registration_fail(self):
        bad = copy.deepcopy(self.plan["endpoints"])
        bad[0]["contexts"].append(copy.deepcopy(bad[0]["contexts"][0]))
        with self.assertRaisesRegex(DevError, "conflicting-registration"):
            source.endpoints(bad, self.files)
        for address, port in (("0.0.0.0", 8080), ("wildcard", 0), ("loopback", 65536)):
            bad = copy.deepcopy(self.plan["endpoints"])
            bad[0]["bind"].update(address=address, port=port)
            with self.assertRaises(DevError):
                source.endpoints(bad, self.files)
        bad = copy.deepcopy(self.plan)
        bad["extraction"] = "run-application-to-discover"
        with self.assertRaises(DevError):
            source.emit(self.files, b"model-component", encode(self.profile), bad, {"types": {}, "functions": {"handle": {}}})

    def test_optional_extension_cannot_claim_transparent_source_api(self):
        selected = copy.deepcopy(self.profile)
        selected["adapter"]["kind"] = "developer-extension"
        with self.assertRaisesRegex(DevError, "extension"):
            source.emit(self.files, b"model-component", encode(selected), self.plan, {"types": {}, "functions": {"handle": {}}})
        self.plan["extraction"] = "developer-extension"
        value = source.emit(self.files, b"model-component", encode(selected), self.plan, {"types": {}, "functions": {"handle": {}}})
        self.assertEqual(value["extraction"], "developer-extension")

    def test_literal_prefix_requires_explicit_enclosing_mount(self):
        source.mounts(encode(self.mounts), self.declaration)
        for route, matching in (("/api/hey", "prefix"), ("/api/hey", "exact"), ("/other", "prefix")):
            bad = copy.deepcopy(self.mounts)
            bad["mounts"][0].update(path=route, pathMatch=matching)
            with self.assertRaisesRegex(DevError, "non-equivalent"):
                source.mounts(encode(bad), self.declaration)
        self.mounts["mounts"][0]["path"] = "/"
        source.mounts(encode(self.mounts), self.declaration)

    def test_exact_and_segment_matching_only_allow_equivalent_direct_routes(self):
        self.declaration["endpoints"][0]["contexts"][0].update(path="/hey", match="exact")
        self.mounts["mounts"][0].update(path="/hey", pathMatch="exact", dispatch="direct")
        source.mounts(encode(self.mounts), self.declaration)
        self.mounts["mounts"][0].update(path="/", pathMatch="prefix")
        with self.assertRaisesRegex(DevError, "direct-route"):
            source.mounts(encode(self.mounts), self.declaration)
        self.declaration["endpoints"][0]["contexts"][0]["match"] = "segment-prefix"
        self.mounts["mounts"][0].update(path="/hey", pathMatch="prefix")
        source.mounts(encode(self.mounts), self.declaration)

    def test_encoded_ambiguous_reserved_query_and_alias_paths_are_rejected(self):
        for route in ("", "hey", "/a//b", "/a/../b", "/a/./b", "/hey%2Fchild", "/hey%252Fchild", "/hey?q=x", "/hey#x", "/_lsf", "/_lsf/assets", "/he\\y"):
            with self.subTest(route=route), self.assertRaises(DevError):
                source.path(route)
        for route in ("/hey", "/hey/", "/heyday", "/HEY", "/hey/child"):
            self.assertEqual(source.path(route), route)

    def test_explicit_methods_profile_and_host_validation_never_add_head(self):
        self.mounts["mounts"][0]["methods"] = ["GET"]
        manifests = triggers(self.declaration, self.mounts, self.pin)
        self.assertEqual([row["spec"]["configuration"]["method"] for row in manifests], ["GET"])
        for change in ({"methods": ["TRACE"]}, {"methods": ["GET", "GET"]}, {"host": "User@app.example.invalid"}, {"host": "*.example.invalid"}):
            bad = copy.deepcopy(self.mounts)
            bad["mounts"][0].update(change)
            with self.assertRaises(DevError):
                source.mounts(encode(bad), self.declaration)
        bad = copy.deepcopy(self.mounts)
        bad["profileDigest"] = digest(b"foreign-profile")
        with self.assertRaisesRegex(DevError, "profile-mismatch"):
            source.mounts(encode(bad), self.declaration)

    def test_mount_origin_is_already_canonical_and_finite(self):
        for host in ("App.example.invalid", "app.example.invalid.", "app..example.invalid", "-app.example.invalid",
                     "app-.example.invalid", "app.example.invalid:80", "app.example.invalid:99999",
                     "127.00.0.1", "127.0.0.1:080", "[::1]", "app.example.invalid/path"):
            with self.subTest(host=host), self.assertRaises(ValueError):
                source.authority(host, "http")
        for host in ("app.example.invalid", "app.example.invalid:8080", "127.0.0.1:8080"):
            self.assertEqual(source.authority(host, "http"), host)

    def test_publication_revision_and_generation_are_required_after_deployment(self):
        for key, value in (("publication", "build-placeholder"), ("revision", digest(b"wrong-form")),
                           ("deploymentGeneration", "0"), ("deploymentGeneration", "01"), ("deploymentGeneration", str(2**64))):
            bad = copy.deepcopy(self.pin)
            bad[key] = value
            with self.assertRaises(DevError):
                triggers(self.declaration, self.mounts, bad)
        manifests = triggers(self.declaration, self.mounts, self.pin)
        self.assertEqual(manifests[0]["spec"]["target"]["publication"], self.pin["publication"])
        self.assertEqual(manifests[0]["spec"]["target"]["revision"], self.pin["revision"])


class ServerRoutes(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.root.chmod(0o700)
        self.cli = CatalogModel()
        self.owner = {"tenant": "examples", "route": "server", "clientConfigDigest": digest(b"protected-client-profile")}
        self.routes = server_routes.Routes(self.root, self.cli, self.owner)
        _, _, _, declaration, mounts, pin = fixture()
        self.manifests = triggers(declaration, mounts, pin)

    def test_apply_redeploy_rollback_and_remove_use_catalog_generation_cas(self):
        first = self.routes.apply(self.manifests)
        self.assertEqual(first["routes"]["independent-get"]["generation"], "18")
        self.routes.apply(self.manifests)
        self.assertEqual(len(self.cli.mutations), 2)
        newer = copy.deepcopy(self.manifests)
        for row in newer:
            row["spec"]["target"]["revision"] = "revision-v1:" + digest(b"new-revision")
        self.routes.apply(newer)
        self.routes.rollback(["independent-get", "independent-head"])
        self.assertEqual(self.cli.triggers["independent-get"]["manifest"], self.manifests[0])
        self.routes.remove(["independent-get", "independent-head"])
        self.assertEqual(self.routes.read()["routes"], {})
        self.assertEqual(self.cli.triggers, {})

    def test_uncertain_apply_recovers_only_original_receipt_without_second_mutation(self):
        self.cli.lose_reply = True
        with self.assertRaises(DevError) as error:
            self.routes.apply(self.manifests)
        self.assertTrue(error.exception.uncertain)
        original = self.routes.read()["pending"]["id"]
        self.assertEqual(len(self.cli.mutations), 1)
        self.routes.recover()
        self.assertEqual(len(self.cli.mutations), 1)
        self.assertIn(("trigger", "operation", original), self.cli.calls)
        self.assertIsNone(self.routes.read()["pending"])

    def test_unknown_operation_keeps_pending_and_never_assumes_rollback(self):
        self.cli.crash = True
        with self.assertRaises(OSError):
            self.routes.apply(self.manifests)
        pending = copy.deepcopy(self.routes.read()["pending"])
        with self.assertRaises(DevError) as error:
            self.routes.recover()
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(self.routes.read()["pending"], pending)
        with self.assertRaises(DevError):
            self.routes.apply(self.manifests)
        self.assertEqual(len(self.cli.mutations), 1)

    def test_denied_redeployment_leaves_last_good_local_and_catalog_route(self):
        prior = self.routes.apply(self.manifests)
        self.cli.reject = True
        newer = copy.deepcopy(self.manifests)
        newer[0]["spec"]["target"]["publication"] = "publication:" + digest(b"not-authorized")
        with self.assertRaisesRegex(DevError, "last-good-retained"):
            self.routes.apply(newer)
        self.assertEqual(self.routes.read(), prior)
        self.assertEqual(self.cli.triggers["independent-get"]["manifest"], self.manifests[0])

    def test_unowned_or_changed_route_cannot_be_overwritten(self):
        self.routes.apply(self.manifests)
        self.cli.triggers["independent-head"]["generation"] = "999"
        count = len(self.cli.mutations)
        with self.assertRaisesRegex(DevError, "concurrent-change"):
            self.routes.apply(self.manifests)
        self.assertEqual(len(self.cli.mutations), count)
        with self.assertRaisesRegex(DevError, "owned-removal"):
            self.routes.remove(["foreign-get"])

    def test_forged_receipt_scope_pin_or_generation_retains_original_intent(self):
        self.cli.lose_reply = True
        with self.assertRaises(DevError):
            self.routes.apply(self.manifests)
        pending = copy.deepcopy(self.routes.read()["pending"])
        original = self.cli.operations[pending["id"]]
        for field, selected in (("tenant", "foreign"), ("operationId", "foreign-op"), ("expectedGeneration", "1"), ("objectGeneration", "19")):
            self.cli.forged = {**original, field: selected}
            with self.assertRaises(DevError):
                self.routes.recover()
            self.assertEqual(self.routes.read()["pending"], pending)
        self.cli.forged = copy.deepcopy(original)
        self.cli.forged["target"]["publication"]["id"] = "publication:" + digest(b"different-package")
        with self.assertRaisesRegex(DevError, "receipt-pin"):
            self.routes.recover()
        self.assertEqual(len(self.cli.mutations), 1)

    def test_different_authenticated_profile_cannot_adopt_owned_receipts(self):
        self.routes.apply(self.manifests)
        foreign = server_routes.Routes(self.root, self.cli, {**self.owner, "clientConfigDigest": digest(b"foreign-profile")})
        with self.assertRaisesRegex(DevError, "owner-mismatch"):
            foreign.read()

    def test_route_inspection_does_not_claim_reachability_or_execution_permission(self):
        self.routes.apply(self.manifests)
        inspection = self.routes.inspect()
        self.assertFalse(inspection["atomicMultiRoutePublication"])
        self.assertFalse(inspection["executionPermission"])
        self.assertTrue(all(row["reachability"] == "not-observed" for row in inspection["routes"]))
        self.assertTrue(all(row["published"] is not None for row in inspection["routes"]))


if __name__ == "__main__":
    unittest.main()
