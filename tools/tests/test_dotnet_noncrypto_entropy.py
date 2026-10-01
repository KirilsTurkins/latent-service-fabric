"""Exact CLR native derivation and separate, explicitly declared entropy ports."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as XML

from tools.build_snapshot import digest, canonical
from tools.dotnet_guest import entropy, runtime
from tools.dotnet_guest.compatibility import coverage, inspect, retain_failure
from tools.rust_capsule_project import ROOT, snapshot, write_json
from tools.tests import test_dotnet_application_dependencies as fixtures


class NoncryptoNativePort(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-noncrypto-entropy-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "sdk/tools/native-entropy"
        self.source.mkdir(parents=True)
        self.archive_bytes, self.member = b"captured native archive", b"captured pal_random member"
        self.upstream = {**entropy.UPSTREAM, "archiveDigest": digest(self.archive_bytes), "archiveSize": len(self.archive_bytes),
                         "memberDigest": digest(self.member), "memberSize": len(self.member)}
        for name, body in snapshot(ROOT / "sdk/dotnet-guest/tools/native-entropy").items():
            (self.source / name).write_bytes(canonical(self.upstream) if name == "upstream.json" else body)
        self.original = self.root / "packages" / self.upstream["package"] / self.upstream["version"] / self.upstream["path"]
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(self.archive_bytes)
        self.evidence, self.output, self.project = (self.root / name for name in ("evidence", "compiled", "project"))
        for path in (self.evidence, self.output, self.project):
            path.mkdir()
        (self.project / "Capsule.csproj").write_text("<Project><PropertyGroup><RuntimeIdentifier>wasi-wasm</RuntimeIdentifier></PropertyGroup></Project>")
        self.commands, self.protected = [], []
        self.compiler = SimpleNamespace(sdk=self.root / "sdk", package_cache=self.root / "packages", wasi_sdk=self.root / "wasi",
            commands=SimpleNamespace(output=self.evidence), isolation=SimpleNamespace(protect_inputs=lambda *rows: self.protected.extend(rows)))
        def run(name, executable, *arguments):
            self.commands.append((name, executable, arguments))
            if name == "noncrypto-native-preimage":
                return self.member
            if name == "noncrypto-entropy-compile":
                Path(arguments[-1]).write_bytes(b"bounded derived native object")
                return b""
            raise AssertionError(name)
        self.compiler.run = run
        self.pin = patch.object(entropy, "UPSTREAM", self.upstream)
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def prepare(self):
        return entropy.prepare(self.compiler, [runtime.CLOCK, runtime.RANDOM], self.project, self.output)

    def response(self, port, *, objects=1, wraps=1, secure=False):
        target = self.project / "obj/Release/link.rsp"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = ["\"" + str(port.object) + "\""] * objects + [entropy.WRAP] * wraps
        if secure:
            body.append("-Wl,--wrap=SystemNative_GetCryptographicallySecureRandomBytes")
        target.write_text("\n".join(body), encoding="utf-8")
        return target

    def test_absent_declaration_never_reads_or_compiles_a_native_port(self):
        self.compiler.sdk = self.root / "absent-sdk"
        self.assertIsNone(entropy.prepare(self.compiler, [runtime.CLOCK], self.project, self.output))
        self.assertEqual(self.commands, [])
        self.assertEqual(self.protected, [])
        self.assertFalse((self.evidence / "noncrypto-entropy.o").exists())

    def test_exact_preimages_derive_protected_object_and_bind_actual_link_response(self):
        port = self.prepare()
        self.response(port)
        value = port.finish(self.project, self.evidence)
        self.assertEqual([row[0] for row in self.commands], ["noncrypto-native-preimage", "noncrypto-entropy-compile"])
        self.assertEqual(value["original"]["digest"], digest(self.archive_bytes))
        self.assertEqual(value["originalMember"]["digest"], digest(self.member))
        self.assertEqual(value["derived"]["digest"], digest(port.object.read_bytes()))
        self.assertEqual(value["secureRandom"], "unchanged-denial")
        self.assertFalse(value["ordinaryLibraryExecutionQualified"])
        self.assertEqual(value["nativeLinkBinding"]["objectOccurrences"], 1)
        self.assertEqual(port.retained.read_bytes(), port.object.read_bytes())
        self.assertEqual(set(self.protected), {port.object, port.targets, port.private_source})
        self.assertTrue(all(path.is_relative_to(self.output) for path in self.protected))

    def test_changed_archive_and_member_fail_before_object_compilation(self):
        self.original.write_bytes(b"changed native preimage")
        with self.assertRaisesRegex(ValueError, "unsupported-native-preimage"):
            self.prepare()
        self.assertEqual(self.commands, [])
        self.original.write_bytes(self.archive_bytes)
        self.member = b"changed member"
        with self.assertRaisesRegex(ValueError, "unsupported-member-preimage"):
            self.prepare()
        self.assertEqual([row[0] for row in self.commands], ["noncrypto-native-preimage"])
        self.assertFalse((self.output / "noncrypto-entropy-port").exists())

    def test_unknown_profile_descriptor_cannot_select_a_native_entrypoint(self):
        (self.source / "upstream.json").write_bytes(canonical({**self.upstream, "entrypoint": "SystemNative_GetCryptographicallySecureRandomBytes"}))
        with self.assertRaisesRegex(ValueError, "unreviewed-upstream"):
            self.prepare()
        self.assertEqual(self.commands, [])

    def test_missing_duplicate_and_secure_redirects_fail_actual_link_binding(self):
        port = self.prepare()
        for objects, wraps, secure in ((0, 1, False), (2, 1, False), (1, 0, False), (1, 2, False), (1, 1, True)):
            with self.subTest(objects=objects, wraps=wraps, secure=secure):
                self.response(port, objects=objects, wraps=wraps, secure=secure)
                with self.assertRaisesRegex(ValueError, "native-link-binding"):
                    port.finish(self.project, self.evidence)
                self.assertFalse((self.evidence / "noncrypto-entropy-port.json").exists())

    def test_original_source_private_object_targets_and_retained_changes_are_rejected(self):
        port = self.prepare()
        for path in (self.original, self.source / "entropy.c", port.private_source, port.object, port.retained, port.targets):
            with self.subTest(path=path):
                before = path.read_bytes()
                path.write_bytes(before + b"changed")
                with self.assertRaises(ValueError):
                    port.recheck()
                path.write_bytes(before)
                port.recheck()

    def test_private_msbuild_paths_are_literal_and_control_characters_are_denied(self):
        unusual = self.output / "literal % $(TOKEN); α"
        unusual.mkdir()
        port = entropy.prepare(self.compiler, [runtime.CLOCK, runtime.RANDOM], self.project, unusual)
        document = XML.fromstring((self.project / "Capsule.csproj").read_bytes())
        value = document.find("PropertyGroup/LsfInternalNoncryptoEntropyObject")
        self.assertIsNotNone(value)
        self.assertIn("%25 %24%28TOKEN%29%3B α", value.text)
        self.assertEqual(document.find("Import").attrib["Project"], entropy.msbuild_literal(port.targets))
        with self.assertRaisesRegex(ValueError, "path-limit"):
            entropy.msbuild_literal(Path("line\nfeed"))


class SeparateEntropySelection(unittest.TestCase):
    def graph(self, imports=(), exports=()):
        graph = fixtures.CapturedCompilerSelection.graph(self, [*imports, *exports])
        graph["worlds"][0]["imports"] = {str(i): {"interface": {"id": i}} for i in range(len(imports))}
        graph["worlds"][0]["exports"] = {str(i): {"interface": {"id": i}} for i in range(len(imports), len(imports) + len(exports))}
        return graph

    def test_only_exact_declaration_enables_insecure_versions_and_secure_stays_primary(self):
        for name in sorted(runtime.WASI_INSECURE_IMPORTS):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "entropy-requires-declaration"):
                    runtime.additional([runtime.CLOCK], [name])
                self.assertEqual(runtime.select([runtime.CLOCK, runtime.RANDOM], [name, "wasi:random/random@0.2.6"]), "closed")
                self.assertEqual(runtime.additional([runtime.CLOCK, runtime.RANDOM], [name]), ("entropy",))
        self.assertEqual(runtime.additional([runtime.CLOCK, runtime.RANDOM], ["wasi:random/random@0.2.6"]), ())
        for name in ("latent:random/random@0.1.1", "latent:random/bytes@0.1.0", "wasi:random/insecure@0.2.1"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                runtime.additional([runtime.CLOCK, name], ["wasi:random/insecure@0.2.0"])

    def test_separate_export_coverage_rejects_duplicate_authority_and_retains_legacy_gaps(self):
        raw = self.graph(imports=["wasi:random/random@0.2.6", "wasi:random/insecure@0.2.0"])
        primary = self.graph(exports=["wasi:random/random@0.2.6"])
        extra = self.graph(imports=[runtime.RANDOM], exports=["wasi:random/insecure@0.2.0"])
        self.assertEqual(coverage(raw, primary)["gaps"], [{"interface": "wasi:random/insecure@0.2.0", "kind": "interface"}])
        self.assertEqual(coverage(raw, primary, additional_adapters=[extra])["gaps"], [])
        with self.assertRaisesRegex(ValueError, "duplicate-adapter-export"):
            coverage(raw, primary, additional_adapters=[primary])

    def test_completed_build_binds_final_derivation_without_overwriting_preparation(self):
        from tools.dotnet_guest import build as builder
        from tools.dotnet_guest.project import create
        from tools.build_observation import file_identity
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            application = create(root / "application", "greeting")
            tools = root / "tools"
            tools.mkdir()
            native = root / "contracts-tool"
            native.write_bytes(b"owned unit-boundary binary identity")
            original, derived = {"name": "original-composer"}, {"name": entropy.PROFILE}
            instances = []
            class Commands:
                def __init__(self, work, output, environment):
                    self.output, self.environment, self.records = output, environment, []
                def run(self, stage, executable, *arguments):
                    self.assert_contracts = stage
                    destination = arguments[-1]
                    destination.mkdir()
                    for name in ("contracts.json", "wit-lock.json", "surface.json"):
                        write_json(destination / name, {})
            class Compiler:
                def __init__(self, tools, commands, vendor, **keywords):
                    self.commands, self.materials, self.before = commands, [], {}
                    self.compiler_patches, self.generated_materials = [original], []
                    self.wasm, self.rechecked = native, False
                    instances.append(self)
                def compile(self, work, world, output):
                    output.mkdir()
                    component = output / "component.wasm"
                    component.write_bytes(b"unit boundary component")
                    obj = output / "derived.o"
                    obj.write_bytes(b"completed unit boundary derivation")
                    self.generated_materials.append(file_identity(obj, "noncrypto-entropy-object"))
                    self.compiler_patches = [*self.compiler_patches, derived]
                    for name in ("runtime-profile.json", "closed-runtime-coverage.json"):
                        write_json(self.commands.output / name, {})
                    return component, {"filesDigest": digest(b"unit binding")}
                def check_unchanged(self):
                    self.rechecked = True
            def package(output, *arguments):
                write_json(output / "package-source.json", {"layers": []})
            with patch.object(builder, "Commands", Commands), patch.object(builder, "Compiler", Compiler), \
                    patch.object(builder.guest_compatibility_build, "inspect"), patch.object(builder, "package_inputs", package):
                output = builder.build(application, root / "output", native, None,
                    "https://github.com/example/entropy-unit-boundary", tools=tools)
            preparation = (output / "compiler-patches-preparation.json").read_bytes()
            complete = (output / "compiler-patches.json").read_bytes()
            self.assertEqual(json.loads(preparation)["patches"], [original])
            self.assertEqual(json.loads(complete)["patches"], [original, derived])
            observation = json.loads((output / "build-observation.json").read_bytes())
            materials = {row["name"]: row for row in observation["materials"]}
            self.assertEqual(materials["automatic-compiler-patches"]["digest"], digest(complete))
            self.assertEqual(materials["compiler-patch-preparation"]["digest"], digest(preparation))
            self.assertEqual(materials["noncrypto-entropy-object"]["digest"], digest(b"completed unit boundary derivation"))
            self.assertTrue(instances[0].rechecked)

    def test_real_compiler_seam_passes_two_plugs_and_retains_both_graph_identities(self):
        fixture = fixtures.CapturedCompilerSelection()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        compiler, work, output = fixture.application(fixture.root, emitted=[runtime.CLOCK,
            "wasi:random/random@0.2.6", "wasi:random/insecure@0.2.6"], final=[runtime.CLOCK, runtime.RANDOM])
        compiler.generated_materials = []
        compiler.wac.write_bytes(b"owned unit-boundary component composer")
        original_run, plugs = compiler.run, []
        def run(stage, executable, *arguments):
            if stage == "declared-runtime-wit":
                return canonical(self.graph(imports=[runtime.CLOCK, runtime.RANDOM]))
            if stage == "closed-runtime-adapter-wit":
                return canonical(self.graph(exports=["wasi:random/random@0.2.6"]))
            if stage == "additional-runtime-entropy-wit":
                return canonical(self.graph(imports=[runtime.RANDOM], exports=sorted(runtime.WASI_INSECURE_IMPORTS)))
            if stage == "closed-runtime-composition":
                plugs.extend(arguments)
            return original_run(stage, executable, *arguments)
        compiler.run = run
        with patch("tools.dotnet_application_dependencies.configure", fixture.configure), patch("tools.dotnet_guest.entropy.prepare") as prepare:
            prepare.return_value = None
            component, result = compiler.compile(work, "examples:greeting/service@1.0.0", output)
        prepare.assert_called_once_with(compiler, [runtime.CLOCK, runtime.RANDOM], output / "project", output)
        self.assertTrue(component.is_file())
        self.assertEqual(plugs[0], "compose")
        self.assertEqual(plugs.count("--dep"), 3)
        self.assertIn("lsf:adapter0=" + str(compiler.runtimes["closed"]), plugs)
        self.assertIn("lsf:adapter1=" + str(compiler.runtimes["entropy"]), plugs)
        source = (fixture.evidence / "runtime-composition.wac").read_text()
        self.assertEqual(source.count('"wasi:random/insecure@0.2.6": runtime1'), 1)
        self.assertNotIn('"wasi:random/insecure@0.2.0":', source)
        materials = {row["name"] for row in compiler.generated_materials}
        self.assertEqual(materials, {"runtime-composition", "runtime-composition-source"})
        self.assertEqual(result["runtimeProfile"]["profile"], "closed")
        self.assertEqual(result["runtimeProfile"]["additionalAdapters"][0]["name"], "noncrypto-entropy")
        receipt = json.loads((fixture.evidence / "closed-runtime-coverage.json").read_bytes())
        self.assertEqual(receipt["additionalAdapters"][0]["componentDigest"], digest(compiler.runtimes["entropy"].read_bytes()))
        self.assertEqual(receipt["gaps"], [])
        self.assertTrue((fixture.evidence / "native-aot-raw.wasm").is_file())
        (fixture.evidence / "source-inputs.json").write_bytes(b"reviewed-source")
        retain_failure(fixture.evidence)
        (fixture.evidence / "additional-runtime-entropy.wit.json").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "stale-receipt"):
            retain_failure(fixture.evidence)


if __name__ == "__main__":
    unittest.main()
