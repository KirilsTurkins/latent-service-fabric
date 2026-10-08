"""Original compiler observations and export availability are separate facts."""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.java_transaction_qualification import compiler_exports as exports
from tools.java_transaction_qualification import diagnostic_inputs
from tools.java_transaction_qualification.inputs import TOOL_PRODUCER_SOURCE, digest


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


class CompilerExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.root = self.base / "export"
        self.root.mkdir()
        self.source = "a" * 40
        self.identities = {}
        self.rows = []
        # Format fixtures exercise provenance refusal, not real compilation.
        for name, relative in exports.PATHS.items():
            files = {"compiled/component.wasm": b"\0asm\x0d\0\x01\0fixture",
                     "report.json": b"{}", "project/transaction-binding.json": b"{}",
                     "compiler-inputs.json": b"[]", "source-inputs.json": b"{}",
                     "source.tar.gz": b"original source archive", "recipe-inputs.json": b"{}"}
            if name != "forbidden-child":
                files["project/deferred-http-requirements.json"] = b"{}"
            for path, raw in files.items():
                p = self.root / relative / path
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(raw)
                self.rows.append({"path": relative + "/" + path, "bytes": len(raw),
                                  "digest": digest(raw).removeprefix("sha256:")})
            self.identities[name] = {"path": relative, "componentDigest": digest(files["compiled/component.wasm"]),
                "componentBytes": len(files["compiled/component.wasm"]),
                "companionDigest": digest(files["project/transaction-binding.json"]),
                "requirementsDigest": None if name == "forbidden-child" else digest(b"{}"),
                "compilerInputsDigest": digest(files["compiler-inputs.json"]),
                "sourceDigest": digest(files["source-inputs.json"]), "sourceArchiveDigest": digest(files["source.tar.gz"]),
                "recipeDigest": digest(files["recipe-inputs.json"]), "actualImports": []}
        self.process = {"schemaVersion": "latent.java.transaction-value-compiler-process.v1",
            "sourceCommit": self.source, "originalToolProducer": TOOL_PRODUCER_SOURCE,
            "compilerOnly": True, "compiled": True, "componentExportAvailable": False,
            "signedNodeExecutionQualified": False, "admissionRejectionQualified": False,
            "priorResultsReused": False, "publicToolsReadOnly": True,
            "originalPerVariantCompilerDeadlineSeconds": 900, "originalPerCommandOutputBytes": 4194304,
            "captures": self.identities}
        self.census = {"sourceCommit": self.source, "attempt": "fixture", "sourceVolumeReadOnly": True,
            "files": self.rows, "bytes": sum(row["bytes"] for row in self.rows),
            "compilerOnly": True, "signedExecutionQualified": False}
        self.seal = {"sourceCommit": self.source, "originalToolProducer": TOOL_PRODUCER_SOURCE,
            "compilerOnly": True, "componentExportAvailable": True, "signedNodeExecutionQualified": False,
            "admissionRejectionQualified": False, "captures": self.identities,
            "compilerOwnerState": {"Status": "exited", "Running": False, "Pid": 0, "ExitCode": 0, "OOMKilled": False}}

    def load(self):
        process, census = encoded(self.process), encoded(self.census)
        self.seal["compilerProcessReceiptDigest"] = digest(process).removeprefix("sha256:")
        self.seal["exportCensusDigest"] = digest(census).removeprefix("sha256:")
        seal = encoded(self.seal)
        paths = [self.base / name for name in ("process.json", "seal.json", "census.json")]
        for path, raw in zip(paths, (process, seal, census)):
            path.write_bytes(raw)
        return exports.load(self.root, paths[0], digest(process), paths[1], digest(seal), paths[2],
                            digest(census), self.source, "put-once-diagnostics")

    def test_original_pre_export_flag_and_raw_receipt_are_preserved(self):
        item = self.load()
        self.assertEqual(item.process, encoded(self.process))
        self.assertIs(json.loads(item.process)["componentExportAvailable"], False)
        self.assertIs(json.loads(item.seal)["componentExportAvailable"], True)
        self.assertIs(item.observation()["signedNodeExecutionQualified"], False)
        self.assertEqual(item.identity, self.identities["put-once-diagnostics"])

    def test_rewritten_process_export_claim_or_runtime_claim_is_refused(self):
        for field in ("componentExportAvailable", "signedNodeExecutionQualified", "admissionRejectionQualified"):
            with self.subTest(field=field):
                self.process[field] = True
                with self.assertRaisesRegex(ValueError, "original-pre-export"):
                    self.load()
                self.process[field] = False

    def test_live_compiler_cannot_supply_a_retired_export_seal(self):
        self.seal["compilerOwnerState"]["Pid"] = 1
        with self.assertRaisesRegex(ValueError, "physical-retirement"):
            self.load()

    def test_unlisted_file_and_outside_or_duplicate_census_paths_are_refused(self):
        extra = self.root / "capture/put-once-values/unlisted.txt"
        extra.write_bytes(b"unlisted")
        with self.assertRaisesRegex(ValueError, "unlisted-or-duplicate"):
            self.load()
        extra.unlink()
        original = self.rows[0]["path"]
        for path in ("../outside", self.rows[1]["path"]):
            with self.subTest(path=path):
                self.rows[0]["path"] = path
                with self.assertRaises(ValueError):
                    self.load()
        self.rows[0]["path"] = original

    def test_census_content_drift_and_single_link_ownership_are_refused(self):
        row = self.rows[0]
        path = self.root / row["path"]
        original = path.read_bytes()
        path.write_bytes(b"changed")
        with self.assertRaises(ValueError):
            self.load()
        path.write_bytes(original)
        link = self.base / "outside-hardlink"
        os.link(path, link)
        with self.assertRaisesRegex(ValueError, "single-link"):
            self.load()

    def test_empty_directory_depth_and_changed_component_size_are_refused(self):
        self.identities["put-once-diagnostics"]["componentBytes"] += 1
        with self.assertRaisesRegex(ValueError, "component-byte-identity"):
            self.load()
        self.identities["put-once-diagnostics"]["componentBytes"] -= 1
        parent = self.root
        for _ in range(33):
            parent /= "e"
        parent.mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "directory-count-and-depth-bound"):
            self.load()

    def test_export_selection_requires_paired_provenance_and_separate_candidate(self):
        self.load()
        values = {"diagnostic_export_root": self.root, "diagnostic_receipt": self.base / "process.json",
            "diagnostic_receipt_digest": digest(encoded(self.process)),
            "diagnostic_source_commit": self.source, "diagnostic_component_digest": digest(b"component"),
            "diagnostic_export_receipt": self.base / "seal.json",
            "diagnostic_export_receipt_digest": digest(encoded(self.seal)),
            "diagnostic_export_census": self.base / "census.json",
            "diagnostic_export_census_digest": digest(encoded(self.census))}
        selected = diagnostic_inputs.selection(SimpleNamespace(**values))
        self.assertEqual(selected["diagnostic_receipt_digest"], values["diagnostic_receipt_digest"])
        for field in values:
            with self.subTest(missing=field):
                incomplete = dict(values)
                incomplete[field] = None
                with self.assertRaisesRegex(ValueError, "complete-explicit"):
                    diagnostic_inputs.selection(SimpleNamespace(**incomplete))
        for extra, reason in (({"diagnostic_capture": self.base / "archive.tar.gz"}, "exclusive"),
                              ({"recovery_helper": self.base / "native-helper"}, "separate-bounded")):
            with self.subTest(extra=extra):
                with self.assertRaisesRegex(ValueError, reason):
                    diagnostic_inputs.selection(SimpleNamespace(**(values | extra)))
