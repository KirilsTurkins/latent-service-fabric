from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import validate
from tools.security_common import SecurityError


class SelectedGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.artifacts = self.root / "artifacts"
        self.packages = self.root / "packages"
        self.archive = b"controlled-package-fixture"
        self.archive_hash = base64.b64encode(hashlib.sha512(self.archive).digest()).decode()
        location = self.packages / "fixture/1.2.3"
        location.mkdir(parents=True)
        (location / "fixture.1.2.3.nupkg").write_bytes(self.archive)
        (location / "fixture.1.2.3.nupkg.sha512").write_text(self.archive_hash)
        self.write(location / ".nupkg.metadata", {"contentHash": "reviewed-content-hash", "source": "https://api.nuget.org/v3/index.json"})
        for project in validate.LOCKED:
            self.write(self.source / "sdk/dotnet" / project / "packages.lock.json", {"dependencies": {"net8.0": {
                "Fixture": {"type": "Direct", "resolved": "1.2.3", "contentHash": "reviewed-content-hash"}, "Models": {"type": "Project"}}}})
            self.write(self.artifacts / "obj" / project / "project.assets.json", {
                "targets": {"net8.0": {"Fixture/1.2.3": {"type": "package"}, "Models/1.0.0": {"type": "project"}}},
                "libraries": {"Fixture/1.2.3": {"path": "fixture/1.2.3", "sha512": "reviewed-content-hash"}, "Models/1.0.0": {"type": "project"}},
                "project": {"restore": {"sources": {"https://api.nuget.org/v3/index.json": {}}, "restoreLockProperties": {"restoreLockedMode": True},
                                         "configFilePaths": [str(self.source / "sdk/dotnet/nuget.transport.config")]}}})

    @staticmethod
    def write(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def graph(self) -> list[dict]:
        return validate.package_graph(self.source, self.artifacts, self.packages)

    def test_exact_assets_graph_and_archive_hash_match_each_lock(self) -> None:
        graph = self.graph()
        self.assertEqual(len(graph), 3)
        self.assertEqual({item["version"] for item in graph}, {"1.2.3"})
        self.assertEqual({item["archiveSha512"] for item in graph}, {self.archive_hash})
        self.assertNotEqual(graph[0]["archiveSha512"], graph[0]["contentHash"])

    def test_omitted_additional_or_case_duplicate_selected_edges_fail(self) -> None:
        path = self.artifacts / "obj" / validate.LOCKED[0] / "project.assets.json"
        original = path.read_text()
        for kind in ("missing", "extra", "case", "edge", "library"):
            value = json.loads(original)
            selected = value["targets"]["net8.0"]
            if kind == "missing":
                del selected["Fixture/1.2.3"]
            elif kind == "extra":
                selected["Hidden/2.0.0"] = {"type": "package"}
            elif kind == "case":
                selected["fixture/1.2.3"] = selected["Fixture/1.2.3"]
            elif kind == "edge":
                selected["Fixture/1.2.3"]["dependencies"] = {"Hidden": "2.0.0"}
            else:
                value["libraries"]["Hidden/2.0.0"] = {"type": "package"}
            self.write(path, value)
            with self.subTest(kind=kind), self.assertRaises(SecurityError):
                self.graph()

    def test_restore_source_lock_mode_version_and_content_cannot_drift(self) -> None:
        path = self.artifacts / "obj" / validate.LOCKED[0] / "project.assets.json"
        original = path.read_text()
        for kind in ("source", "mode", "config", "version", "content"):
            value = json.loads(original)
            restore = value["project"]["restore"]
            if kind == "source":
                restore["sources"]["https://unreviewed.invalid"] = {}
            elif kind == "mode":
                restore["restoreLockProperties"]["restoreLockedMode"] = False
            elif kind == "config":
                restore["configFilePaths"].append("unreviewed.config")
            elif kind == "version":
                value["targets"]["net8.0"]["Fixture/2.0.0"] = value["targets"]["net8.0"].pop("Fixture/1.2.3")
            else:
                value["libraries"]["Fixture/1.2.3"]["sha512"] = "changed"
            self.write(path, value)
            with self.subTest(kind=kind), self.assertRaises(SecurityError):
                self.graph()

    def test_modified_archive_is_not_mistaken_for_nuget_content_identity(self) -> None:
        (self.packages / "fixture/1.2.3/fixture.1.2.3.nupkg").write_bytes(b"changed")
        with self.assertRaisesRegex(SecurityError, "dotnet-archive-hash-drift"):
            self.graph()


if __name__ == "__main__":
    unittest.main()
