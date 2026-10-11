"""Frozen profile selection controls; mocked WIT graphs are not guest execution."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_build as build
from tools.dev_workflow.common import DevError, digest, encode
from tools.tests.test_guest_compatibility import graph

V4 = "lsf-host-abi-phase3-v4"
V5 = "lsf-host-abi-phase3-v5"
RUNTIME = "latent:runtime/activation@0.1.0"
STREAMS = "latent:network/streams@0.1.0"
HTTP = "latent:http/streaming@0.3.0"
CLOCK = "latent:clock/monotonic@0.1.0"
EXPORT = "examples:hello/service@1.0.0"
COMPONENT = b"controlled component; emitted WIT graph is mocked"
FILES = {"sdk-lock.json": encode({"language": "dotnet"})}


class EmittedGraph:
    def __init__(self, imports):
        self.imports = imports
        self.calls = 0

    def run(self, *args):
        self.calls += 1
        return encode(graph(imports=self.imports))


def output(directory):
    path = Path(directory)
    (path / "component.wasm").write_bytes(COMPONENT)
    (path / "source-inputs.json").write_bytes(b"captured source inventory")
    return path


def inspect(path, actual=(RUNTIME, HTTP, CLOCK), *, declared=None, profile=V5):
    surface = {"imports": list(actual if declared is None else declared), "exports": [EXPORT]}
    return build.inspect(EmittedGraph(actual), Path("wasm-tools"), path, surface,
                         host_abi_profile=profile)


class FrozenHostProfiles(unittest.TestCase):
    def test_existing_v4_inspection_shape_and_manifest_identity_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            result = build.inspect(EmittedGraph((HTTP, CLOCK)), Path("wasm-tools"), path,
                                   {"imports": [HTTP, CLOCK], "exports": [EXPORT]})
            self.assertEqual(set(result), {"componentDigest", "hostAbiDigest", "imports", "findings"})
            self.assertEqual(result["hostAbiDigest"], digest(encode(build.host_manifest(V4))))
            build.package_report(path, FILES, COMPONENT)
            report = compatibility.read((path / "compatibility-report.json").read_bytes())
            self.assertEqual(report["runtimeProfile"], V4)
            self.assertEqual(report["authority"], "none")

    def test_only_exact_declared_new_interfaces_select_v5(self):
        for declared, expected in (([HTTP, CLOCK], V4), ([RUNTIME], V5), ([STREAMS], V5),
                                   ([HTTP, RUNTIME, CLOCK], V5), (["wasi:sockets/tcp@0.2.0"], V4),
                                   (["latent:runtime/activation@0.2.0"], V4)):
            with self.subTest(declared=declared):
                self.assertEqual(build.declared_host_abi({"imports": declared}), expected)
                self.assertEqual(build.declared_host_abi({"imports": {name: {} for name in declared}}), expected)

    def test_declaration_shape_duplicates_and_count_remain_bounded(self):
        for surface in ({}, {"imports": None}, {"imports": RUNTIME}, {"imports": [RUNTIME, RUNTIME]},
                        {"imports": [{}]}, {"imports": [True]}, {"imports": [RUNTIME] * 129}):
            with self.subTest(surface=surface), self.assertRaises(DevError):
                build.declared_host_abi(surface)

    def test_explicit_v5_inspection_and_package_bind_both_identities_without_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            result = inspect(path)
            self.assertEqual(result["hostAbiProfile"], V5)
            self.assertEqual(result["hostAbiDigest"], digest(encode(build.host_manifest(V5))))
            self.assertEqual(result["componentDigest"], digest(COMPONENT))
            build.package_report(path, FILES, COMPONENT)
            report = compatibility.read((path / "compatibility-report.json").read_bytes())
            self.assertEqual(report["runtimeProfile"], V5)
            self.assertEqual(report["componentDigest"], digest(COMPONENT))
            self.assertEqual(report["authority"], "none")
            self.assertEqual(report["status"], "incomplete")
            self.assertIn("lifecycle-unproven", [row["classification"] for row in report["findings"]])

    def test_default_v4_cannot_fall_back_after_emitted_runtime_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            with self.assertRaisesRegex(ValueError, "compatibility-failed"):
                build.inspect(EmittedGraph((RUNTIME,)), Path("wasm-tools"), path,
                              {"imports": [RUNTIME], "exports": [EXPORT]})
            retained = json.loads((path / "compatibility-inspection.json").read_bytes())
            self.assertNotIn("hostAbiProfile", retained)
            self.assertIn("unknown-import", [row["classification"] for row in retained["findings"]])

    def test_explicit_v5_does_not_authorize_undeclared_imports(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            with self.assertRaisesRegex(ValueError, "compatibility-failed"):
                inspect(path, (HTTP, STREAMS), declared=(HTTP,))
            retained = json.loads((path / "compatibility-inspection.json").read_bytes())
            self.assertIn("surface-mismatch", [row["classification"] for row in retained["findings"]])
            self.assertFalse((path / "compatibility-report.json").exists())

    def test_v5_recognition_cannot_turn_http_grants_into_runtime_or_socket_grants(self):
        host = build.host_manifest(V5)
        findings = compatibility.import_findings([HTTP, RUNTIME, STREAMS], [HTTP, RUNTIME, STREAMS], host,
                                                installed={HTTP, RUNTIME, STREAMS}, granted={HTTP})
        self.assertEqual({row["operation"] for row in findings}, {RUNTIME, STREAMS})
        self.assertTrue(all(row["classification"] == "missing-grant" for row in findings))

    def test_unsupported_versions_remain_unknown_under_explicit_v5(self):
        for name in ("latent:runtime/activation@0.2.0", "latent:network/streams@0.2.0", "wasi:sockets/tcp@0.2.0"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                path = output(temporary)
                with self.assertRaisesRegex(ValueError, "compatibility-failed"):
                    inspect(path, (name,))
                retained = json.loads((path / "compatibility-inspection.json").read_bytes())
                self.assertIn("unknown-import", [row["classification"] for row in retained["findings"]])

    def test_unknown_profile_is_rejected_before_tool_dispatch(self):
        for profile in (None, {}, "lsf-host-abi-phase3-v6", "../host-abi-phase3-v5.json"):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                path = output(temporary)
                commands = EmittedGraph((RUNTIME,))
                with self.assertRaisesRegex(DevError, "unsupported-host-profile"):
                    build.inspect(commands, Path("wasm-tools"), path,
                                  {"imports": [RUNTIME], "exports": [EXPORT]}, host_abi_profile=profile)
                self.assertEqual(commands.calls, 0)
                self.assertFalse((path / "compatibility-inspection.json").exists())

    def test_missing_v5_manifest_never_substitutes_available_v4(self):
        host = build.host_manifest(V4)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "wit").mkdir()
            (root / "wit/host-abi-phase3-v4.json").write_bytes(encode(host))
            with patch.object(build, "ROOT", root), self.assertRaises((FileNotFoundError, ValueError)):
                build.host_manifest(V5)

    def test_manifest_id_must_match_explicit_profile(self):
        host = copy.deepcopy(build.host_manifest(V4))
        with patch.object(build, "read_json", return_value=host), self.assertRaisesRegex(DevError, "profile-identity"):
            build.host_manifest(V5)

    def test_changed_v5_manifest_prevents_package_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            inspect(path)
            changed = copy.deepcopy(build.host_manifest(V5))
            changed["world"] = "latent:platform/replaced@0.5.0"
            original = build.read_json
            def read(path):
                return changed if path.name == "host-abi-phase3-v5.json" else original(path)
            with patch.object(build, "read_json", side_effect=read), self.assertRaisesRegex(DevError, "stale-inspection"):
                build.package_report(path, FILES, COMPONENT)
            self.assertFalse((path / "compatibility-report.json").exists())

    def test_v5_profile_cannot_be_removed_to_launder_inspection_as_v4(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            result = inspect(path)
            del result["hostAbiProfile"]
            (path / "compatibility-inspection.json").write_bytes(encode(result))
            with self.assertRaisesRegex(DevError, "stale-inspection"):
                build.package_report(path, FILES, COMPONENT)
            self.assertFalse((path / "compatibility-report.json").exists())

    def test_changed_component_prevents_v5_package_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            inspect(path)
            with self.assertRaisesRegex(DevError, "stale-inspection"):
                build.package_report(path, FILES, b"replaced component")
            self.assertFalse((path / "compatibility-report.json").exists())

    def test_failure_report_preserves_v5_profile_and_blocking_observations(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            with self.assertRaisesRegex(ValueError, "compatibility-failed"):
                inspect(path, (RUNTIME,), declared=(HTTP,))
            build.failure_report(path, "dotnet", "compatibility")
            report = compatibility.read((path / "compatibility-report.json").read_bytes())
            self.assertEqual(report["runtimeProfile"], V5)
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["authority"], "none")
            self.assertIn("surface-mismatch", [row["classification"] for row in report["findings"]])

    def test_stale_manifest_reporting_preserves_original_compiler_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            inspect(path)
            changed = copy.deepcopy(build.host_manifest(V5))
            changed["world"] = "latent:platform/replaced@0.5.0"
            original = build.read_json
            def read(path):
                return changed if path.name == "host-abi-phase3-v5.json" else original(path)
            with patch.object(build, "read_json", side_effect=read):
                try:
                    raise ValueError("original-compiler-failure")
                except ValueError:
                    build.failure_report(path, "dotnet", "compile")
                    with self.assertRaisesRegex(ValueError, "original-compiler-failure"):
                        raise
            marker = json.loads((path / "compatibility-report-failed.json").read_bytes())
            self.assertEqual(marker["status"], "unavailable")
            self.assertEqual(marker["authority"], "none")
            self.assertFalse((path / "compatibility-report.json").exists())

    def test_preinspection_compile_failure_uses_authoritative_declared_v5_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            (path / "surface.json").write_bytes(encode({"imports": [RUNTIME], "exports": [EXPORT]}))
            build.failure_report(path, "dotnet", "compile")
            report = compatibility.read((path / "compatibility-report.json").read_bytes())
            self.assertEqual(report["runtimeProfile"], V5)
            self.assertEqual(report["authority"], "none")
            self.assertEqual(report["status"], "incomplete")

    def test_missing_inspection_does_not_claim_success_for_declared_v5(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = output(temporary)
            (path / "surface.json").write_bytes(encode({"imports": [RUNTIME], "exports": [EXPORT]}))
            build.package_report(path, FILES, COMPONENT)
            report = compatibility.read((path / "compatibility-report.json").read_bytes())
            self.assertEqual(report["runtimeProfile"], V5)
            self.assertEqual(report["status"], "incomplete")
            self.assertEqual(report["authority"], "none")
            self.assertTrue(all(row["evidence"] == "not-evaluated" for row in report["findings"]))


if __name__ == "__main__":
    unittest.main()
