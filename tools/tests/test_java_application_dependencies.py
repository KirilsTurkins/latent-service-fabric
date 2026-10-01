"""Captured JAR selection and executable-input denial; no runtime qualification claim."""
from pathlib import Path
import struct
import tempfile
import unittest

from tools.application_dependencies import MANIFEST, LOCK, capture, prepare
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest
from tools.java_application_dependencies import classpath, deterministic_jar, selected_entries
from tools.java_dependency_resolution import declarations, script


def class_bytes(version=69):
    return b"\xca\xfe\xba\xbe" + struct.pack(">HH", 0, version) + b"bounded-bytecode-header-control"


class JavaDependencies(unittest.TestCase):
    def prepare(self, libraries):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        root = Path(owned.name)
        project, work, output = (root / name for name in ("project", "work", "output"))
        project.mkdir(); work.mkdir(); output.mkdir()
        artifacts = []
        for index, (name, entries, edges) in enumerate(libraries):
            path = root / (name + ".jar")
            path.write_bytes(deterministic_jar(entries))
            artifacts.append({"id": name, "role": "application", "format": "file", "mount": f"dependencies/java/{index}.jar",
                "source": {"path": "../" + path.name}, "dependencies": edges, "metadata": {"ecosystem": "maven"}})
        (project / MANIFEST).write_bytes(canonical({"formatVersion": 1, "language": "java", "selection": {"release": 25},
            "nativeLocks": [], "artifacts": artifacts, "transformations": []}))
        (project / LOCK).write_bytes(canonical(capture(project)))
        return root, prepare(project, work, output, "java")

    def test_local_unknown_transitive_jars_and_resource_bytes_preserved_offline(self):
        root, closure = self.prepare([
            ("outside-primary", {"external/Pure.class": class_bytes(), "data/example.txt": b"snowman \xe2\x98\x83"}, ["outside-transitive"]),
            ("outside-transitive", {"external/Helper.class": class_bytes()}, []),
        ])
        jars, receipt = classpath(closure, root / "classpath")
        self.assertEqual(len(jars), 2)
        self.assertEqual(selected_entries(jars[0].read_bytes(), 25)["data/example.txt"], b"snowman \xe2\x98\x83")
        self.assertEqual(receipt["resources"][0]["owner"], "outside-primary")
        self.assertEqual(receipt["resources"][0]["digest"], digest(b"snowman \xe2\x98\x83"))
        self.assertEqual(receipt["artifacts"][1]["selection"]["classpathOrder"], 1)
        closure.check_unchanged()

    def test_duplicate_class_and_duplicate_resource_are_rejected(self):
        for name, content in (("org/external/Pure.class", class_bytes()), ("data/resource.txt", b"same")):
            with self.subTest(name=name):
                root, closure = self.prepare([("one", {name: content}, []), ("two", {name: content}, [])])
                with self.assertRaisesRegex(DependencyError, "duplicate"):
                    classpath(closure, root / "classpath")

    def test_multi_release_highest_qualified_release_with_original_identity(self):
        jar = deterministic_jar({"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\r\nMulti-Release: true\r\n",
            "org/example/Pure.class": class_bytes(52), "META-INF/versions/21/org/example/Pure.class": class_bytes(65),
            "META-INF/versions/25/org/example/Pure.class": class_bytes(69),
            "META-INF/versions/26/org/example/Pure.class": class_bytes(70)})
        selected = selected_entries(jar, 25)
        self.assertEqual(selected["org/example/Pure.class"], class_bytes(69))
        self.assertFalse(any(name.startswith("META-INF/versions/") for name in selected))
        self.assertNotEqual(digest(jar), digest(deterministic_jar(selected)))

    def test_malformed_multirelease_and_new_bytecode_fail(self):
        with self.assertRaisesRegex(DependencyError, "manifest-required"):
            selected_entries(deterministic_jar({"META-INF/versions/21/org/example/Pure.class": class_bytes()}), 25)
        with self.assertRaisesRegex(DependencyError, "newer"):
            selected_entries(deterministic_jar({"org/example/Pure.class": class_bytes(70)}), 25)

    def test_shaded_names_preserved_and_platform_override_denied(self):
        self.assertIn("relocated/example/Pure.class", selected_entries(deterministic_jar({"relocated/example/Pure.class": class_bytes()}), 25))
        for prefix in ("java/", "dev/latent/guest/", "dev/latent/generated/", "org/teavm/interop/"):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(DependencyError, "overrides-platform"):
                selected_entries(deterministic_jar({prefix + "Pure.class": class_bytes()}), 25)

    def test_service_provider_metadata_preserved_and_duplicate_policy_explicit(self):
        root, closure = self.prepare([("providers", {"META-INF/services/org.example.Service": b"org.example.Pure\n# comment\n",
                                                       "org/example/Pure.class": class_bytes()}, [])])
        jars, receipt = classpath(closure, root / "classpath")
        self.assertEqual(receipt["serviceProviders"], "preserved-no-host-initialization")
        self.assertIn("META-INF/services/org.example.Service", selected_entries(jars[0].read_bytes(), 25))

    def test_resolver_owns_script_and_retains_native_conditions(self):
        value = {"formatVersion": 1, "dependencies": [{"group": "external", "name": "pure", "version": "1.2.3",
            "scope": "runtime", "exclusions": [{"group": "unwanted", "name": "tool"}]}], "localJars": [],
            "repositories": [{"id": "private", "url": "https://packages.example.org/maven"}],
            "selection": {"release": 25, "runtimeProfile": "java-teavm-c"}}
        declarations(value)
        generated = script(value)
        self.assertIn("failOnDynamicVersions", generated)
        self.assertIn("resolutionResult.allComponents", generated)
        self.assertIn("component.variants", generated)
        self.assertNotIn("apply plugin", generated)
        value["dependencies"][0]["version"] = "1.0-SNAPSHOT"
        with self.assertRaisesRegex(DependencyError, "coordinate"):
            declarations(value)

    def test_private_repository_credentials_cannot_enter_declarations(self):
        value = {"formatVersion": 1, "dependencies": [], "localJars": [],
            "repositories": [{"id": "private", "url": "https://user:password@packages.example.org/maven"}], "selection": {}}
        with self.assertRaisesRegex(DependencyError, "credentials"):
            declarations(value)

    def test_teavm_host_extension_services_cannot_execute_as_guest_inputs(self):
        jar = deterministic_jar({"META-INF/services/org.teavm.vm.spi.TeaVMPlugin": b"external.UnreviewedPlugin\n"})
        with self.assertRaisesRegex(DependencyError, "compiler-provider"):
            selected_entries(jar, 25)


class JavaResourceArtifacts(unittest.TestCase):
    def prepare_resources(self, libraries, *, change=None, capture_entries=True):
        from tools.application_dependency_store import Store
        from tools.java_resource_artifacts import capture_resources
        from tools.rust_capsule_project import snapshot
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        root = Path(owned.name)
        project, work, output = (root / name for name in ("project", "work", "output"))
        project.mkdir(); work.mkdir(); output.mkdir()
        store = Store(project / "dependency-inputs/objects")
        parents, original_paths = [], []
        for index, (identity, entries, edges) in enumerate(libraries):
            path = root / (str(index) + "-outside-original.jar")
            path.write_bytes(deterministic_jar(entries))
            captured = store.put(path.read_bytes())
            original_paths.append(path)
            parents.append({"id": identity, "role": "application", "format": "file",
                "mount": f"dependencies/java/{index:04d}.jar", "dependencies": edges,
                "source": {"path": store.path(captured["digest"]).relative_to(project).as_posix()},
                "metadata": {"ecosystem": "captured-local-jar"}})
        artifacts = capture_resources(project, store, parents) if capture_entries else parents
        if change is not None:
            change(artifacts)
        declaration = {"formatVersion": 1, "language": "java", "selection": {"release": 25},
            "nativeLocks": [], "artifacts": artifacts, "transformations": []}
        (project / MANIFEST).write_bytes(canonical(declaration))
        (project / LOCK).write_bytes(canonical(capture(project)))
        for path in original_paths:
            path.unlink()
        closure = prepare(project, work, output, "java")
        return root, closure, snapshot(project)

    def selected(self, libraries, **kwargs):
        from tools.java_resource_artifacts import packaged_resources
        root, closure, files = self.prepare_resources(libraries, **kwargs)
        jars, receipt = classpath(closure, root / "classpath")
        rows, sources = packaged_resources(closure, receipt, files)
        return root, closure, {**files, **sources}, jars, receipt, rows

    def test_unknown_transitive_resource_children_survive_original_input_removal(self):
        from tools import guest_resources
        root, closure, files, jars, receipt, rows = self.selected([
            ("outside:developer-primary:8.4", {"outside/Main.class": class_bytes(),
                                              "data/main.bin": b"\0\xffopaque"}, ["private:transitive:1.0"]),
            ("private:transitive:1.0", {"outside/Helper.class": class_bytes(),
                                        "data/snowman.txt": "snowman \u2603\n".encode()}, []),
        ])
        self.assertFalse(list(root.glob("*-outside-original.jar")))
        self.assertEqual(len(jars), 2)
        self.assertEqual(len(rows), 2)
        by_id = {item["id"]: item for item in closure.lock["artifacts"]}
        self.assertIn("private:transitive:1.0", by_id["outside:developer-primary:8.4"]["dependencies"])
        for row in rows:
            child = by_id[row["owner"]]
            self.assertEqual(child["role"], "resource")
            self.assertEqual(child["files"][0]["digest"], digest(files[row["source"]]))
            self.assertIn(child["id"], by_id[child["metadata"]["jar"]]["dependencies"])
            self.assertNotEqual(row["digest"], by_id[child["metadata"]["jar"]]["original"]["digest"])
        packaged = guest_resources.capture(files, b"component package control", b"captured source",
                                           additional_resources=rows)
        self.assertEqual(packaged.index["count"], 2)
        self.assertEqual(packaged.index["runtimeLookup"], "language-profile-qualification-required")
        self.assertEqual({item["owner"] for item in packaged.index["resources"]}, {row["owner"] for row in rows})
        self.assertEqual([item["owner"] for item in receipt["resources"]],
                         ["outside:developer-primary:8.4", "private:transitive:1.0"])
        closure.check_unchanged()

    def test_multi_release_resource_binds_original_zip_entry_and_selected_version(self):
        entries = {"META-INF/MANIFEST.MF": b"Manifest-Version: 1.0\r\nMulti-Release: true\r\n",
            "data/version.txt": b"base", "META-INF/versions/21/data/version.txt": b"java21",
            "META-INF/versions/25/data/version.txt": b"java25",
            "META-INF/versions/26/data/version.txt": b"java26 unselected",
            "META-INF/LICENSE.txt": b"per-JAR legal metadata stays in original", "META-INF/VENDOR.SF": b"signature"}
        _root, closure, files, jars, receipt, rows = self.selected([("outside:multi-release:1.0", entries, [])])
        self.assertEqual(len(rows), 1)
        self.assertEqual(files[rows[0]["source"]], b"java25")
        child = next(item for item in closure.lock["artifacts"] if item["role"] == "resource")
        self.assertEqual(child["metadata"]["originalEntry"], "META-INF/versions/25/data/version.txt")
        self.assertEqual(child["metadata"]["selectedVersion"], 25)
        self.assertEqual(child["metadata"]["release"], 25)
        self.assertEqual(child["metadata"]["originalJarDigest"], receipt["artifacts"][0]["originalDigest"])
        self.assertEqual(selected_entries(jars[0].read_bytes(), 25)["data/version.txt"], b"java25")
        self.assertIn("META-INF/LICENSE.txt", selected_entries(jars[0].read_bytes(), 25))

    def test_package_owner_cannot_be_forged_from_whole_jar_identity(self):
        from tools import guest_resources
        _root, _closure, files, _jars, _receipt, rows = self.selected([
            ("outside:whole-jar:1.0", {"data/value": b"real raw resource"}, []),
        ])
        with self.assertRaisesRegex(guest_resources.ResourceError, "bytes-not-captured"):
            guest_resources.capture(files, b"component", b"source",
                additional_resources=[{**rows[0], "owner": "outside:whole-jar:1.0"}])

    def test_verified_resource_children_enter_actual_package_layers_with_source_and_lock_binding(self):
        import json
        from tools import guest_resources
        from tools.rust_capsule_build import package_inputs
        from tools.rust_capsule_project import inventory
        root, closure, files, _jars, _receipt, rows = self.selected([
            ("outside:package:1.0", {"data/hello.txt": "hello \u2603\n".encode(), "data/binary": b"\0\xff"}, []),
        ])
        files = {**files, "sdk-lock.json": canonical({"language": "java"}),
                 "vendor/lsf/Cargo.toml": b'[workspace.package]\nversion="0.1.0-alpha.5"\n'}
        output = root / "package"
        output.mkdir()
        source = inventory({name: data for name, data in files.items() if not name.startswith("dependency-inputs/")})
        (output / "source-inputs.json").write_bytes(source)
        component = b"controlled package bytes; no emitted-component qualification claim"
        project = {"name": "java-resource-fixture", "tenant": "examples", "service": "examples/java-resource-fixture",
                   "world": "examples:resource-fixture/service@1.0.0", "version": "1.0.0", "limits": {}}
        package_inputs(output, project, {"imports": [], "exports": []}, files, component, additional_resources=rows)
        package = json.loads((output / "package-source.json").read_bytes())
        layers = {item["path"]: item for item in package["layers"]}
        self.assertEqual(layers[guest_resources.INDEX]["role"], "asset")
        self.assertEqual(layers["compatibility-report.json"]["role"], "asset")
        index = json.loads((output / guest_resources.INDEX).read_bytes())
        objects = {item["object"]: (output / item["object"]).read_bytes() for item in index["resources"]}
        verified = guest_resources.verify((output / guest_resources.INDEX).read_bytes(), objects,
            source_digest=digest(source), component_digest=digest(component), dependency_lock_digest=digest(closure.lock_bytes))
        self.assertEqual(verified["count"], 2)
        self.assertEqual({item["owner"] for item in verified["resources"]}, {row["owner"] for row in rows})
        self.assertEqual(set(objects.values()), {b"\0\xff", "hello \u2603\n".encode()})
        self.assertEqual(json.loads((output / "deployment.json").read_bytes())["spec"]["grants"], [])

    def test_resource_child_requires_selected_edge_role_and_exact_origin(self):
        from tools.java_resource_artifacts import packaged_resources
        changes = {
            "edge": lambda rows: rows[0]["dependencies"].clear(),
            "role": lambda rows: rows[-1].update(role="generated"),
            "origin": lambda rows: rows[-1]["metadata"].update(originalEntry="data/different"),
            "selection": lambda rows: rows[0]["metadata"]["resourceSelection"].update(release=21),
        }
        for name, change in changes.items():
            with self.subTest(name=name):
                root, closure, files = self.prepare_resources([
                    ("outside:child:1.0", {"data/value": b"child bytes"}, []),
                ], change=change)
                _jars, receipt = classpath(closure, root / "classpath")
                with self.assertRaisesRegex(DependencyError, "child|selection-drift"):
                    packaged_resources(closure, receipt, files)

    def test_staged_source_and_store_resource_byte_tamper_are_rejected(self):
        from tools.java_resource_artifacts import packaged_resources
        for location in ("source", "staged", "store"):
            with self.subTest(location=location):
                _root, closure, files, _jars, receipt, rows = self.selected([
                    ("outside:tamper:1.0", {"data/value": b"original bytes"}, []),
                ])
                row = rows[0]
                child = next(item for item in closure.lock["artifacts"] if item["id"] == row["owner"])
                if location == "source":
                    files[row["source"]] = b"changed source"
                elif location == "staged":
                    (closure.work / child["mount"]).write_bytes(b"changed staged")
                else:
                    closure.store.path(row["digest"]).write_bytes(b"changed cache")
                with self.assertRaisesRegex(DependencyError, "bytes-changed|integrity"):
                    packaged_resources(closure, receipt, files)

    def test_source_lock_receipt_and_profile_drift_cannot_package_resources(self):
        import copy
        from tools.java_resource_artifacts import packaged_resources
        _root, closure, files, _jars, receipt, _rows = self.selected([
            ("outside:bindings:1.0", {"data/value": b"bound bytes"}, []),
        ])
        with self.assertRaisesRegex(DependencyError, "source-lock-binding"):
            packaged_resources(closure, receipt, {name: value for name, value in files.items() if name != LOCK})
        for change in (
            lambda value: value["artifacts"][0].update(selectedDigest=digest(b"different selected JAR")),
            lambda value: value["resources"][0].update(owner="outside:forged:1.0"),
            lambda value: value.update(release=26),
            lambda value: value.update(release=True),
        ):
            changed = copy.deepcopy(receipt)
            change(changed)
            with self.assertRaisesRegex(DependencyError, "drift|pinned-profile"):
                packaged_resources(closure, changed, files)

    def test_legacy_whole_jar_resource_lock_requires_explicit_recapture(self):
        from tools.java_resource_artifacts import packaged_resources
        root, closure, files = self.prepare_resources([
            ("outside:legacy:1.0", {"data/value": b"old lock has no resource child"}, []),
        ], capture_entries=False)
        _jars, receipt = classpath(closure, root / "classpath")
        with self.assertRaisesRegex(DependencyError, "requires-recapture"):
            packaged_resources(closure, receipt, files)

    def test_service_metadata_stays_opaque_and_teavm_host_spi_fails_before_capture(self):
        _root, _closure, files, _jars, _receipt, rows = self.selected([
            ("outside:providers:1.0", {"META-INF/services/outside.Service": b"outside.Provider\n# comment\n"}, []),
        ])
        self.assertEqual(files[rows[0]["source"]], b"outside.Provider\n# comment\n")
        for name, payload, reason in (
            ("META-INF/services/org.teavm.vm.spi.TeaVMPlugin", b"outside.CompilerPlugin\n", "compiler-provider"),
            ("META-INF/services/outside.Service", b"outside.Bad Provider\n", "metadata-invalid"),
            ("META-INF/services/outside.Service", b"\xff", "encoding"),
        ):
            with self.subTest(name=name, reason=reason), self.assertRaisesRegex(DependencyError, reason):
                self.prepare_resources([("outside:invalid-provider:1.0", {name: payload}, [])])

    def test_resource_name_duplicates_and_finite_resource_graph_limits_fail(self):
        from unittest.mock import patch
        from tools import guest_resources, java_resource_artifacts
        for attribute, maximum, entries, reason in (
            ("MAX_COUNT", 0, {"data/value": b"a"}, "count-limit"),
            ("MAX_FILE", 1, {"data/value": b"ab"}, "byte-limit"),
            ("MAX_TOTAL", 2, {"data/one": b"ab", "data/two": b"cd"}, "byte-limit"),
        ):
            with self.subTest(attribute=attribute), patch.object(guest_resources, attribute, maximum):
                with self.assertRaisesRegex(DependencyError, reason):
                    self.prepare_resources([("outside:limited:1.0", entries, [])])
        with patch.object(java_resource_artifacts, "MAX_ARTIFACTS", 1), self.assertRaisesRegex(DependencyError, "graph-limit"):
            self.prepare_resources([("outside:limited:1.0", {"data/value": b"a"}, [])])
        with self.assertRaisesRegex(guest_resources.ResourceError, "collision"):
            self.prepare_resources([("outside:one:1.0", {"data/value": b"a"}, []),
                                    ("outside:two:1.0", {"DATA/value": b"b"}, [])])
        with self.assertRaisesRegex(DependencyError, "path-invalid"):
            self.prepare_resources([("outside:unicode:1.0", {"data/cafe\u0301": b"a"}, [])])

    def test_changing_unknown_coordinates_changes_child_attribution_without_catalogue_gate(self):
        identities = []
        for parent in ("developer:unlisted-alpha:1.0", "private:renamed-unlisted:9.7"):
            _root, closure, _files, _jars, _receipt, rows = self.selected([(parent, {"data/value": b"same bytes"}, [])])
            child = next(item for item in closure.lock["artifacts"] if item["id"] == rows[0]["owner"])
            self.assertEqual(child["metadata"]["jar"], parent)
            identities.append(child["id"])
        self.assertNotEqual(*identities)
        with self.assertRaisesRegex(DependencyError, "pinned-profile"):
            declarations({"formatVersion": 1, "dependencies": [], "localJars": [],
                "repositories": [{"id": "central", "url": "https://packages.example.org/maven"}],
                "selection": {"release": 26}})


if __name__ == "__main__":
    unittest.main()
