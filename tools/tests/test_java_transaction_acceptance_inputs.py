"""Custody/refusal fixtures; these tests do not execute or compile a guest."""
import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest

from tools.java_transaction_qualification import acceptance_inputs as inputs
from tools.java_transaction_qualification.compiler_exports import ExportedCapture
from tools.java_transaction_qualification.inputs import WORLD, digest
from tools.rust_capsule_project import inventory


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def fixture(name):
    project = {"src/dev/latent/app/Capsule.java": b"synthetic custody-only source",
        "wit/world.wit": b"synthetic custody-only WIT", "transaction-binding.json": b"{}",
        "transaction-profile.json": encoded({"hostAbiDigest": "sha256:" + "b" * 64}),
        "capsule-project.json": b"{}"}
    if name == inputs.VALUE:
        text = "κλειδί / 値 / 🌍"
        declaration = {"schemaVersion": "latent.java.transaction-value-inputs.v1", "selectors": inputs.SELECTORS,
            "expectedUnsignedValues": inputs.UNSIGNED, "utf8Text": text,
            "utf8PayloadDigest": digest(json.dumps([None, text], ensure_ascii=False, separators=(",", ":")).encode()),
            "absentOptionalRequired": True, "freshInstanceRequired": True,
            "originalSourceDigest": "sha256:" + "a" * 64,
            "sourceDigest": digest(project["src/dev/latent/app/Capsule.java"]),
            "worldDigest": digest(project["wit/world.wit"]), "companionDigest": digest(project["transaction-binding.json"]),
            "componentCompiled": False, "signedStateExecutionQualified": False,
            "unsignedRoundtripQualified": False, "utf8RoundtripQualified": False, "absentOptionalQualified": False}
        project["transaction-value-inputs.json"] = encoded(declaration)
        project["deferred-http-requirements.json"] = b"{}"
    archive = io.BytesIO()
    with gzip.GzipFile(fileobj=archive, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as stream:
            for path, raw in project.items():
                member = tarfile.TarInfo(path)
                member.size = len(raw)
                stream.addfile(member, io.BytesIO(raw))
    files = {"project/" + path: raw for path, raw in project.items()}
    files.update({"compiled/component.wasm": b"\0asm\x0d\0\x01\0" + name.encode(),
        "source-inputs.json": inventory(project), "source.tar.gz": archive.getvalue(),
        "recipe-inputs.json": b"{}", "compiler-inputs.json": b"[]"})
    report = {"schemaVersion": "latent.transaction-guest.compiler.v1", "language": "java", "variant": name,
        "world": WORLD, "evidenceKind": "authored-component-compiler", "sourceRevision": "a" * 40,
        "status": "compiled", "compiled": True, "workingTreeChanged": False,
        "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
        "componentDigest": digest(files["compiled/component.wasm"]), "componentBytes": len(files["compiled/component.wasm"]),
        "sourceDigest": digest(files["source-inputs.json"]), "sourceArchiveDigest": digest(files["source.tar.gz"]),
        "recipeDigest": digest(files["recipe-inputs.json"]), "companionDigest": digest(project["transaction-binding.json"]),
        "hostAbiDigest": "sha256:" + "b" * 64,
        "actualImports": sorted(inputs.STATE | inputs.CLOCKS | ({inputs.CALL} if name == inputs.CHILD else set())),
        "details": {"bindings": {}, "tools": [], "commands": [{"stage": s, "exitCode": 0}
            for s in ["java-to-c", "c-to-wasm", "component-new", "component-validate", "compiled-wit"]]}}
    if name == inputs.VALUE:
        report["deferredHttpRequirementsDigest"] = digest(project["deferred-http-requirements.json"])
    files["report.json"] = encoded(report)
    identity = {key: report[key] for key in ["componentDigest", "componentBytes", "sourceDigest", "sourceArchiveDigest",
                                           "recipeDigest", "companionDigest"]}
    identity.update(compilerInputsDigest=digest(files["compiler-inputs.json"]),
                    requirementsDigest=report.get("deferredHttpRequirementsDigest"))
    selected = {"acceptance_source_commit": "a" * 40,
                "acceptance_value_component_digest": digest(b"\0asm\x0d\0\x01\0" + inputs.VALUE.encode()),
                "acceptance_child_component_digest": digest(b"\0asm\x0d\0\x01\0" + inputs.CHILD.encode())}
    return ExportedCapture(files, identity, b"original-process", b"original-seal", b"original-census"), selected


class AcceptanceInputTests(unittest.TestCase):
    def test_values_retain_unsigned_maximum_null_utf8_and_false_runtime_claims(self):
        exported, selected = fixture(inputs.VALUE)
        report, declaration = inputs.validate(exported, selected, inputs.VALUE)
        self.assertEqual(declaration["expectedUnsignedValues"]["unsignedMaximum"], "18446744073709551615")
        self.assertEqual(declaration["expectedUnsignedValues"]["highBit"], "9223372036854775808")
        self.assertIn("🌍", declaration["utf8Text"])
        self.assertIs(declaration["absentOptionalRequired"], True)
        self.assertIs(report["signedNodeExecutionQualified"], False)
        self.assertEqual(exported.process, b"original-process")

    def test_child_requires_actual_service_import_and_no_dispatch_requirements(self):
        exported, selected = fixture(inputs.CHILD)
        report, declaration = inputs.validate(exported, selected, inputs.CHILD)
        self.assertIsNone(declaration)
        self.assertIn(inputs.CALL, report["actualImports"])
        report["actualImports"].remove(inputs.CALL)
        exported.files["report.json"] = encoded(report)
        with self.assertRaisesRegex(ValueError, "closed-imports"):
            inputs.validate(exported, selected, inputs.CHILD)

    def test_changed_unsigned_selector_null_utf8_or_qualification_claim_refuses(self):
        exported, _selected = fixture(inputs.VALUE)
        project = {name[8:]: raw for name, raw in exported.files.items() if name.startswith("project/")}
        original = json.loads(project["transaction-value-inputs.json"])
        changes = [dict(expectedUnsignedValues={"highBit": "-9223372036854775808", "unsignedMaximum": "-1"}),
            dict(selectors={"highBit": "1", "unsignedMaximum": "2"}), dict(utf8PayloadDigest=digest(b"changed")),
            dict(absentOptionalRequired=False), dict(freshInstanceRequired=False), dict(componentCompiled=True),
            dict(signedStateExecutionQualified=True), dict(extraAuthority=True)]
        for changed in changes:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inputs.declaration(encoded(dict(original, **changed)), project)

    def test_component_source_archive_closure_and_original_source_drift_refuse(self):
        for path in ["compiled/component.wasm", "source.tar.gz", "source-inputs.json", "compiler-inputs.json",
                     "project/src/dev/latent/app/Capsule.java"]:
            exported, selected = fixture(inputs.VALUE)
            exported.files[path] += b"changed"
            with self.subTest(path=path), self.assertRaises(ValueError):
                inputs.validate(exported, selected, inputs.VALUE)

    def test_unsuccessful_compiler_or_invented_runtime_claim_refuses(self):
        for changed in [dict(signedNodeExecutionQualified=True), dict(workingTreeChanged=True),
                        dict(status="failed"), dict(sourceRevision="b" * 40)]:
            exported, selected = fixture(inputs.VALUE)
            report = json.loads(exported.files["report.json"])
            report.update(changed)
            exported.files["report.json"] = encoded(report)
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                inputs.validate(exported, selected, inputs.VALUE)
        exported, selected = fixture(inputs.VALUE)
        report = json.loads(exported.files["report.json"])
        report["details"]["commands"][0]["exitCode"] = 1
        exported.files["report.json"] = encoded(report)
        with self.assertRaisesRegex(ValueError, "compiler-stages"):
            inputs.validate(exported, selected, inputs.VALUE)

    def test_selection_requires_all_pins_and_a_separate_stopped_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            values = {name: root if name == "acceptance_export_root" else root / name
                      for name in inputs.PATH_ARGUMENTS}
            for name, path in values.items():
                if name != "acceptance_export_root":
                    path.write_bytes(b"original")
            values.update({name: "sha256:" + "a" * 64 for name in set(inputs.ARGUMENTS) - inputs.PATH_ARGUMENTS})
            values.update(acceptance_source_commit="a" * 40, acceptance_child_component_digest="sha256:" + "b" * 64,
                          value_child_acceptance_only=True, prepare_authority_only=True)
            selected = inputs.selection(SimpleNamespace(**values))
            self.assertEqual(selected["acceptance_source_commit"], "a" * 40)
            for changed in [dict(acceptance_process_receipt_digest=None), dict(value_child_acceptance_only=False),
                            dict(prepare_authority_only=False), dict(recovery_helper=root / "native"),
                            dict(pending_restore_only=True), dict(current_selections=root / "current"),
                            dict(reviewed_policy_environment=root / "old-ten-document-scope"),
                            dict(diagnostic_source_commit="b" * 40)]:
                with self.subTest(changed=changed), self.assertRaises(ValueError):
                    inputs.selection(SimpleNamespace(**dict(values, **changed)))
            self.assertIsNone(inputs.selection(SimpleNamespace()))
