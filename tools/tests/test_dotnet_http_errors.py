"""Compiler ownership/authority controls; the real BCL probe is separate."""
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.dotnet_guest import http_errors, runtime
from tools.dotnet_guest.compiler import Compiler
from tools.dotnet_guest.project import create, validate
from tools.rust_capsule_project import ROOT, digest, read_file, snapshot, write_json


class HttpErrorPortTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-http-errors-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.sdk = ROOT / "sdk/dotnet-guest"
        self.tools, self.project, self.output, self.evidence = [self.root / name for name in
            ("tools", "project", "output", "evidence")]
        for directory in (self.tools, self.project, self.output, self.evidence):
            directory.mkdir()
        self.project.joinpath("Capsule.csproj").write_text('<Project><PropertyGroup /></Project>')
        shutil.copytree(self.sdk / "tools/http-errors", self.tools / "http-errors-source")
        binary = self.tools / "http-errors"
        binary.mkdir()
        (binary / "HttpErrors.dll").write_bytes(b"control-compiler-tool")
        (binary / "Mono.Cecil.dll").write_bytes(b"control-cecil")
        self.addCleanup(patch.stopall)
        patch.object(http_errors, "SOURCE_DIGEST", digest(b"control-original")).start()
        patch.object(http_errors, "CECIL_DIGEST", digest(b"control-cecil")).start()
        for path in http_errors.source_paths(self.tools):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"control-original")
        self.stages = []

    def run_tool(self, stage, *arguments):
        self.stages.append(stage)
        assembly, receipt = arguments[-2:]
        assembly.write_bytes(b"control-derived")
        write_json(receipt, {"patch": "latent.dotnet.http-errors.v1", "sourceDigest": http_errors.SOURCE_DIGEST,
            "outputDigest": digest(b"control-derived"), "cecilDigest": http_errors.CECIL_DIGEST,
            "method": http_errors.METHOD, "categories": list(http_errors.MARKERS),
            "arbitraryPayloadDisclosure": False, "defaultClientComponentQualified": False})

    def prepare(self, declared=None):
        return http_errors.prepare(self.sdk, self.tools, self.root / "dotnet", declared or
            [runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION], self.project, self.output, self.evidence, self.run_tool)

    def reference_files(self, port, references=None, response=None):
        values = references if references is not None else [str(self.root / "other.dll"), str(port.assembly)]
        port.reference_receipt.write_text("\n".join(values) + "\n", encoding="utf-8")
        response_path = self.project / "obj/Release/net10.0/wasi-wasm/native/Capsule.ilc.rsp"
        response_path.parent.mkdir(parents=True)
        response_path.write_text(response if response is not None else "\n".join("-r:" + path for path in values), encoding="utf-8")
        return response_path

    def test_partial_and_opaque_grants_do_not_install_a_bcl_port_or_touch_inputs(self):
        original = snapshot(self.root)
        for declared in ([runtime.CLOCK], [runtime.CLOCK, runtime.HTTP], [runtime.CLOCK, runtime.ACTIVATION],
                         [runtime.CLOCK, runtime.ACTIVATION, "latent:network/streams@0.1.0"],
                         [runtime.CLOCK, runtime.ACTIVATION, "latent:http/streaming@0.3.1"]):
            with self.subTest(declared=declared):
                self.assertIsNone(self.prepare(declared))
                self.assertEqual(snapshot(self.root), original)
        self.assertEqual(self.stages, [])

    def test_sdk_capture_rejects_modified_patch_sources_and_stale_locks(self):
        work = create(self.root / "application", "greeting")
        original = snapshot(work)
        for name in ("Program.cs", "HttpErrors.csproj", "HttpErrors.targets"):
            key = "vendor/lsf/sdk/dotnet-guest/tools/http-errors/" + name
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "vendored SDK changed"):
                validate({**original, key: original[key] + b"\n"})
        (self.tools / "http-errors-source/Program.cs").write_bytes(b"changed-installed-source")
        with self.assertRaisesRegex(ValueError, "installed-source-drift"):
            self.prepare()
        self.assertEqual(self.stages, [])

    def test_unknown_framework_or_cecil_preimage_denies_before_project_mutation(self):
        original_project = (self.project / "Capsule.csproj").read_bytes()
        for path in (*http_errors.source_paths(self.tools), self.tools / "http-errors/Mono.Cecil.dll"):
            original = path.read_bytes()
            path.write_bytes(b"unknown-preimage")
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "unsupported-material"):
                self.prepare()
            self.assertEqual((self.project / "Capsule.csproj").read_bytes(), original_project)
            self.assertEqual(self.stages, [])
            path.write_bytes(original)

    def test_private_derived_owner_requires_actual_native_aot_reference_evidence(self):
        originals = {path: path.read_bytes() for path in http_errors.source_paths(self.tools)}
        port = self.prepare()
        self.assertEqual(self.stages, ["http-errors-rewrite"])
        self.assertFalse(json.loads(read_file(self.evidence / "http-error-port-preparation.json"))["defaultClientComponentQualified"])
        self.assertTrue(port.retained.is_file())
        self.reference_files(port)
        result = port.finish(self.project, self.evidence)
        self.assertEqual(len(result["nativeAotReferenceBinding"]["responseFiles"]), 1)
        self.assertFalse(result["defaultClientComponentQualified"])
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)

    def test_original_unknown_and_duplicate_rsp_references_cannot_qualify_the_port(self):
        port = self.prepare()
        response = self.reference_files(port)
        for value in (str(port.originals[0]), str(self.root / "unknown/System.Net.Http.dll")):
            response.write_text("-r:" + value, encoding="utf-8")
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "reference-drift"):
                port.finish(self.project, self.evidence)
        response.write_text("-r:" + str(port.assembly), encoding="utf-8")
        second = response.with_name("second.rsp")
        second.write_bytes(response.read_bytes())
        with self.assertRaisesRegex(ValueError, "reference-not-observed"):
            port.finish(self.project, self.evidence)
        second.unlink()
        port.reference_receipt.write_text(str(port.originals[0]) + "\n" + str(port.assembly), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "original-reference-survived"):
            port.finish(self.project, self.evidence)

    def test_changed_derived_retained_or_target_bytes_cannot_be_reused(self):
        port = self.prepare()
        self.reference_files(port)
        for path in (port.assembly, port.retained, port.targets):
            original = path.read_bytes()
            path.write_bytes(b"changed-after-derivation")
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "changed"):
                port.finish(self.project, self.evidence)
            path.write_bytes(original)

    def test_rewrite_receipt_cannot_introduce_arbitrary_payload_or_change_categories(self):
        valid_run = self.run_tool
        for name, value in (("method", "arbitrary-private-message"), ("categories", ["new-category"]),
                            ("arbitraryPayloadDisclosure", True), ("sourceDigest", "sha256:" + "0" * 64)):
            with self.subTest(name=name), tempfile.TemporaryDirectory(dir=self.root) as temporary:
                output = Path(temporary)
                def malformed(stage, *arguments):
                    valid_run(stage, *arguments)
                    receipt = json.loads(read_file(arguments[-1]))
                    receipt[name] = value
                    arguments[-1].write_text(json.dumps(receipt), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "rewrite-receipt"):
                    http_errors.prepare(self.sdk, self.tools, self.root / "dotnet",
                        [runtime.CLOCK, runtime.HTTP, runtime.ACTIVATION], self.project, output, self.evidence, malformed)
        self.assertFalse((self.evidence / "derived-System.Net.Http.dll").exists())


class RawCompilerRetentionTests(unittest.TestCase):
    @staticmethod
    def graph(imports):
        packages, interfaces = [{"name": "examples:greeting@1.0.0"}], []
        for identity in imports:
            base, version = identity.split("@")
            package, name = base.rsplit("/", 1)
            packages.append({"name": package + "@" + version})
            interfaces.append({"name": name, "package": len(packages) - 1, "functions": {}, "types": {}})
        return {"worlds": [{"name": "service", "package": 0,
            "imports": {str(index): {"interface": {"id": index}} for index in range(len(interfaces))},
            "exports": {}}], "interfaces": interfaces, "types": [], "packages": packages}

    def compile(self, root, evidence, raw_wit):
        work = create(root / "application", "greeting")
        output = root / "compiled"
        compiler = Compiler.__new__(Compiler)
        compiler.sdk = work / "vendor/lsf/sdk/dotnet-guest"
        compiler.tools, compiler.dotnet, compiler.wasm, compiler.wac = [root / name for name in
            ("tools", "dotnet", "wasm-tools", "wac")]
        compiler.offline, compiler.wasi_sdk, compiler.generated_materials = False, root / "wasi-sdk", []
        compiler.runtimes = {}
        stages, receipt = [], {"outputs": {"ServiceWorld.cs": "captured-binding"}}
        def run(stage, *arguments):
            stages.append(stage)
            if stage == "declared-runtime-wit":
                return json.dumps(self.graph([runtime.CLOCK])).encode()
            if stage == "bindings":
                generated = output / "generated"
                generated.mkdir()
                write_json(generated / "bindings.json", receipt)
            if stage == "canonical-wit":
                return (work / "wit/world.wit").read_bytes()
            if stage == "native-aot":
                project = output / "project"
                (project / "obj").mkdir()
                write_json(project / "obj/bindings.json", receipt)
                raw = project / "bin/Release/net10.0/wasi-wasm/publish/Capsule.wasm"
                raw.parent.mkdir(parents=True)
                raw.write_bytes(b"\0asm\x0d\0\x01\0")
            if stage == "native-runtime-wit":
                return raw_wit
            return b""
        compiler.commands = SimpleNamespace(run=run, output=evidence)
        actual_temporary = tempfile.TemporaryDirectory
        with patch("tools.dotnet_guest.compiler.install_sdk", return_value={}), patch(
                "tools.dotnet_guest.compiler.tempfile.TemporaryDirectory",
                side_effect=lambda **kwargs: actual_temporary(prefix=kwargs["prefix"], dir=root)):
            compiler.compile(work, "examples:greeting/service@1.0.0", output)
        return stages

    def test_profile_rejection_keeps_raw_component_and_wit_after_workspace_retirement(self):
        with tempfile.TemporaryDirectory() as retained:
            evidence = Path(retained)
            graph = self.graph(["wasi:http/types@0.2.1"])
            with tempfile.TemporaryDirectory() as workspace:
                with self.assertRaisesRegex(ValueError, "unsupported-wasi-import"):
                    self.compile(Path(workspace), evidence, json.dumps(graph).encode())
            self.assertEqual((evidence / "native-aot-raw.wasm").read_bytes(), b"\0asm\x0d\0\x01\0")
            self.assertEqual(json.loads(read_file(evidence / "native-aot-raw.wit.json")), graph)
            self.assertFalse((evidence / "runtime-profile.json").exists())

    def test_oversized_raw_wit_is_not_published_or_composed(self):
        with tempfile.TemporaryDirectory() as retained, tempfile.TemporaryDirectory() as workspace:
            evidence = Path(retained)
            with self.assertRaisesRegex(ValueError, "raw-wit-byte-limit"):
                self.compile(Path(workspace), evidence, b" " * (4 * 1024 * 1024 + 1))
            self.assertFalse((evidence / "native-aot-raw.wit.json").exists())
            self.assertFalse((evidence / "runtime-profile.json").exists())
            self.assertTrue((evidence / "native-aot-raw.wasm").is_file())


if __name__ == "__main__":
    unittest.main()
