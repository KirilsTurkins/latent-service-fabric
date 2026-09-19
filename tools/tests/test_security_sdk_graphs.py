from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.security_advisories import query_osv, rustsec
from tools.security_common import SecurityError, digest
from tools.security_inventory import Package, cargo_inventory, is_manifest
from tools.security_sdk_graphs import c_packages, go_packages, legacy_c_tree, legacy_manifest, maven_packages, nuget_packages


class SdkGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path: str, value: str | dict) -> None:
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(value) if isinstance(value, dict) else value, encoding="utf-8")

    def go_fixture(self, extra: str = "") -> tuple[dict, dict]:
        manifest = "module fixture.dev/sdk\n\ngo 1.27.1\nrequire fixture.dev/protocol v1.2.3\n" + extra
        checksum = "h1:" + "A" * 43 + "="
        sums = f"fixture.dev/protocol v1.2.3 {checksum}\nfixture.dev/protocol v1.2.3/go.mod {checksum}\n"
        lock = {"schemaVersion": 1, "module": "fixture.dev/sdk", "goVersion": "1.27.1",
                "manifestSha256": digest(manifest.encode()), "sumSha256": digest(sums.encode()),
                "modules": [{"path": "fixture.dev/protocol", "version": "v1.2.3", "sum": checksum, "goModSum": checksum}], "tools": []}
        self.write("go.mod", manifest)
        self.write("go.sum", sums)
        self.write("dependencies.lock.json", lock)
        return {"path": "go.mod", "lock": "dependencies.lock.json", "sum": "go.sum", "module": "fixture.dev/sdk", "kind": "go-locked"}, lock

    def maven_fixture(self) -> tuple[dict, dict]:
        self.write("build.gradle.kts", "reviewed fixture build data\n")
        lock = {"schemaVersion": 1, "maven": "https://repo.maven.apache.org/maven2/", "artifacts": [
            {"path": "dev/fixture/protocol/1.2.3/protocol-1.2.3.jar", "sha256": "a" * 64, "size": 64, "platform": "any"},
            {"path": "dev/fixture/generator/1.2.3/generator-1.2.3-linux-x86_64.exe", "sha256": "b" * 64, "size": 128, "platform": "linux-x86_64"}]}
        self.write("dependencies.lock.json", lock)
        return {"path": "build.gradle.kts", "lock": "dependencies.lock.json",
                "manifest_sha256": digest(b"reviewed fixture build data\n")}, lock

    def nuget_fixture(self) -> tuple[dict, dict]:
        self.write("Client.csproj", '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net8.0</TargetFramework>'
                   '</PropertyGroup><ItemGroup><PackageReference Include="Fixture.Protocol" Version="1.2.3" />'
                   '<ProjectReference Include="../Models/Models.csproj" /></ItemGroup></Project>')
        checksum = "A" * 86 + "=="
        lock = {"version": 1, "dependencies": {"net8.0": {
            "Fixture.Protocol": {"type": "Direct", "resolved": "1.2.3", "contentHash": checksum,
                                 "dependencies": {"Fixture.Codec": "2.3.4"}},
            "Fixture.Codec": {"type": "Transitive", "resolved": "2.3.4", "contentHash": checksum},
            "models": {"type": "Project"}}}}
        self.write("packages.lock.json", lock)
        return {"path": "Client.csproj", "lock": "packages.lock.json"}, lock

    def c_fixture(self) -> dict:
        lock = {}
        for name, repository, version in (("nghttp2", "nghttp2/nghttp2", "1.70.0"),
                                           ("nanopb", "nanopb/nanopb", "0.4.9.2"),
                                           ("protoc", "protocolbuffers/protobuf", "36.2")):
            commit = "b" * 40
            reference = commit if name == "nanopb" else "v" + version
            filename = "nghttp2-" + version + ".tar.gz" if name == "nghttp2" else "protoc-" + version + "-linux-x86_64.zip"
            url = "https://codeload.github.com/" + repository + "/tar.gz/" + commit if name == "nanopb" else "https://github.com/" + repository + "/releases/download/" + reference + "/" + filename
            lock[name] = {"version": version, "commit": commit, "sha256": "a" * 64, "role": "runtime",
                          "purl": "pkg:github/" + repository + "@" + reference, "url": url}
        lock["nghttp2"]["bundled"] = [{"name": "sfparse", "version": "c" * 40, "commit": "c" * 40,
            "role": "bundled-runtime", "purl": "pkg:github/ngtcp2/sfparse@" + "c" * 40,
            "url": "https://github.com/ngtcp2/sfparse/tree/" + "c" * 40,
            "files": {"lib/sfparse.c": "d" * 64, "lib/sfparse.h": "e" * 64}}]
        for name in ("protobuf", "h2", "hpack", "hyperframe"):
            lock[name] = {"version": "1.2.3", "sha256": "a" * 64, "role": "test-only", "purl": "pkg:pypi/" + name + "@1.2.3",
                          "url": "https://files.pythonhosted.org/packages/fixture/" + name + "-1.2.3-py3-none-any.whl"}
        self.write("dependencies.lock.json", lock)
        return lock

    def test_data_only_readers_cover_modules_generators_transitive_and_native_sources(self) -> None:
        with patch("tools.security_common.run", side_effect=AssertionError("no subprocess in graph readers")):
            entry, _ = self.go_fixture()
            self.assertEqual(set(go_packages(self.root, entry)), {("Go", "fixture.dev/protocol", "v1.2.3"), ("Go", "stdlib", "1.27.1")})
            entry, _ = self.maven_fixture()
            self.assertEqual(set(maven_packages(self.root, entry)), {("Maven", "dev.fixture:protocol", "1.2.3"), ("Maven", "dev.fixture:generator", "1.2.3")})
            entry, _ = self.nuget_fixture()
            self.assertEqual(set(nuget_packages(self.root, entry)), {("NuGet", "Fixture.Protocol", "1.2.3"), ("NuGet", "Fixture.Codec", "2.3.4")})
            self.c_fixture()
            self.assertEqual(len(c_packages(self.root, "dependencies.lock.json")), 8)

    def test_go_missing_checksum_changed_manifest_and_duplicate_module_fail(self) -> None:
        for failure in ("manifest", "checksum", "duplicate", "empty", "version", "value"):
            entry, lock = self.go_fixture()
            if failure == "manifest":
                self.write("go.mod", "module substituted.dev/sdk\n")
            elif failure == "checksum":
                lock["modules"][0]["sum"] = "h1:" + "B" * 43 + "="
            elif failure == "duplicate":
                lock["modules"].append(lock["modules"][0])
            elif failure == "empty":
                lock["modules"] = []
            elif failure == "version":
                lock["goVersion"] = "latest"
            else:
                lock["modules"][0]["sum"] = None
            self.write("dependencies.lock.json", lock)
            with self.subTest(failure=failure), self.assertRaises(SecurityError):
                go_packages(self.root, entry)

    def test_go_unresolved_replacement_or_missing_tool_is_not_scanned_as_safe(self) -> None:
        for directive in ("replace fixture.dev/protocol => ../unreviewed\n", "require missing.dev/protocol v2.0.0\n",
                          "exclude fixture.dev/protocol v1.2.3\n", "tool missing.dev/generator\n", "require (\n"):
            entry, _ = self.go_fixture(directive)
            with self.subTest(directive=directive), self.assertRaises(SecurityError):
                go_packages(self.root, entry)

    def test_go_exact_legacy_exception_cannot_hide_new_lock_or_sum(self) -> None:
        entry, _ = self.go_fixture()
        entry["legacy_sha256"] = digest((self.root / "go.mod").read_bytes().replace(b"\r\n", b"\n"))
        self.assertTrue(legacy_manifest(self.root, entry, {"go.mod"}))
        for path in ("dependencies.lock.json", "go.sum"):
            with self.subTest(path=path), self.assertRaises(SecurityError):
                legacy_manifest(self.root, entry, {"go.mod", path})

    def test_go_generator_binding_is_checked_against_selected_graph_and_manifest(self) -> None:
        entry, lock = self.go_fixture("tool fixture.dev/protocol/cmd/generator\n")
        lock["tools"] = [{"path": "fixture.dev/protocol/cmd/generator", "module": "fixture.dev/protocol", "version": "v1.2.3"}]
        self.write("dependencies.lock.json", lock)
        self.assertEqual(len(go_packages(self.root, entry)), 2)
        lock["tools"][0]["version"] = "v1.2.4"
        self.write("dependencies.lock.json", lock)
        with self.assertRaisesRegex(SecurityError, "go-tool-lock-drift"):
            go_packages(self.root, entry)

    def test_maven_changed_build_registry_path_platform_or_digest_fail(self) -> None:
        for failure in ("build", "registry", "path", "platform", "digest", "duplicate"):
            entry, lock = self.maven_fixture()
            if failure == "build":
                self.write("build.gradle.kts", "unreviewed dependency loader\n")
            elif failure == "registry":
                lock["maven"] = "https://mirror.invalid/"
            elif failure == "path":
                lock["artifacts"][0]["path"] = "../protocol.jar"
            elif failure == "platform":
                lock["artifacts"][0]["platform"] = "unreviewed"
            elif failure == "digest":
                lock["artifacts"][0]["sha256"] = "unknown"
            else:
                lock["artifacts"].append(lock["artifacts"][0])
            self.write("dependencies.lock.json", lock)
            with self.subTest(failure=failure), self.assertRaises(SecurityError):
                maven_packages(self.root, entry)

    def test_nuget_missing_transitive_changed_version_and_unreviewed_project_fail(self) -> None:
        for failure in ("edge", "version", "checksum", "framework", "project"):
            entry, lock = self.nuget_fixture()
            dependencies = lock["dependencies"]["net8.0"]
            if failure == "edge":
                del dependencies["Fixture.Codec"]
            elif failure == "version":
                dependencies["Fixture.Protocol"]["resolved"] = "1.2.4"
            elif failure == "checksum":
                dependencies["Fixture.Codec"]["contentHash"] = "unknown"
            elif failure == "framework":
                lock["dependencies"]["net9.0"] = dependencies
                del lock["dependencies"]["net8.0"]
            else:
                dependencies["unreviewed"] = {"type": "Project"}
            self.write("packages.lock.json", lock)
            with self.subTest(failure=failure), self.assertRaises(SecurityError):
                nuget_packages(self.root, entry)

    def test_nuget_entities_and_hidden_dependency_loading_fail_without_execution(self) -> None:
        entry, _ = self.nuget_fixture()
        for content in ('<!DOCTYPE Project><Project />', '<Project Sdk="Microsoft.NET.Sdk"><Import Project="other.props" /></Project>',
                        '<Project Sdk="Microsoft.NET.Sdk"><PackageDownload Include="hidden" /></Project>'):
            self.write("Client.csproj", content)
            with self.subTest(content=content), self.assertRaises(SecurityError):
                nuget_packages(self.root, entry)

    def test_c_unknown_dependency_url_or_source_commit_fails(self) -> None:
        for failure in ("extra", "url", "commit", "purl", "digest"):
            lock = self.c_fixture()
            if failure == "extra":
                lock["unreviewed"] = lock["nghttp2"]
            elif failure == "url":
                lock["h2"]["url"] = "https://mirror.invalid/h2-1.2.3.whl"
            elif failure == "commit":
                lock["nghttp2"]["commit"] = "main"
            elif failure == "purl":
                lock["protoc"]["purl"] = "pkg:github/protocolbuffers/protobuf@main"
            else:
                lock["nanopb"]["sha256"] = "unknown"
            self.write("dependencies.lock.json", lock)
            with self.subTest(failure=failure), self.assertRaises(SecurityError):
                c_packages(self.root, "dependencies.lock.json")

    def test_c_legacy_interface_allowance_is_bound_to_every_tree_byte(self) -> None:
        self.write("sdk/c/interface.h", "int fixture(void);\n")
        identities = [["sdk/c/interface.h", digest(b"int fixture(void);\n")]]
        entry = {"path": "sdk/c/dependencies.lock.json", "legacy_tree_sha256": [digest(json.dumps(identities, separators=(",", ":")).encode())]}
        self.assertTrue(legacy_c_tree(self.root, entry, {"sdk/c/interface.h"}))
        self.write("sdk/c/interface.h", "int changed(void);\n")
        with self.assertRaisesRegex(SecurityError, "unreviewed-legacy-c-tree"):
            legacy_c_tree(self.root, entry, {"sdk/c/interface.h"})
        self.assertFalse(legacy_c_tree(self.root, entry, {entry["path"]}))

    def test_c_bundled_runtime_cannot_disappear_or_hide_unreviewed_sources(self) -> None:
        for failure in ("missing", "empty", "duplicate", "name", "role", "commit", "url", "file", "digest"):
            lock = self.c_fixture()
            bundled = lock["nghttp2"]["bundled"]
            if failure == "missing":
                del lock["nghttp2"]["bundled"]
            elif failure == "empty":
                bundled.clear()
            elif failure == "duplicate":
                bundled.append(dict(bundled[0]))
            elif failure in ("name", "role", "commit", "url"):
                bundled[0][failure] = "unreviewed"
            elif failure == "file":
                bundled[0]["files"]["lib/unreviewed.c"] = "a" * 64
            else:
                bundled[0]["files"]["lib/sfparse.c"] = "unknown"
            self.write("dependencies.lock.json", lock)
            with self.subTest(failure=failure), self.assertRaises(SecurityError):
                c_packages(self.root, "dependencies.lock.json")

    def test_source_commits_use_osv_commit_queries_and_keep_attribution(self) -> None:
        package = Package("GIT", "https://github.com/fixture/source", "a" * 40, "sdk/c/dependencies.lock.json")
        requests = []
        def transport(payload: bytes) -> tuple[bytes, str]:
            requests.append(json.loads(payload))
            return b'{"results":[{"vulns":[{"id":"OSV-fixture-only","modified":"2026-09-19T00:00:00Z"}]}]}', format_datetime(datetime.now(timezone.utc), usegmt=True)
        findings, receipts = query_osv([package], transport)
        self.assertEqual(requests, [{"queries": [{"commit": "a" * 40}]}])
        self.assertEqual(findings[0].path, "sdk/c/dependencies.lock.json")
        self.assertEqual(receipts[0]["packages"], 1)

    def test_custom_resolved_graph_and_nuget_sources_select_dependency_scan(self) -> None:
        for path in ("sdk/go/dependencies.lock.json", "sdk/java-client/dependencies.lock.json", "sdk/c/dependencies.lock.json",
                     "sdk/dotnet/nuget.transport.config", "website/package-lock.json"):
            with self.subTest(path=path):
                self.assertTrue(is_manifest(path))

    def test_isolated_rust_fixture_requires_reviewed_manifest_and_its_own_lock(self) -> None:
        manifest = '[package]\nname="fixture"\nversion="0.0.0"\n[workspace]\n'
        lock = 'version=4\n[[package]]\nname="fixture"\nversion="0.0.0"\n'
        self.write("tools/fixture/Cargo.toml", manifest)
        self.write("tools/fixture/Cargo.lock", lock)
        entry = {"path": "tools/fixture/Cargo.toml", "lock": "tools/fixture/Cargo.lock",
                 "isolated": True, "manifest_sha256": digest(manifest.encode())}
        covered, record = cargo_inventory(self.root, entry)
        self.assertEqual(covered, {entry["path"], entry["lock"]})
        self.assertEqual(record["packages"], 1)
        self.assertEqual(record["coverage"], "RustSec")
        self.write(entry["path"], manifest + '[dependencies]\nunreviewed="1"\n')
        with self.assertRaisesRegex(SecurityError, "unreviewed-isolated-cargo-manifest"):
            cargo_inventory(self.root, entry)

    def test_rustsec_audits_every_tracked_lock_without_hiding_fixture_findings(self) -> None:
        paths = ["Cargo.lock", "tools/fixture/Cargo.lock"]
        for path in paths:
            self.write(path, 'version=4\n[[package]]\nname="fixture"\nversion="0.0.0"\n')
        observed = []
        def audit(payload, path, binary, database, identity, scratch):
            observed.append(path)
            return (["fixture-finding"] if path != "Cargo.lock" else []), {"lock_sha256": digest(payload), "packages": 1}
        with patch("tools.security_advisories.tracked_paths", return_value=[*paths, "docs/Cargo.lock.fixture"]), \
             patch("tools.security_advisories.verify_tool", return_value=self.root / "cargo-audit"), \
             patch("tools.security_advisories.fetch_rustsec", return_value=(self.root / "database", {"commit": "a" * 40})), \
             patch("tools.security_advisories.audit_lock", side_effect=audit):
            findings, receipt = rustsec(self.root, self.root, self.root)
        self.assertEqual(observed, paths)
        self.assertEqual(findings, ["fixture-finding"])
        self.assertEqual([row["path"] for row in receipt["locks"]], paths)
        with patch("tools.security_advisories.tracked_paths", return_value=[paths[1]]):
            with self.assertRaisesRegex(SecurityError, "missing-or-excessive-rust-lockfiles"):
                rustsec(self.root, self.root, self.root)


if __name__ == "__main__":
    unittest.main()
