"""Exact edges retain compatible exports without WAC plug's duplicate argument."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools.dotnet_guest.composer import compose_exact
from tools.rust_capsule_project import digest

CLOCK = "latent:clock/monotonic@0.1.0"
RANDOM = "latent:random/random@0.1.0"
SECURE = "wasi:random/random@0.2.6"
INSECURE = "wasi:random/insecure@0.2.6"
OLDER = "wasi:random/insecure@0.2.0"


def graph(imports=(), exports=()):
    interfaces, packages = [], [{"name": "examples:greeting@1.0.0"}]
    for value in (*imports, *exports):
        base, version = value.split("@")
        package, name = base.rsplit("/", 1)
        packages.append({"name": package + "@" + version})
        interfaces.append({"name": name, "package": len(packages) - 1, "functions": {}, "types": {}})
    return {"worlds": [{"name": "service", "package": 0,
        "imports": {str(index): {"interface": {"id": index}} for index in range(len(imports))},
        "exports": {str(index): {"interface": {"id": index}}
                    for index in range(len(imports), len(interfaces))}}],
        "interfaces": interfaces, "packages": packages, "types": []}


class ExactCompositionTests(unittest.TestCase):
    def fixture(self, root, *, required=INSECURE, duplicate=False, changed=None, failure=None):
        work, evidence = root / "work", root / "evidence"
        work.mkdir()
        evidence.mkdir()
        paths = {name: work / name for name in ("raw", "primary", "entropy", "wac")}
        for name, path in paths.items():
            path.write_bytes(("unit-boundary-" + name).encode())
        graphs = [("native-aot-raw.wit.json", graph(imports=[CLOCK, SECURE, required])),
                  ("closed-runtime-adapter.wit.json", graph(imports=[CLOCK], exports=[SECURE])),
                  ("additional-runtime-entropy.wit.json", graph(imports=[RANDOM],
                     exports=[OLDER, INSECURE, *([SECURE] if duplicate else [])]))]
        for name, observed_graph in graphs:
            (evidence / name).write_bytes(json.dumps(observed_graph).encode())
        coverage = {"rawComponentDigest": digest(paths["raw"].read_bytes()),
            "rawWitDigest": digest((evidence / graphs[0][0]).read_bytes()),
            "runtimeAdapterDigest": digest(paths["primary"].read_bytes()),
            "runtimeWitDigest": digest((evidence / graphs[1][0]).read_bytes()),
            "additionalAdapters": [{"name": "entropy", "witSource": graphs[2][0],
                "componentDigest": digest(paths["entropy"].read_bytes()),
                "witDigest": digest((evidence / graphs[2][0]).read_bytes())}]}
        calls, protected = [], []
        def run(stage, executable, *arguments):
            calls.append((stage, executable, arguments))
            if failure is not None:
                raise failure
            if changed is not None:
                changed(paths, evidence)
            Path(arguments[-1]).write_bytes(b"unit-boundary-composed-component")
        compiler = SimpleNamespace(commands=SimpleNamespace(output=evidence), runtime=paths["primary"],
            wac=paths["wac"], run=run, generated_materials=[],
            isolation=SimpleNamespace(protect_inputs=lambda *values: protected.extend(values)))
        return compiler, paths, evidence, work / "component.wasm", coverage, calls, protected

    def test_exact_versions_have_one_named_edge_and_host_authority_is_passthrough(self):
        with tempfile.TemporaryDirectory() as temporary:
            compiler, paths, evidence, component, coverage, calls, protected = self.fixture(Path(temporary))
            result = compose_exact(compiler, paths["raw"], component, coverage,
                                   additional_adapters=[("entropy", paths["entropy"])])
            source = (evidence / "runtime-composition.wac").read_bytes()
            self.assertEqual(source.count(b'"wasi:random/insecure@0.2.6": runtime1'), 1)
            self.assertNotIn((OLDER + '":').encode(), source)
            self.assertNotIn((CLOCK + '":').encode(), source)
            self.assertEqual(result["unmodifiedHostImports"], [CLOCK])
            self.assertEqual(result["matching"], "exact-interface-names")
            self.assertEqual([row["name"] for row in result["adapters"]], ["primary", "entropy"])
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][2].count("--dep"), 3)
            self.assertNotIn("--no-validate", calls[0][2])
            self.assertNotIn("--import-dependencies", calls[0][2])
            self.assertIn(paths["raw"], protected)
            self.assertIn(component.parent / "runtime-composition.wac", protected)
            self.assertEqual(source, (component.parent / "runtime-composition.wac").read_bytes())
            self.assertEqual({row["name"] for row in compiler.generated_materials},
                             {"runtime-composition-source", "runtime-composition"})

    def test_changed_binary_or_graph_is_rejected_before_composer_execution(self):
        for selected in ("raw", "primary", "entropy", "native-aot-raw.wit.json",
                         "closed-runtime-adapter.wit.json", "additional-runtime-entropy.wit.json"):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, evidence, component, coverage, calls, _protected = self.fixture(Path(temporary))
                (paths[selected] if selected in paths else evidence / selected).write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError, "stale-inspection"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                                  additional_adapters=[("entropy", paths["entropy"])])
                self.assertEqual(calls, [])
                self.assertFalse(component.exists())

    def test_compatible_version_is_not_an_exact_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            compiler, paths, _evidence, component, coverage, calls, _protected = self.fixture(
                Path(temporary), required="wasi:random/insecure@0.2.1")
            with self.assertRaisesRegex(ValueError, "exact-export-missing"):
                compose_exact(compiler, paths["raw"], component, coverage,
                              additional_adapters=[("entropy", paths["entropy"])])
            self.assertEqual(calls, [])

    def test_duplicate_exports_and_missing_or_wrong_adapter_receipts_fail_closed(self):
        for selected in ("duplicate", "empty", "extra", "receipt"):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, _evidence, component, coverage, calls, _protected = self.fixture(
                    Path(temporary), duplicate=selected == "duplicate")
                additional = [("entropy", paths["entropy"])]
                if selected == "empty":
                    additional = []
                elif selected == "extra":
                    additional *= 5
                elif selected == "receipt":
                    coverage["additionalAdapters"][0]["name"] = "unobserved"
                with self.assertRaisesRegex(ValueError, "duplicate-export|adapter-limit|adapter-receipt"):
                    compose_exact(compiler, paths["raw"], component, coverage, additional_adapters=additional)
                self.assertEqual(calls, [])

    def test_process_mutation_is_rejected_without_a_completed_receipt(self):
        for selected in ("raw", "entropy", "retained-source", "private-source", "graph"):
            with self.subTest(selected=selected), tempfile.TemporaryDirectory() as temporary:
                def mutate(paths, evidence):
                    path = (paths[selected] if selected in paths else
                            evidence / "runtime-composition.wac" if selected == "retained-source" else
                            paths["raw"].parent / "runtime-composition.wac" if selected == "private-source" else
                            evidence / "additional-runtime-entropy.wit.json")
                    path.write_bytes(b"changed-after-execution")
                compiler, paths, evidence, component, coverage, calls, _protected = self.fixture(
                    Path(temporary), changed=mutate)
                with self.assertRaisesRegex(ValueError, "input-changed|source-changed"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                                  additional_adapters=[("entropy", paths["entropy"])])
                self.assertEqual(len(calls), 1)
                self.assertFalse((evidence / "runtime-composition.json").exists())
                self.assertEqual(compiler.generated_materials, [])

    def test_original_composer_failure_keeps_raw_bytes_and_retained_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            original = ValueError("original-composer-type-error")
            compiler, paths, evidence, component, coverage, calls, _protected = self.fixture(
                Path(temporary), failure=original)
            before = paths["raw"].read_bytes()
            with self.assertRaises(ValueError) as observed:
                compose_exact(compiler, paths["raw"], component, coverage,
                              additional_adapters=[("entropy", paths["entropy"])])
            self.assertIs(observed.exception, original)
            self.assertEqual(paths["raw"].read_bytes(), before)
            self.assertTrue((evidence / "runtime-composition.wac").is_file())
            self.assertFalse((evidence / "runtime-composition.json").exists())
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
