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
        # Named composition edges consume callable members, not type-only imports.
        # This member-name fixture does not establish signature conformance.
        symbol = {
            "latent:clock/monotonic": "now-nanos",
            "latent:clock/wall": "now-unix-millis",
            "wasi:clocks/wall-clock": "now",
            "latent:random/random": "u64-value",
            "wasi:random/random": "get-random-bytes",
            "wasi:random/insecure": "get-insecure-random-u64",
        }[base]
        interfaces.append({"name": name, "package": len(packages) - 1,
                           "functions": {symbol: {"name": symbol}}, "types": {}})
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


class WallFacetCompositionTests(unittest.TestCase):
    def fixture(self, root, *, name="wall", imports=None, exports=None, raw_wall=True, primary_wall=True):
        from tools.dotnet_guest.runtime import WALL, WASI_WALL
        compiler, paths, evidence, component, coverage, calls, protected = ExactCompositionTests().fixture(
            root, required=WASI_WALL)
        raw = graph(imports=[CLOCK, SECURE, *([WASI_WALL] if raw_wall else [])])
        primary = graph(imports=[CLOCK], exports=[SECURE, *([WASI_WALL] if primary_wall else [])])
        facet = graph(imports=[WALL] if imports is None else imports,
                      exports=[WASI_WALL] if exports is None else exports)
        for source, value in (("native-aot-raw.wit.json", raw),
                              ("closed-runtime-adapter.wit.json", primary),
                              ("additional-runtime-" + name + ".wit.json", facet)):
            (evidence / source).write_bytes(json.dumps(value).encode())
        coverage["rawWitDigest"] = digest((evidence / "native-aot-raw.wit.json").read_bytes())
        coverage["runtimeWitDigest"] = digest((evidence / "closed-runtime-adapter.wit.json").read_bytes())
        coverage["additionalAdapters"] = [{"name": name, "witSource": "additional-runtime-" + name + ".wit.json",
            "componentDigest": digest(paths["entropy"].read_bytes()),
            "witDigest": digest((evidence / ("additional-runtime-" + name + ".wit.json")).read_bytes())}]
        return compiler, paths, evidence, component, coverage, calls, protected, (raw, primary, facet)

    def test_named_wall_facet_replaces_only_one_exact_closed_clock_edge(self):
        from tools.dotnet_guest.runtime import WASI_WALL
        with tempfile.TemporaryDirectory() as temporary:
            compiler, paths, evidence, component, coverage, calls, protected, _graphs = self.fixture(Path(temporary))
            result = compose_exact(compiler, paths["raw"], component, coverage,
                                   additional_adapters=[("wall", paths["entropy"])])
            source = (evidence / "runtime-composition.wac").read_bytes()
            self.assertEqual(source.count((json.dumps(WASI_WALL) + ": runtime1").encode()), 1)
            self.assertIn((json.dumps(SECURE) + ": runtime0").encode(), source)
            self.assertEqual(result["explicitFacetOverrides"], [
                {"interface": WASI_WALL, "fromAdapter": "primary", "toAdapter": "wall"}])
            self.assertEqual(result["unmodifiedHostImports"], [CLOCK])
            self.assertEqual(len(calls), 1)
            self.assertIn(paths["raw"], protected)
            self.assertNotIn("--no-validate", calls[0][2])
            self.assertEqual(source, (component.parent / "runtime-composition.wac").read_bytes())

    def test_wall_name_does_not_authorize_different_ports_versions_or_extra_authority(self):
        from tools.dotnet_guest.runtime import WALL, WASI_WALL
        changes = [{"imports": [CLOCK]}, {"imports": [WALL, RANDOM]},
                   {"imports": ["latent:clock/wall@0.1.1"]},
                   {"exports": ["wasi:clocks/wall-clock@0.2.0"]},
                   {"exports": [WASI_WALL, SECURE]}, {"raw_wall": False}, {"primary_wall": False}]
        for changed in changes:
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(
                    Path(temporary), **changed)
                with self.assertRaisesRegex(ValueError, "wall-facet-shape"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                                  additional_adapters=[("wall", paths["entropy"])])
                self.assertEqual(calls, [])
                self.assertFalse(component.exists())

    def test_duplicate_clock_export_requires_exact_named_wall_facet(self):
        for name in ("entropy", "wall-clock", "primary"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(
                    Path(temporary), name=name)
                with self.assertRaisesRegex(ValueError, "duplicate-export"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                                  additional_adapters=[(name, paths["entropy"])])
                self.assertEqual(calls, [])

    def test_member_coverage_accepts_only_the_same_named_wall_override(self):
        from tools.dotnet_guest.compatibility import coverage as member_coverage
        with tempfile.TemporaryDirectory() as temporary:
            *_values, graphs = self.fixture(Path(temporary))
            raw, primary, facet = graphs
            result = member_coverage(raw, primary, additional_adapters=[facet], additional_names=["wall"])
            self.assertEqual(result["gaps"], [])
            for names in ((), ("entropy",)):
                with self.subTest(names=names), self.assertRaisesRegex(ValueError, "duplicate-adapter-export"):
                    member_coverage(raw, primary, additional_adapters=[facet], additional_names=names)
            with self.assertRaisesRegex(ValueError, "additional-adapter-name"):
                member_coverage(raw, primary, additional_adapters=[facet, facet], additional_names=["wall", "wall"])

    def test_changed_wall_facet_bytes_fail_before_composer_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(Path(temporary))
            paths["entropy"].write_bytes(b"changed selected wall facet")
            with self.assertRaisesRegex(ValueError, "stale-inspection"):
                compose_exact(compiler, paths["raw"], component, coverage,
                              additional_adapters=[("wall", paths["entropy"])])
            self.assertEqual(calls, [])


class RetirementCompositionTests(unittest.TestCase):
    def fixture(self, root, *, selected=True, consumer=True, primary=True, extra=False,
                consumer_change=None, provider_change=None):
        from tools.dotnet_guest.retirement import IDENTITY, PACKAGE
        values = ExactCompositionTests().fixture(root)
        compiler, paths, evidence, component, coverage, calls, protected = values
        names = ("native-aot-raw.wit.json", "closed-runtime-adapter.wit.json",
                 "additional-runtime-entropy.wit.json")
        graphs = [json.loads((evidence / name).read_bytes()) for name in names]
        for observed, direction, enabled, changed in ((graphs[0], "imports", consumer, consumer_change),
                (graphs[1], "exports", primary, provider_change), (graphs[2], "exports", extra, None)):
            if not enabled:
                continue
            function = {"name": "drain", "kind": "async-freestanding", "params": []}
            function.update(changed or {})
            index = len(observed["interfaces"])
            observed["interfaces"].append({"name": "owner", "package": len(observed["packages"]),
                "functions": {"drain": function}, "types": {}})
            observed["packages"].append({"name": PACKAGE})
            observed["worlds"][0][direction]["retirement"] = {"interface": {"id": index}}
        for name, observed in zip(names, graphs):
            (evidence / name).write_bytes(json.dumps(observed).encode())
        coverage["rawWitDigest"] = digest((evidence / names[0]).read_bytes())
        coverage["runtimeWitDigest"] = digest((evidence / names[1]).read_bytes())
        coverage["additionalAdapters"][0]["witDigest"] = digest((evidence / names[2]).read_bytes())
        if selected:
            coverage["compilerPrivateImports"] = [IDENTITY]
        return (*values, graphs)

    def test_selected_private_owner_has_one_primary_edge_and_no_new_host_authority(self):
        from tools.dotnet_guest.retirement import IDENTITY
        with tempfile.TemporaryDirectory() as temporary:
            compiler, paths, evidence, component, coverage, calls, _protected, _graphs = self.fixture(Path(temporary))
            result = compose_exact(compiler, paths["raw"], component, coverage,
                additional_adapters=[("entropy", paths["entropy"])], owned_retirement=True)
            source = (evidence / "runtime-composition.wac").read_bytes()
            self.assertEqual(source.count((json.dumps(IDENTITY) + ": runtime0").encode()), 1)
            self.assertEqual([row for row in result["edges"] if row["interface"] == IDENTITY],
                [{"interface": IDENTITY, "adapter": "primary"}])
            self.assertEqual(result["unmodifiedHostImports"], [CLOCK])
            self.assertNotIn((json.dumps(CLOCK) + ":").encode(), source)
            self.assertEqual(len(calls), 1)

    def test_private_port_requires_selected_compiler_profile_and_exact_primary_provider(self):
        for changed in ({"selected": False}, {"consumer": False}, {"primary": False},
                        {"primary": False, "extra": True}, {"extra": True}):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(
                    Path(temporary), **changed)
                with self.assertRaisesRegex(ValueError, "retirement-composition-profile-or-edge|duplicate-export"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                        additional_adapters=[("entropy", paths["entropy"])],
                        owned_retirement=changed.get("selected", True))
                self.assertEqual(calls, [])
                self.assertFalse(component.exists())

    def test_sync_parameter_result_or_renamed_private_drain_is_rejected_on_either_side(self):
        for side in ("consumer_change", "provider_change"):
            for changed in ({"kind": "freestanding"}, {"params": [{"name": "value", "type": "u32"}]},
                            {"result": "u32"}, {"name": "different"}):
                with self.subTest(side=side, changed=changed), tempfile.TemporaryDirectory() as temporary:
                    compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(
                        Path(temporary), **{side: changed})
                    with self.assertRaisesRegex(ValueError, "private-import-shape|private-export-shape"):
                        compose_exact(compiler, paths["raw"], component, coverage,
                            additional_adapters=[("entropy", paths["entropy"])], owned_retirement=True)
                    self.assertEqual(calls, [])

    def test_private_port_receipt_cannot_enable_or_hide_an_unselected_edge(self):
        from tools.dotnet_guest.retirement import IDENTITY
        for selected, marker in ((True, []), (True, [IDENTITY, CLOCK]), (False, [IDENTITY])):
            with self.subTest(selected=selected, marker=marker), tempfile.TemporaryDirectory() as temporary:
                compiler, paths, _evidence, component, coverage, calls, _protected, _graphs = self.fixture(
                    Path(temporary), selected=selected, consumer=selected, primary=selected)
                coverage["compilerPrivateImports"] = marker
                with self.assertRaisesRegex(ValueError, "retirement-composition-receipt"):
                    compose_exact(compiler, paths["raw"], component, coverage,
                        additional_adapters=[("entropy", paths["entropy"])], owned_retirement=selected)
                self.assertEqual(calls, [])

    def test_member_coverage_checks_the_private_consumer_and_primary_signature(self):
        from tools.dotnet_guest.compatibility import coverage as member_coverage
        from tools.dotnet_guest.retirement import IDENTITY
        with tempfile.TemporaryDirectory() as temporary:
            *_values, graphs = self.fixture(Path(temporary))
            raw, primary, extra = graphs
            result = member_coverage(raw, primary, additional_adapters=[extra],
                additional_names=["entropy"], owned_retirement=True)
            self.assertEqual(result["gaps"], [])
            self.assertEqual(result["compilerPrivateImports"], [IDENTITY])
            with self.assertRaisesRegex(ValueError, "retirement-composition-profile-or-edge"):
                member_coverage(raw, primary, additional_adapters=[extra], additional_names=["entropy"])
            primary["interfaces"][-1]["functions"]["drain"]["kind"] = "freestanding"
            with self.assertRaisesRegex(ValueError, "private-export-shape"):
                member_coverage(raw, primary, additional_adapters=[extra],
                    additional_names=["entropy"], owned_retirement=True)

    def test_unselected_composition_source_and_host_edges_are_byte_identical(self):
        sources, imports = [], []
        with tempfile.TemporaryDirectory() as temporary:
            for ordinal, keywords in enumerate(({}, {"owned_retirement": False})):
                root = Path(temporary) / str(ordinal)
                root.mkdir()
                compiler, paths, evidence, component, coverage, _calls, _protected = ExactCompositionTests().fixture(root)
                result = compose_exact(compiler, paths["raw"], component, coverage,
                    additional_adapters=[("entropy", paths["entropy"])], **keywords)
                sources.append((evidence / "runtime-composition.wac").read_bytes())
                imports.append(result["unmodifiedHostImports"])
        self.assertEqual(sources[0], sources[1])
        self.assertNotIn(b"dotnet-retirement", sources[0])
        self.assertEqual(imports, [[CLOCK], [CLOCK]])


if __name__ == "__main__":
    unittest.main()
