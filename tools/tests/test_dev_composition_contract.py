import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from jsonschema import Draft202012Validator, ValidationError
from referencing import Registry, Resource

from tools.dev_workflow import composition_contract as contract
from tools.dev_workflow.common import DevError, decode, encode


SHA = "sha256:" + "a" * 64
OTHER_SHA = "sha256:" + "b" * 64
BUDGET_FIELDS = ("cpuFuel", "memoryBytes", "wallTimeLimitMillis", "childCalls", "outboundRequests",
                 "stateReadBytes", "stateWriteBytes", "blobReadBytes", "blobWriteBytes", "logBytes", "effectCount")


def composition():
    component = {"id": "domain", "packageDigest": SHA, "componentDigest": SHA, "releaseDigest": SHA,
        "contractMetadataDigest": SHA, "language": "java", "witShape": "nested-values-v1", "publicationKind": "capsule",
        "target": {"service": "examples/domain", "route": "domain", "revision": "revision-v1:" + SHA,
            "publicationId": "publication:" + SHA, "deploymentId": "domain", "deploymentGeneration": "1", "contract": "examples:domain/api@1.0.0", "function": "run"},
        "imports": [], "exports": [{"contract": "examples:domain/api@1.0.0", "functions": ["run"]}],
        "budget": {name: None if name == "wallTimeLimitMillis" else "0" for name in BUDGET_FIELDS}}
    return {"schemaVersion": "latent.composition.v1", "tenant": "examples",
        "nodeProfile": {"id": "http-java-v1", "javaGuest": True, "maximumWirePayloadBytes": "2097152",
            "maximumRequestBodyBytes": "65536", "maximumResponseBodyBytes": "65536"},
        "components": [component], "triggers": [], "serviceEdges": [], "providers": [], "policies": []}


def static_composition():
    value = composition()
    component = value["components"][0]
    component.update(id="site", language="static", witShape="static-assets-v1", publicationKind="static-site", assetsDigest=SHA, webManifestDigest=SHA)
    for field in ("releaseDigest", "componentDigest", "contractMetadataDigest", "budget"):
        del component[field]
    component["target"] = {"publicationId": "publication:" + SHA, "webGeneration": "1"}
    component["exports"] = []
    value["triggers"] = [{"kind": "static", "component": "site"}]
    return value


def provider():
    return {"contract": "latent:clock/wall@0.1.0", "providerProfile": "activation-wall-v1",
        "configurationDigest": SHA, "configurationEpoch": "18446744073709551615",
        "bindingId": "clock-installed", "bindingDigest": SHA, "policyIds": ["runtime-allow"]}


def capture_fixture(schema, document=None):
    document = document or schema
    if "$ref" in schema:
        return capture_fixture(document["$defs"][schema["$ref"][8:]], document)
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]
    kind = schema["type"]
    if kind == "object":
        return {name: capture_fixture(schema["properties"][name], document) for name in schema["required"]}
    if kind == "array":
        return [capture_fixture(schema["items"], document) for _ in range(schema.get("minItems", 0))]
    if kind == "integer":
        return schema.get("minimum", 0)
    if kind == "string":
        if schema.get("pattern", "").startswith("^sha256:"):
            return SHA
        if schema.get("pattern", "").startswith("^/"):
            return "/index.html"
        return "sample"
    raise AssertionError("unexpected capture fixture schema kind")


class DevCompositionContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = contract.input_schema()
        cls.capture_schema = json.loads((contract.ROOT / contract.CAPTURE_SCHEMA_PATH).read_bytes())
        registry = Registry().with_resources([
            (cls.schema["$id"], Resource.from_contents(cls.schema)),
            (cls.capture_schema["$id"], Resource.from_contents(cls.capture_schema)),
        ])
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema, registry=registry)
        cls.capture_validator = Draft202012Validator(cls.capture_schema)

    def valid(self, value):
        self.validator.validate(value)
        self.assertIs(contract.validate_semantics(value), value)

    def rejected(self, value, code):
        with self.assertRaisesRegex(DevError, "^" + code + "$"):
            contract.validate_semantics(value)

    def test_closed_schema_static_variants_and_real_hash_encodings(self):
        value = composition()
        value["components"][0]["engineConfigurationDigest"] = "blake3:" + "f" * 64
        self.valid(value)
        self.valid(static_composition())
        bad = copy.deepcopy(value)
        bad["components"][0]["engineConfigurationDigest"] = SHA
        with self.assertRaises(ValidationError):
            self.validator.validate(bad)
        for field, datum in (("componentDigest", SHA), ("budget", value["components"][0]["budget"]),
                             ("metadataPath", "metadata/wit.json"), ("engineConfigurationDigest", "blake3:" + "f" * 64)):
            with self.subTest(static_field=field):
                bad = static_composition()
                bad["components"][0][field] = datum
                with self.assertRaises(ValidationError):
                    self.validator.validate(bad)
        for mutate in (
            lambda row: row.update(trafficEnabled=True),
            lambda row: row["components"][0].update(publicationKind="web-application"),
            lambda row: row["components"][0]["target"].update(publicationId=SHA),
            lambda row: row["components"][0]["target"].update(revision="latest"),
            lambda row: row["components"][0]["target"].update(deploymentGeneration="0"),
            lambda row: row["components"][0]["target"].pop("deploymentGeneration"),
            lambda row: row["nodeProfile"].update(javaGuest=None),
        ):
            bad = composition()
            mutate(bad)
            with self.assertRaises(ValidationError):
                self.validator.validate(bad)
        bad = static_composition()
        bad["triggers"][0].update(contract="latent:web/application@0.1.0", function="handle")
        with self.assertRaises(ValidationError):
            self.validator.validate(bad)
        for field in ("service", "route", "revision", "deploymentId", "contract", "function"):
            bad = static_composition()
            bad["components"][0]["target"][field] = value["components"][0]["target"][field]
            with self.assertRaises(ValidationError):
                self.validator.validate(bad)
        bad = static_composition()
        bad["components"][0].update(manifestPath="metadata/web-release.json", manifestDigest=OTHER_SHA)
        self.validator.validate(bad)
        self.rejected(bad, "preflight-static-manifest-identity-required")
        bad["components"][0]["manifestDigest"] = SHA
        self.valid(bad)
        bad["components"][0]["target"]["webGeneration"] = "0"
        with self.assertRaises(ValidationError):
            self.validator.validate(bad)

    def test_exact_u64_paths_byte_and_collection_bounds(self):
        value = composition()
        value["components"][0]["budget"]["cpuFuel"] = str((1 << 64) - 1)
        self.valid(value)
        value["components"][0]["budget"]["cpuFuel"] = str(1 << 64)
        self.validator.validate(value)
        self.rejected(value, "preflight-u64-decimal-string-required")
        for field in ("childCalls", "outboundRequests", "effectCount"):
            bounded = composition()
            bounded["components"][0]["budget"][field] = str((1 << 32) - 1)
            self.valid(bounded)
            bounded["components"][0]["budget"][field] = str(1 << 32)
            self.validator.validate(bounded)
            self.rejected(bounded, "preflight-resource-counter-bound")
        for number in ("00", "-1", "1.0", "184467440737095516150", 1, True, None):
            bad = composition()
            bad["components"][0]["budget"]["cpuFuel"] = number
            with self.assertRaises(ValidationError):
                self.validator.validate(bad)
        for name in ("../component.wasm", "CON/file.wasm", "component.wasm.", "a//b", "a\\b", "x/" + "é" * 121):
            bad = composition()
            bad["components"][0]["componentPath"] = name
            self.validator.validate(bad)
            with self.assertRaises(DevError):
                contract.validate_semantics(bad)
        for names in (["a" * 65], ["réferer"], ["x-a"] * 65):
            bad = composition()
            bad["components"][0]["headerNames"] = names
            with self.assertRaises(ValidationError):
                self.validator.validate(bad)
        bad = composition()
        bad["components"] *= 9
        with self.assertRaises(ValidationError):
            self.validator.validate(bad)
        large = composition()
        large["components"][0]["language"] = "rust"
        large["components"][0]["exports"] = [{"contract": f"examples:large{i}/api@1.0.0",
            "functions": [f"call-{index:02d}-" + "x" * 56 for index in range(64)]} for i in range(32)]
        for index in range(2):
            next_component = copy.deepcopy(large["components"][0])
            next_component["id"] = "large-" + str(index)
            next_component["target"]["service"] = "examples/large-" + str(index)
            large["components"].append(next_component)
        self.validator.validate(large)
        self.assertGreater(len(encode(large)), 262144)
        self.rejected(large, "preflight-input-byte-limit")
        with self.assertRaisesRegex(DevError, "duplicate-field"):
            decode(b'{"schemaVersion":"latent.composition.v1","schemaVersion":"other"}')

    def test_ambiguous_identity_keys_and_missing_policy_references_reject(self):
        value = composition()
        value["policies"] = [{"id": "runtime-allow", "digest": SHA}]
        value["providers"] = [provider()]
        self.valid(value)
        vectors = []
        bad = copy.deepcopy(value)
        alternate = copy.deepcopy(bad["providers"][0])
        alternate["configurationDigest"] = OTHER_SHA
        bad["providers"].append(alternate)
        vectors.append((bad, "preflight-ambiguous-provider-binding"))
        bad = copy.deepcopy(value)
        bad["policies"].append({"id": "runtime-allow", "digest": OTHER_SHA})
        vectors.append((bad, "preflight-ambiguous-policy"))
        bad = copy.deepcopy(value)
        bad["providers"][0]["policyIds"] = ["missing"]
        vectors.append((bad, "preflight-provider-policy-selection"))
        bad = copy.deepcopy(value)
        alternate = copy.deepcopy(bad["components"][0])
        alternate["target"]["route"] = "other"
        bad["components"].append(alternate)
        vectors.append((bad, "preflight-ambiguous-component"))
        bad = copy.deepcopy(value)
        alternate = copy.deepcopy(bad["components"][0])
        alternate["id"] = "other"
        bad["components"].append(alternate)
        vectors.append((bad, "preflight-ambiguous-target"))
        bad = copy.deepcopy(value)
        edge = {"from": "domain", "to": None, "contract": "examples:domain/api@1.0.0", "function": "run",
                "declaredGrantDigest": SHA, "requestBudget": {"wallTimeLimitMillis": None}}
        bad["serviceEdges"] = [edge, {**edge, "requestBudget": {"cpuFuel": "1"}}]
        vectors.append((bad, "preflight-ambiguous-service-edge"))
        for bad, code in vectors:
            with self.subTest(code=code):
                self.validator.validate(bad)
                self.rejected(bad, code)
        bad = static_composition()
        bad["serviceEdges"] = [{"from": "site", "to": None, "contract": "examples:domain/api@1.0.0", "function": "run",
                               "declaredGrantDigest": SHA, "requestBudget": {}}]
        self.validator.validate(bad)
        self.rejected(bad, "preflight-static-service-edge")

    def test_support_matrix_keeps_other_languages_unknown_shapes_and_context_unqualified(self):
        value = composition()
        component, profile = value["components"][0], value["nodeProfile"]
        for name in ("http-java-v1", "standalone-java-v1"):
            profile["id"] = name
            result = contract.selection_support(component, profile)
            self.assertEqual(result["state"], "supported")
            self.assertFalse(result["executionQualified"])
        profile["javaGuest"] = False
        self.assertEqual(contract.selection_support(component, profile)["code"], "java-engine-profile-not-selected")
        profile["javaGuest"] = True
        for shape in ("resources", "futures", "streams"):
            component["witShape"] = shape
            self.assertEqual(contract.selection_support(component, profile)["state"], "unsupported")
        component["witShape"] = "unknown"
        self.assertEqual(contract.selection_support(component, profile)["state"], "untested")
        component["language"] = "rust"
        component["witShape"] = "resources"
        self.assertEqual(contract.selection_support(component, profile)["state"], "untested")
        component.update(language="java", witShape="nested-values-v1")
        component["imports"] = [contract.CONTEXT]
        component["exports"] = [{"contract": "latent:web/application@0.1.0", "functions": ["handle"]}]
        value["triggers"] = [{"kind": "http", "component": "domain", "contract": "latent:web/application@0.1.0", "function": "handle"}]
        self.assertEqual(contract.selection_support(component, profile)["code"], "ordinary-context-provider-not-installed")
        component["imports"] = []
        profile["id"] = "http-java-v1"
        self.assertEqual(contract.selection_support(component, profile)["state"], "supported")
        profile["id"] = "former-http-global-values-v1"
        self.assertEqual(contract.selection_support(component, profile)["code"], "former-profile-is-disposable-reproduction-only")

    def test_java_interface_alias_and_multiple_export_reasons_are_closed(self):
        value = composition()
        component, profile = value["components"][0], value["nodeProfile"]
        component["imports"] = ["latent:http/client@0.2.0", "latent:http/client@0.3.0"]
        self.validator.validate(value)
        self.assertEqual(contract.java_declaration_reason(component), "java-interface-alias-unsupported")
        component["imports"] = ["examples:domain/api@1.0.0"]
        self.assertEqual(contract.selection_support(component, profile)["code"], "java-interface-alias-unsupported")
        component["imports"] = []
        component["exports"].append({"contract": "examples:another/api@1.0.0", "functions": ["run"]})
        self.validator.validate(value)
        self.assertEqual(contract.selection_support(component, profile)["code"], "java-public-export-interface-unsupported")
        serialized = json.dumps(contract.selection_support(component, profile))
        self.assertNotIn("examples:another", serialized)

    def test_capture_schema_walker_matches_closed_vectors_without_new_budget_algorithm(self):
        budget = capture_fixture(self.capture_schema)
        self.capture_validator.validate(budget)
        self.assertIs(contract.validate_capture_budget(budget), budget)
        # Schema conformance is intentionally not a second calculation of headroom.
        budget["captureLimits"]["publicAssetCount"]["remaining"] = 17
        self.capture_validator.validate(budget)
        contract.validate_capture_budget(budget)
        value = static_composition()
        value["components"][0]["captureBudget"] = budget
        self.valid(value)
        for mutate in (
            lambda row: row.update(signingKey="synthetic-private-value"),
            lambda row: row["qualification"].update(browserQualified=True),
            lambda row: row.update(complete=1),
            lambda row: row.update(nodeCapacity="qualified"),
            lambda row: row["generatedInputs"].update(finalPackageBytesObserved=0),
            lambda row: row["selection"].update(sourceObservationDigest="blake3:" + "a" * 64),
            lambda row: row["largestAssets"].extend([row["largestAssets"][0]] * 5),
            lambda row: row["captureLimits"]["publicAssetCount"].update(actual=16777217),
        ):
            bad = copy.deepcopy(budget)
            mutate(bad)
            with self.assertRaises(ValidationError):
                self.capture_validator.validate(bad)
            with self.assertRaisesRegex(DevError, "^preflight-capture-budget-shape$"):
                contract.validate_capture_budget(bad)
        serialized = encode(contract.selection_support(value["components"][0], value["nodeProfile"]))
        self.assertNotIn(b"signingKey", serialized)
        self.assertFalse(json.loads(serialized)["executionQualified"])

    def test_matrix_binds_sources_and_missing_packaged_contract_fails_finitely(self):
        matrix = contract.support_matrix()
        self.assertEqual(matrix["axes"]["publicationKind"], ["capsule", "static-site"])
        self.assertFalse(matrix["cartesianSupportPromised"])
        self.assertFalse(matrix["executionAuthorized"])
        self.assertEqual(contract.changed_matrix_sources(), [])
        with tempfile.TemporaryDirectory() as directory:
            changed = contract.changed_matrix_sources(Path(directory))
            self.assertEqual(set(changed), set(matrix["sources"]))
        self.assertRegex(contract.matrix_identity(), r"^sha256:[0-9a-f]{64}$")
        for row in matrix["rows"]:
            self.assertTrue(row["sources"])
            self.assertLessEqual(set(row["sources"]), set(matrix["sources"]))
            self.assertFalse(row["executionQualified"])
        with self.assertRaisesRegex(DevError, "^preflight-support-contract-not-packaged$"):
            contract._document("contracts/dev/missing-contract.json")

    def test_zip_packaged_stdlib_helper_uses_exact_resources_without_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "helper.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("tools/__init__.py", b"")
                for name in ("tools/dev_workflow/__init__.py", "tools/dev_workflow/common.py",
                             "tools/dev_workflow/paths.py", "tools/dev_workflow/composition_contract.py"):
                    bundle.writestr(name, (contract.ROOT / name).read_bytes())
                for name in (contract.MATRIX_PATH, contract.SCHEMA_PATH, contract.CAPTURE_SCHEMA_PATH):
                    bundle.writestr("tools/dev_workflow/data/" + name, (contract.ROOT / name).read_bytes())
            captured = root / "capture.json"
            captured.write_bytes(encode(capture_fixture(self.capture_schema)))
            code = ("import json, pathlib, sys; sys.path.insert(0, sys.argv[1]); "
                "from tools.dev_workflow import composition_contract as c; "
                "assert not (c.ROOT / c.SCHEMA_PATH).exists(); "
                "c.validate_capture_budget(json.loads(pathlib.Path(sys.argv[2]).read_bytes())); "
                "print(json.dumps({'input':c.input_schema()['$id'],'matrix':c.support_matrix()['schemaVersion'],'identity':c.matrix_identity()}))")
            completed = subprocess.run([sys.executable, "-I", "-c", code, str(archive), str(captured)],
                cwd=root, check=True, timeout=20, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertLess(len(completed.stdout), 4096)
            result = json.loads(completed.stdout)
            self.assertEqual(result["input"], self.schema["$id"])
            self.assertEqual(result["matrix"], contract.MATRIX)
            self.assertEqual(result["identity"], contract.matrix_identity())


if __name__ == "__main__":
    unittest.main()
