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


if __name__ == "__main__":
    unittest.main()
