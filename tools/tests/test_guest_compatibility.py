"""Report trust boundaries and final-component inspection, without compiler claims."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import guest_compatibility as c
from tools import guest_compatibility_build as build
from tools.dev_workflow.common import DevError, digest, encode

DIGEST = "sha256:" + "1" * 64
PROFILE = "lsf-host-abi-phase3-v4"
HTTP = "latent:http/client@0.2.0"


def sample(findings=(), *, language="rust"):
    return c.report(language, DIGEST, DIGEST, PROFILE, [{"kind": "runtime", "digest": DIGEST}], findings)


def graph(imports=(HTTP,), exports=("examples:hello/service@1.0.0",)):
    result = {"worlds": [], "interfaces": [], "types": [], "packages": []}
    sides = {}
    for direction, names in (("imports", imports), ("exports", exports)):
        sides[direction] = {}
        for name in names:
            path, version = name.split("@")
            package, interface = path.split("/")
            index = len(result["interfaces"])
            result["interfaces"].append({"package": len(result["packages"]), "name": interface})
            result["packages"].append({"name": package + "@" + version})
            sides[direction][name] = {"interface": {"id": index}}
    result["worlds"] = [{"name": "service", "package": len(result["packages"]), **sides}]
    result["packages"].append({"name": "examples:hello@1.0.0"})
    return result


class CompatibilityReport(unittest.TestCase):
    def test_all_languages_share_classifications_without_package_eligibility(self):
        for language in c.LANGUAGES:
            report = sample([c.finding("missing-runtime-port", "invocation", "not-evaluated", owner_issue=741)], language=language)
            self.assertEqual(c.read(encode(report)), report)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["authority"], "none")

    def test_denial_resource_and_uncertainty_remain_distinct(self):
        classes = ("denied-grant", "resource-exhausted", "external-uncertain", "deadline", "cancelled", "unsupported-reached")
        report = sample([c.finding(name, "invocation", "actual-component") for name in classes])
        self.assertEqual([item["classification"] for item in report["findings"]], list(classes))
        self.assertEqual(c.read(encode(report)), report)

    def test_unknown_and_extension_are_not_success(self):
        for classification in ("unresolved-behavior", "optional-extension", "lifecycle-unproven"):
            self.assertEqual(sample([c.finding(classification, "invocation", "model")])["status"], "incomplete")

    def test_elimination_requires_compiler_source_identity(self):
        for evidence in ("model", "native-reference", "not-evaluated", "actual-component"):
            with self.assertRaises(DevError):
                c.finding("unsupported-eliminated", "compile", evidence, source_digest=DIGEST)
        with self.assertRaises(DevError):
            c.finding("unsupported-eliminated", "compile", "compiler")
        self.assertEqual(sample([c.finding("unsupported-eliminated", "compile", "compiler", source_digest=DIGEST)])["status"], "observed")

    def test_findings_bound_and_omissions_preserve_incompleteness(self):
        report = sample([c.finding("unsupported-eliminated", "compile", "compiler", source_digest=DIGEST)] * 70)
        self.assertEqual(len(report["findings"]), 64)
        self.assertEqual(report["omittedFindings"], 6)
        self.assertEqual(report["status"], "incomplete")

    def test_infinite_finding_input_is_rejected(self):
        with self.assertRaisesRegex(DevError, "input-limit"):
            sample(c.finding("unresolved-behavior", "compile", "model") for _ in range(4097))

    def test_identity_status_and_unknown_fields_cannot_be_forged(self):
        for key, value in (("sourceDigest", "sha256:" + "2" * 64), ("status", "passed"), ("authority", "granted"), ("hidden", True)):
            changed = {**sample(), key: value}
            with self.assertRaises(DevError):
                c.validate(changed)

    def test_reports_do_not_accept_private_source_or_exception_payloads(self):
        for text in ("https://user:secret@example.test/a?token=secret", "../secret", "C:/private/file", "a\nsecret", "Bearer secret"):
            with self.assertRaises(DevError):
                c.finding("target-incompatible", "compile", "compiler", location={"path": text, "line": 1, "column": 1})
        with self.assertRaises(DevError):
            c.validate_finding({"classification": "target-incompatible", "phase": "compile", "evidence": "compiler", "message": "secret"})

    def test_patch_requires_original_transformed_and_transform_identities(self):
        with self.assertRaises(DevError):
            c.report("rust", DIGEST, DIGEST, PROFILE, [{"kind": "patch", "digest": DIGEST}], [])
        report = c.report("rust", DIGEST, DIGEST, PROFILE,
            [{"kind": "patch", "digest": DIGEST, "originalDigest": DIGEST, "transformDigest": DIGEST}], [])
        self.assertEqual(c.read(encode(report)), report)

    def test_oversized_recursive_and_duplicate_json_fail_closed(self):
        for raw in (b"x" * (c.MAX_BYTES + 1), b'{"schemaVersion":1,"schemaVersion":2}', b"[" * 100 + b"0" + b"]" * 100):
            with self.assertRaises(DevError):
                c.read(raw)

    def test_http_grants_do_not_recognize_socket_imports(self):
        host = {"interfaces": [{"interface": HTTP}]}
        result = c.import_findings(["wasi:sockets/tcp@0.2.0"], ["wasi:sockets/tcp@0.2.0"], host,
                                  installed={HTTP}, granted={HTTP})
        self.assertEqual([item["classification"] for item in result], ["unknown-import"])

    def test_import_recognition_provider_installation_and_grant_are_separate(self):
        host = {"interfaces": [{"interface": HTTP}]}
        for installed, granted, expected in ((set(), set(), "missing-provider"), ({HTTP}, set(), "missing-grant"),
                                             (None, None, "unresolved-behavior")):
            self.assertEqual(c.import_findings([HTTP], [HTTP], host, installed=installed, granted=granted)[0]["classification"], expected)


class FinalComponentInspection(unittest.TestCase):
    def test_actual_java_type_interface_is_structural_without_installing_or_granting_a_provider(self):
        raw = (Path(__file__).parent / "fixtures/java-type-imports/final-wit-102f61b1.json").read_bytes()
        self.assertEqual(digest(raw), "sha256:fa52df37a921a12fcfed9fc1fb499ee9848291daa01de04bdce572e0f7a0cf4d")
        original = json.loads(raw)
        host = json.loads((build.ROOT / "wit/host-abi-phase3-v4.json").read_bytes())
        known = {row["interface"] for row in host["interfaces"]}
        names = build.interface_names(original, host_interfaces=known)
        clocks = ["latent:clock/monotonic@0.1.0", "latent:clock/wall@0.1.0"]
        self.assertEqual(names, {"imports": clocks, "typeImports": ["examples:java-http-domain/types@1.0.0"],
                                "exports": ["examples:java-http-domain/api@1.0.0"]})
        findings = c.import_findings(names["imports"], clocks, host)
        self.assertEqual([item["classification"] for item in findings], ["unresolved-behavior"])
        self.assertEqual(sample(findings)["authority"], "none")
        self.assertEqual([item["classification"] for item in c.import_findings(names["imports"], clocks, host,
                         installed=set(), granted=set())], ["missing-provider", "missing-provider"])
        reexport = copy.deepcopy(original)
        reexport["worlds"][0]["exports"]["types"] = {"interface": {"id": 2}}
        self.assertIn("examples:java-http-domain/types@1.0.0", build.interface_names(reexport)["exports"])

    def test_type_named_callable_and_recognized_host_interfaces_do_not_bypass_host_checks(self):
        original = json.loads((Path(__file__).parent / "fixtures/java-type-imports/final-wit-102f61b1.json").read_bytes())
        changed = copy.deepcopy(original)
        changed["interfaces"][2]["functions"] = {"send": {"kind": "freestanding", "params": [], "result": None}}
        self.assertEqual(build.interface_names(changed)["typeImports"], [])
        changed = copy.deepcopy(original)
        known = {"examples:java-http-domain/types@1.0.0"}
        self.assertEqual(build.interface_names(changed, host_interfaces=known)["typeImports"], [])

    def test_resource_handle_and_async_aliases_cannot_be_classified_as_structural(self):
        original = json.loads((Path(__file__).parent / "fixtures/java-type-imports/final-wit-102f61b1.json").read_bytes())
        for kind in ("resource", {"handle": {"own": 1}}, {"handle": {"borrow": 1}},
                     {"future": "u64"}, {"stream": "u64"}, {"unknown": "u64"}):
            changed = copy.deepcopy(original)
            changed["types"][0]["kind"] = kind
            names = build.interface_names(changed)
            self.assertEqual(names["typeImports"], [])
            self.assertIn("examples:java-http-domain/types@1.0.0", names["imports"])

    def test_structural_alias_indices_cycles_and_deep_memoized_paths_fail_closed(self):
        original = json.loads((Path(__file__).parent / "fixtures/java-type-imports/final-wit-102f61b1.json").read_bytes())
        for index in (-1, True, 99999, 0):
            changed = copy.deepcopy(original)
            changed["types"][0]["kind"] = {"type": index}
            with self.assertRaises(DevError):
                build.interface_names(changed)
        changed = copy.deepcopy(original)
        changed["interfaces"][2]["types"] = {"shallow": 0, "deep": len(changed["types"]) + 32}
        for index in range(33):
            child = 0 if index == 0 else len(changed["types"]) - 1
            changed["types"].append({"kind": {"option": child}})
        with self.assertRaises(DevError):
            build.interface_names(changed)

    def test_structural_value_forms_and_shared_work_bound_remain_finite(self):
        original = json.loads((Path(__file__).parent / "fixtures/java-type-imports/final-wit-102f61b1.json").read_bytes())
        for kind in ({"tuple": {"types": ["u64", "string"]}}, {"result": {"ok": "u64", "err": None}},
                     {"variant": {"cases": [{"name": "empty", "type": None}, {"name": "full", "type": "u64"}]}},
                     {"enum": {"cases": [{"name": "on"}, {"name": "off"}]}},
                     {"flags": {"flags": [{"name": "read"}, {"name": "write"}]}}):
            changed = copy.deepcopy(original)
            changed["types"][0]["kind"] = kind
            self.assertEqual(build.interface_names(changed)["typeImports"], ["examples:java-http-domain/types@1.0.0"])
        changed = copy.deepcopy(original)
        base = len(changed["types"])
        for index in range(9):
            changed["types"].append({"kind": {"tuple": {"types": ["u64"] * 4096}}})
        changed["interfaces"][2]["types"] = {"bounded-" + str(index): base + index for index in range(9)}
        with self.assertRaises(DevError):
            build.interface_names(changed)

    def test_reporting_stale_input_preserves_original_build_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "source-inputs.json").write_bytes(b"captured source")
            (output / "compatibility-inspection.json").write_bytes(b"invalid json")
            build.failure_report(output, "rust", "compile")
            marker = json.loads((output / "compatibility-report-failed.json").read_bytes())
            self.assertEqual(marker["status"], "unavailable")
            self.assertEqual(marker["authority"], "none")

    def test_unwritable_failure_report_cannot_mask_compiler_exception(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "source-inputs.json").write_bytes(b"captured source")
            with patch.object(build, "write_json", side_effect=PermissionError("private path")):
                try:
                    raise ValueError("original-compiler-failure")
                except ValueError:
                    build.failure_report(output, "rust", "compile")
                    with self.assertRaisesRegex(ValueError, "original-compiler-failure"):
                        raise

    def test_final_graph_tables_and_indices_are_checked(self):
        self.assertEqual(build.interface_names(graph())["imports"], [HTTP])
        for changed in (graph(), graph()):
            changed["worlds"][0]["imports"][HTTP]["interface"]["id"] = -1
            with self.assertRaises(DevError):
                build.interface_names(changed)

    def test_unknown_world_items_and_ambiguous_worlds_are_not_guessed(self):
        changed = graph()
        changed["worlds"][0]["imports"][HTTP] = {"function": {}}
        with self.assertRaises(DevError):
            build.interface_names(changed)
        changed = graph()
        changed["worlds"] *= 2
        with self.assertRaises(DevError):
            build.interface_names(changed)

    def test_surface_mismatch_fails_before_packaging_and_retains_inspection(self):
        class Commands:
            def run(self, *args):
                return encode(graph(imports=("unknown:capability/client@1.0.0",)))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "component.wasm").write_bytes(b"component")
            with self.assertRaisesRegex(ValueError, "compatibility-failed"):
                build.inspect(Commands(), Path("wasm-tools"), output, {"imports": [HTTP], "exports": ["examples:hello/service@1.0.0"]})
            retained = json.loads((output / "compatibility-inspection.json").read_bytes())
            self.assertIn("unknown-import", [item["classification"] for item in retained["findings"]])

    def test_unknown_native_outcome_is_never_presented_as_guest_execution(self):
        report = sample([c.finding("unsupported-reached", "invocation", "native-reference")])
        self.assertIn("native-reference", c.present(report))
        self.assertNotIn("actual-component", c.present(report))

    def test_catalogue_absence_and_renaming_do_not_change_import_classification(self):
        host = {"interfaces": [{"interface": HTTP}]}
        first = c.import_findings([HTTP], [HTTP], host)
        second = c.import_findings([HTTP], [HTTP], copy.deepcopy(host))
        self.assertEqual(first, second)


class SharedPackageAssembly(unittest.TestCase):
    def test_all_six_builders_execute_shared_package_assembly_with_final_inspection(self):
        import importlib
        from tools import rust_capsule_build as shared

        class InspectedCommands:
            def run(self, *args):
                return encode(graph(imports=()))

        builders = {"rust": "tools.rust_capsule_build", "c": "tools.c_capsule_build",
                    "java": "tools.java_capsule_build", "dotnet": "tools.dotnet_guest.build",
                    "go": "tools.go_capsule_build", "typescript": "tools.typescript_guest.build"}
        for language, module_name in builders.items():
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                module = importlib.import_module(module_name)
                self.assertIs(module.package_inputs, shared.package_inputs)
                self.assertTrue(set(build.RECIPE) <= set(module.RECIPE))
                output = Path(directory)
                component = b"controlled component bytes; wasm-tools boundary is mocked"
                source = b"captured source inventory"
                (output / "component.wasm").write_bytes(component)
                (output / "source-inputs.json").write_bytes(source)
                surface = {"imports": [], "exports": ["examples:hello/service@1.0.0"]}
                inspected = build.inspect(InspectedCommands(), Path("wasm-tools"), output, surface)
                files = {"sdk-lock.json": encode({"language": language}),
                         "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n',
                         "wit/application.wit": b"package examples:hello@1.0.0; interface service {}"}
                project = {"name": "package-fixture", "tenant": "examples", "service": "examples/package-fixture",
                           "world": "examples:hello/service@1.0.0", "version": "1.0.0", "limits": {}}
                module.package_inputs(output, project, surface, files, component)
                package = json.loads((output / "package-source.json").read_bytes())
                layers = {item["path"]: item for item in package["layers"]}
                self.assertEqual(layers["compatibility-report.json"]["role"], "asset")
                self.assertEqual(layers["component.wasm"]["role"], "component")
                self.assertEqual(layers["capsule.json"]["role"], "capsule-manifest")
                self.assertEqual(layers["contracts.json"]["role"], "contracts")
                self.assertEqual(layers["wit-lock.json"]["role"], "wit-lock")
                self.assertEqual((output / "wit/application.wit").read_bytes(), files["wit/application.wit"])
                report = c.validate(json.loads((output / "compatibility-report.json").read_bytes()))
                self.assertEqual(report["language"], language)
                self.assertEqual(report["componentDigest"], inspected["componentDigest"])
                self.assertEqual(report["sourceDigest"], digest(source))
                self.assertIn("lifecycle-unproven", [row["classification"] for row in report["findings"]])
                deployment = json.loads((output / "deployment.json").read_bytes())
                self.assertEqual(deployment["spec"]["grants"], [])

    def test_changed_component_after_inspection_cannot_produce_package_source(self):
        from tools.rust_capsule_build import package_inputs

        class InspectedCommands:
            def run(self, *args):
                return encode(graph(imports=()))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            component = b"component inspected before changed bytes"
            (output / "component.wasm").write_bytes(component)
            surface = {"imports": [], "exports": ["examples:hello/service@1.0.0"]}
            build.inspect(InspectedCommands(), Path("wasm-tools"), output, surface)
            files = {"sdk-lock.json": encode({"language": "rust"}),
                     "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n'}
            project = {"name": "package-fixture", "tenant": "examples", "service": "examples/package-fixture",
                       "world": "examples:hello/service@1.0.0", "version": "1.0.0", "limits": {}}
            with self.assertRaisesRegex(DevError, "stale-inspection"):
                package_inputs(output, project, surface, files, b"changed component bytes")
            self.assertFalse((output / "package-source.json").exists())
            self.assertFalse((output / "BUILD-COMPLETE.json").exists())


if __name__ == "__main__":
    unittest.main()
