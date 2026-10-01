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


if __name__ == "__main__":
    unittest.main()
