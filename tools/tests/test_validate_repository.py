from __future__ import annotations

import importlib.util
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_repository.py"
SPEC = importlib.util.spec_from_file_location("validate_repository", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)

FOUNDATION_MODULE_PATH = Path(__file__).resolve().parents[1] / "validate_foundation.py"
FOUNDATION_SPEC = importlib.util.spec_from_file_location("validate_foundation", FOUNDATION_MODULE_PATH)
assert FOUNDATION_SPEC is not None and FOUNDATION_SPEC.loader is not None
foundation = importlib.util.module_from_spec(FOUNDATION_SPEC)
FOUNDATION_SPEC.loader.exec_module(foundation)


class SourceTraversalTests(unittest.TestCase):
    def setUp(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def tearDown(self) -> None:
        validator.ERRORS.clear()
        validator.WARNINGS.clear()

    def test_generated_directories_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source.json").write_text("{}", encoding="utf-8")
            for directory in validator.IGNORED_DIRECTORY_NAMES:
                generated = root / directory
                generated.mkdir(parents=True)
                (generated / "broken.json").write_text("{", encoding="utf-8")
            generated_paths = [
                root / "sdk/typescript-client/dist",
                root / "sdk/java-client/build",
                root / "sdk/dotnet/Latent.Sdk/bin",
                root / "sdk/dotnet/Latent.Sdk/obj",
            ]
            for generated in generated_paths:
                generated.mkdir(parents=True)
                (generated / "broken.json").write_text("{", encoding="utf-8")

            validator.validate_json(root)
            self.assertEqual(validator.ERRORS, [])
            self.assertEqual(
                {path.relative_to(root) for path in validator.iter_source_files(root)},
                {Path("source.json")},
            )

    def test_authoritative_source_remains_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "src/build"
            source.mkdir(parents=True)
            (source / "broken.json").write_text("{", encoding="utf-8")

            validator.validate_json(root)
            self.assertEqual(len(validator.ERRORS), 1)
            self.assertIn("src/build/broken.json", validator.ERRORS[0])

    def test_documentation_svg_requires_accessibility_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/valid.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title description\">
  <title id=\"title\">Valid diagram</title>
  <desc id=\"description\">A valid accessible SVG.</desc>
  <rect width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertEqual(validator.ERRORS, [])

    def test_documentation_svg_rejects_duplicate_title_and_shape_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/duplicate.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"shared description\">
  <title id=\"shared\">Duplicate ID diagram</title>
  <desc id=\"description\">The title and shape reuse one ID.</desc>
  <rect id=\"shared\" width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertEqual(
                validator.ERRORS,
                ["SVG contains duplicate ID shared: docs/assets/duplicate.svg"],
            )

    def test_documentation_svg_rejects_duplicate_definition_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/duplicate-defs.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title description\">
  <title id=\"title\">Duplicate definition IDs</title>
  <desc id=\"description\">Two definitions reuse one local ID.</desc>
  <defs>
    <linearGradient id=\"paint\"/>
    <clipPath id=\"paint\"/>
  </defs>
  <rect width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertEqual(
                validator.ERRORS,
                ["SVG contains duplicate ID paint: docs/assets/duplicate-defs.svg"],
            )

    def test_documentation_svg_allows_same_id_in_separate_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "docs/assets"
            assets.mkdir(parents=True)
            content = """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title description\">
  <title id=\"title\">Valid diagram</title>
  <desc id=\"description\">IDs are local to this document.</desc>
  <rect id=\"shape\" width=\"10\" height=\"10\"/>
</svg>"""
            (assets / "first.svg").write_text(content, encoding="utf-8")
            (assets / "second.svg").write_text(content, encoding="utf-8")

            validator.validate_svg(root)

            self.assertEqual(validator.ERRORS, [])

    def test_documentation_svg_rejects_active_or_incomplete_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/unsafe.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"presentation\" aria-labelledby=\"title missing\">
  <title id=\"title\">Unsafe diagram</title>
  <script>alert('no')</script>
  <use href=\"https://example.invalid/external.svg#shape\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertTrue(
                any("aria-labelledby references missing ID(s) missing" in error for error in validator.ERRORS)
            )
            self.assertTrue(any("role must be img" in error for error in validator.ERRORS))
            self.assertTrue(any("missing non-empty <desc>" in error for error in validator.ERRORS))
            self.assertTrue(any("disallowed <script>" in error for error in validator.ERRORS))
            self.assertTrue(any("non-local reference in href" in error for error in validator.ERRORS))

    def test_documentation_svg_labels_reference_its_title_and_description(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            asset = root / "docs/assets/mislabelled.svg"
            asset.parent.mkdir(parents=True)
            asset.write_text(
                """<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 10 10\" role=\"img\" aria-labelledby=\"title shape\">
  <title id=\"title\">Mislabelled diagram</title>
  <desc id=\"description\">Its description is not announced.</desc>
  <rect id=\"shape\" width=\"10\" height=\"10\"/>
</svg>""",
                encoding="utf-8",
            )

            validator.validate_svg(root)

            self.assertTrue(
                any(
                    "aria-labelledby must reference a non-empty <desc>" in error
                    for error in validator.ERRORS
                )
            )


class BenchmarkRetentionTests(unittest.TestCase):
    def test_budget_counts_combined_files_including_generated_directory_names(self) -> None:
        validator.ERRORS.clear()
        self.addCleanup(validator.ERRORS.clear)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "benchmarks/artifacts"
            evidence.mkdir(parents=True)
            (root / "benchmarks/report.md").write_bytes(b"report")
            (evidence / "payload.bin").write_bytes(b"1234")
            with patch.object(validator, "MAX_BENCHMARK_TREE_BYTES", 10):
                validator.validate_benchmark_retention(root)
                self.assertEqual(validator.ERRORS, [])
                (evidence / "payload.bin").write_bytes(b"12345")
                validator.validate_benchmark_retention(root)
                self.assertEqual(len(validator.ERRORS), 1)
                self.assertIn("retention budget (11 bytes)", validator.ERRORS[0])


class RetainedEmptyEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        validator.ERRORS.clear()
        self.addCleanup(validator.ERRORS.clear)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.package = self.root / "benchmarks/phase1/conformance/retained-ci"
        self.package.mkdir(parents=True)
        self.receipt = self.package / "run/cli.stderr"
        self.receipt.parent.mkdir()
        self.receipt.write_bytes(b"")
        self.manifest = self.package / "files.manifest.json"
        self.document = {"schema": "latent.phase1.retained-files.v1", "total_bytes": "0", "files": [
            {"path": "run/cli.stderr", "bytes": "0",
             "sha256": "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}]}
        self.write_manifest()

    def write_manifest(self) -> None:
        self.manifest.write_text(json.dumps(self.document), encoding="utf-8")

    def test_manifest_bound_empty_receipt_preserves_original_bytes(self) -> None:
        validator.validate_nonempty_files(self.root)
        self.assertEqual(validator.ERRORS, [])
        self.assertEqual(self.receipt.read_bytes(), b"")

    def test_unbound_empty_evidence_and_empty_source_remain_rejected(self) -> None:
        (self.package / "unbound.stdout").write_bytes(b"")
        (self.root / "empty.rs").write_bytes(b"")
        validator.validate_nonempty_files(self.root)
        self.assertEqual(len(validator.ERRORS), 2)
        self.assertTrue(all("empty file:" in error for error in validator.ERRORS))

    def test_wrong_hash_or_declared_size_does_not_exempt_empty_file(self) -> None:
        for change in ({"sha256": "sha256:" + "0" * 64}, {"bytes": "1"}):
            with self.subTest(change=change):
                validator.ERRORS.clear()
                row = self.document["files"][0]
                original = dict(row)
                row.update(change)
                self.write_manifest()
                validator.validate_nonempty_files(self.root)
                self.assertTrue(any("empty file:" in error for error in validator.ERRORS))
                row.clear()
                row.update(original)

    def test_nonempty_tampering_of_declared_empty_receipt_is_rejected(self) -> None:
        self.receipt.write_bytes(b"unexpected output")
        validator.validate_nonempty_files(self.root)
        self.assertTrue(any("changed empty receipt" in error for error in validator.ERRORS))

    def test_traversal_or_duplicate_reference_never_grants_exemption(self) -> None:
        for references in ([dict(self.document["files"][0], path="../run/cli.stderr")],
                           self.document["files"] * 2):
            with self.subTest(references=references):
                validator.ERRORS.clear()
                original = self.document["files"]
                self.document["files"] = references
                self.write_manifest()
                validator.validate_nonempty_files(self.root)
                self.assertTrue(any("invalid retained evidence manifest" in error for error in validator.ERRORS))
                self.assertTrue(any("empty file:" in error for error in validator.ERRORS))
                self.document["files"] = original

    def test_manifests_outside_conformance_cannot_exempt_source(self) -> None:
        self.manifest.unlink()
        (self.root / "files.manifest.json").write_text(json.dumps(self.document), encoding="utf-8")
        validator.validate_nonempty_files(self.root)
        self.assertTrue(any("empty file:" in error for error in validator.ERRORS))


class WorkspaceDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        foundation.ERRORS.clear()

    def tearDown(self) -> None:
        foundation.ERRORS.clear()

    def test_detects_path_dependency_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_workspace(root, cyclic=True)

            foundation.validate_workspace_dependency_graph(root)

            self.assertTrue(any("a -> b -> a" in error for error in foundation.ERRORS))

    def test_accepts_an_acyclic_path_dependency_graph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_workspace(root, cyclic=False)

            foundation.validate_workspace_dependency_graph(root)

            self.assertEqual(foundation.ERRORS, [])

    @staticmethod
    def _write_workspace(root: Path, *, cyclic: bool) -> None:
        (root / "Cargo.toml").write_text(
            '[workspace]\nresolver = "2"\nmembers = ["crates/a", "crates/b"]\n',
            encoding="utf-8",
        )
        for name in ("a", "b"):
            directory = root / "crates" / name
            directory.mkdir(parents=True)
            dependency = "b" if name == "a" else ("a" if cyclic else "")
            dependency_text = (
                f'\n[dependencies]\n{dependency} = {{ path = "../{dependency}" }}\n'
                if dependency
                else ""
            )
            (directory / "Cargo.toml").write_text(
                textwrap.dedent(
                    f"""
                    [package]
                    name = "{name}"
                    version = "0.1.0"
                    edition = "2021"
                    """
                ).lstrip()
                + dependency_text,
                encoding="utf-8",
            )


class GeneratedBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        foundation.ERRORS.clear()

    def tearDown(self) -> None:
        foundation.ERRORS.clear()

    def test_accepts_exhaustive_out_dir_generation_owners(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_foundation(root)

            foundation.validate_generated_contract_boundaries(root)

            self.assertEqual(foundation.ERRORS, [])

    def test_rejects_unlisted_proto_and_checked_in_generated_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_foundation(root)
            proto_root = root / "api/proto"
            (proto_root / "latent/extra.proto").write_text(
                'syntax = "proto3";\npackage latent.extra;\n', encoding="utf-8"
            )
            (proto_root / "generated.rs").write_text("// generated", encoding="utf-8")

            foundation.validate_generated_contract_boundaries(root)

            self.assertTrue(any("manifest drift" in error for error in foundation.ERRORS))
            self.assertTrue(
                any("generated language source" in error for error in foundation.ERRORS)
            )

    def test_rejects_wasmtime_build_script_binding_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_foundation(root)
            build_script = root / foundation.WASMTIME_TARGET_BUILD_SCRIPT
            build_script.write_text(
                'fn main() { let _ = std::env::var("TARGET"); '
                'wasmtime::component::bindgen!(); }',
                encoding="utf-8",
            )

            foundation.validate_generated_contract_boundaries(root)

            self.assertTrue(
                any(
                    "must not duplicate binding generation" in error
                    for error in foundation.ERRORS
                )
            )

    @staticmethod
    def _write_foundation(root: Path) -> None:
        proto_root = root / "api/proto"
        proto = proto_root / "latent/test.proto"
        proto.parent.mkdir(parents=True)
        proto.write_text('syntax = "proto3";\npackage latent.test;\n', encoding="utf-8")
        (proto_root / "latent-api.protos").write_text("latent/test.proto\n", encoding="utf-8")

        rpc = root / "crates/latent-rpc/build.rs"
        rpc.parent.mkdir(parents=True)
        rpc.write_text("OUT_DIR latent-api.protos", encoding="utf-8")
        component = root / "crates/latent-component-bindings/build.rs"
        component.parent.mkdir(parents=True)
        component.write_text(
            "OUT_DIR wit/platform/runtime examples/echo-contract/wit", encoding="utf-8"
        )
        wasmtime = root / foundation.WASMTIME_TARGET_BUILD_SCRIPT
        wasmtime.parent.mkdir(parents=True)
        wasmtime.write_text(
            'fn main() { let target = std::env::var("TARGET").unwrap(); '
            'println!("cargo:rustc-env=LATENT_WASMTIME_HOST_TARGET={target}"); }',
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
