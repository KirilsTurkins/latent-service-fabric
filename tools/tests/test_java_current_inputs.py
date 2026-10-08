"""Current compiler-material oracle tests; synthetic bytes establish no compilation."""
import copy
import json
import unittest
from dataclasses import replace

from tools.java_transaction_qualification import current_inputs as current
from tools.java_transaction_qualification.inputs import digest, WORLD
from tools.rust_capsule_project import inventory


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def fixture():
    project = {"transaction-binding.json": b"exact-companion", "transaction-profile.json": encoded({"hostAbiDigest": "sha256:" + "a" * 64})}
    component = b"\0asm\x0d\0\x01\0" + b"synthetic-test-input"
    files = {"project/" + name: raw for name, raw in project.items()}
    files.update({"component.wasm": component, "source-inputs.json": inventory(project), "source.tar.gz": b"original-archive",
                  "recipe-inputs.json": b"original-recipe", "compiler-inputs.json": b"original-tools"})
    report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": "java", "variant": "aggregate",
              "evidenceKind": "authored-component-compiler", "world": WORLD, "sourceRevision": "1" * 40,
              "status": "compiled", "compiled": True, "workingTreeChanged": False,
              "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
              "componentBytes": len(component), "componentDigest": digest(component),
              "sourceDigest": digest(files["source-inputs.json"]), "sourceArchiveDigest": digest(files["source.tar.gz"]),
              "recipeDigest": digest(files["recipe-inputs.json"]), "companionDigest": digest(project["transaction-binding.json"]),
              "hostAbiDigest": "sha256:" + "a" * 64, "actualImports": sorted(current.REQUIRED_IMPORTS),
              "details": {"commands": [{"stage": name, "exitCode": 0} for name in sorted(current.SUCCESS_STAGES)]}}
    files["report.json"] = encoded(report)
    selection = current.CurrentSelection("1" * 40, "aggregate", digest(files["report.json"]), digest(component), digest(files["compiler-inputs.json"]))
    return files, selection


class CurrentJavaInputs(unittest.TestCase):
    def test_independent_selected_report_and_source_materials_preserve_original_bytes(self):
        files, selected = fixture()
        before = copy.deepcopy(files)
        report = current.validate_materials(files, selected)
        self.assertEqual(report["sourceRevision"], selected.source_commit)
        self.assertFalse(report["signedNodeExecutionQualified"])
        self.assertEqual(files, before)

    def test_changed_component_report_source_or_tool_closure_refuses(self):
        for name in ("component.wasm", "report.json", "source-inputs.json", "source.tar.gz", "recipe-inputs.json", "compiler-inputs.json", "project/transaction-binding.json"):
            files, selected = fixture()
            files[name] += b"changed"
            with self.subTest(material=name), self.assertRaises(ValueError):
                current.validate_materials(files, selected)
        files, selected = fixture()
        with self.assertRaises(ValueError):
            current.validate_materials(files, replace(selected, source_commit="2" * 40))

    def test_failed_missing_stages_and_claimed_signed_execution_refuse_even_with_reselected_report_digest(self):
        for change in ("failed-stage", "missing-stage", "signed-claim", "dirty-source", "foreign-language"):
            files, selected = fixture()
            report = json.loads(files["report.json"])
            if change == "failed-stage": report["details"]["commands"][0]["exitCode"] = 1
            elif change == "missing-stage": report["details"]["commands"].pop()
            elif change == "signed-claim": report["signedNodeExecutionQualified"] = True
            elif change == "dirty-source": report["workingTreeChanged"] = True
            else: report["language"] = "go"
            files["report.json"] = encoded(report)
            with self.subTest(change=change), self.assertRaises(ValueError):
                current.validate_materials(files, replace(selected, report_digest=digest(files["report.json"])))

    def test_declared_import_profile_and_selection_bounds_refuse(self):
        files, selected = fixture()
        for value in (replace(selected, source_commit="short"), replace(selected, variant="guessed"), replace(selected, component_digest="digest")):
            with self.subTest(selection=value), self.assertRaises(ValueError): current.validate_materials(files, value)
        report = json.loads(files["report.json"])
        report["actualImports"].append("latent:http/client@0.2.0")
        files["report.json"] = encoded(report)
        with self.assertRaises(ValueError): current.validate_materials(files, replace(selected, report_digest=digest(files["report.json"])))


if __name__ == "__main__":
    unittest.main()
