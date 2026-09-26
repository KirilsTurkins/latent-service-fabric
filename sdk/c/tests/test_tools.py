import importlib.util
import json
from pathlib import Path
import unittest


SDK = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("c_dependency_audit", SDK / "tools/audit_dependencies.py")
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


class DependencyGraphTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads((SDK / "dependencies.lock.json").read_text())

    def test_source_and_ecosystem_queries(self):
        queries = AUDIT.queries(self.lock)
        self.assertEqual(len(queries), 9)
        self.assertEqual({name for name, query in queries if "commit" in query},
                         {"nghttp2", "nanopb", "protoc", "sfparse"})
        self.assertEqual({name for name, query in queries if "version" in query},
                         {"nanopb", "protobuf", "h2", "hpack", "hyperframe"})
        self.assertTrue(all(query["package"]["ecosystem"] == "PyPI" for _, query in queries if "package" in query))

    def test_closed_role_labelled_graph(self):
        graph = AUDIT.graph(self.lock, "2026-09-19T00:00:00Z")
        self.assertEqual((graph["bomFormat"], graph["specVersion"]), ("CycloneDX", "1.6"))
        components = {item["bom-ref"]: item for item in graph["components"]}
        self.assertEqual(len(components), 8)
        known = set(components) | {"latent-sdk-c"}
        edges = {item["ref"]: item["dependsOn"] for item in graph["dependencies"]}
        self.assertEqual(set(edges), known)
        self.assertEqual(edges["latent-c:nghttp2"], ["latent-c:sfparse"])
        self.assertEqual(edges["latent-c:h2"], ["latent-c:hpack", "latent-c:hyperframe"])
        for children in edges.values():
            self.assertTrue(set(children) <= known)
        for entry in components.values():
            self.assertIn("latent:dependency-role", {item["name"] for item in entry["properties"]})
            self.assertTrue(entry["purl"].startswith("pkg:"))
        bundled = components["latent-c:sfparse"]
        self.assertEqual(len([item for item in bundled["properties"] if "bundled-file-sha256" in item["name"]]), 2)

    def test_duplicate_bundled_identity_rejected(self):
        self.lock["nghttp2"]["bundled"][0]["name"] = "nanopb"
        with self.assertRaises(ValueError):
            AUDIT.components(self.lock)


if __name__ == "__main__":
    unittest.main()
