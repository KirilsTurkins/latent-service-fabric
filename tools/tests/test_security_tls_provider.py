"""Renaming the bounded provider never hides upstream rustls advisories."""
import json
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import security_tls_provider as tls
from tools import security_advisories as advisories
from tools.security_common import POLICY, SecurityError, digest, tracked_paths
from tools.security_findings import finding
from tools.security_inventory import Package, inventory


class BoundedTlsAdvisoryIdentity(unittest.TestCase):
    def test_future_osv_findings_use_upstream_name_and_remain_attributed_to_the_private_manifest(self):
        package = Package("crates.io", "rustls", "0.23.46", tls.MANIFEST)

        def transport(payload):
            self.assertEqual(json.loads(payload), {"queries": [{"package": {"ecosystem": "crates.io", "name": "rustls"},
                                                                "version": "0.23.46"}]})
            return json.dumps({"results": [{"vulns": [{"id": "GHSA-future-rustls", "modified": "2099-01-01T00:00:00Z"}]}]}).encode(), format_datetime(datetime.now(timezone.utc), usegmt=True)

        findings, observations = advisories.query_osv([package], transport)
        self.assertEqual(findings, [finding("osv", "GHSA-future-rustls", tls.MANIFEST, "crates.io:rustls@0.23.46")])
        self.assertEqual(observations[0]["advisories"][0]["package"], package.public())

    def test_real_active_provider_has_upstream_osv_identity_and_complete_manifest_coverage(self):
        root = tls.bounded.ROOT
        packages, records = inventory(root)
        self.assertIn(Package("crates.io", "rustls", "0.23.46", tls.MANIFEST), packages)
        selected = [row for row in records if row["path"] == tls.MANIFEST]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["privatePackage"], "latent-rustls-outbound")
        self.assertEqual(selected[0]["buildLock"], "Cargo.lock")
        self.assertEqual(selected[0]["sourceEvidenceLock"], tls.LOCK)
        self.assertEqual(selected[0]["recordSha256"], tls.bounded.RECORD_SHA256)
        self.assertEqual(selected[0]["coverage"], "OSV-and-RustSec-authenticated-origin")

    def test_old_policy_is_red_and_no_generic_vendor_manifest_exclusion_is_added(self):
        with tempfile.TemporaryDirectory() as temporary:
            policy = Path(temporary)
            data = json.loads((POLICY / "inventory.json").read_bytes())
            rows = [row for row in data["manifests"] if row["kind"] == "bounded-rustls"]
            self.assertEqual(len(rows), 1)
            data["manifests"].remove(rows[0])
            (policy / "inventory.json").write_bytes(json.dumps(data).encode())
            shutil.copyfile(POLICY / "requirements.txt", policy / "requirements.txt")
            with self.assertRaisesRegex(SecurityError, "unreviewed-or-missing-dependency-manifest"):
                inventory(tls.bounded.ROOT, policy)
            paths = tracked_paths(tls.bounded.ROOT)
            with patch("tools.security_inventory.tracked_paths", return_value=[*paths, "crates/vendor/unknown/Cargo.toml"]), \
                    self.assertRaisesRegex(SecurityError, "unreviewed-or-missing-dependency-manifest"):
                inventory(tls.bounded.ROOT)

    def test_rustsec_keeps_all_real_locks_and_reports_a_future_upstream_advisory_for_the_fork(self):
        root = tls.bounded.ROOT
        paths = [path for path in tracked_paths(root)
                 if path == "Cargo.lock" or path.startswith(tls.bounded.PROVIDER + "/")]
        observed = []
        expected = finding("rustsec", "RUSTSEC-2099-0001", tls.MANIFEST, "rustls@0.23.46")

        def audit(payload, path, _binary, _database, _identity, _scratch):
            observed.append(path)
            if path == tls.MANIFEST:
                packages = tomllib.loads(payload.decode())["package"]
                self.assertEqual(packages, [{"name": "rustls", "version": "0.23.46", "source": tls.REGISTRY,
                                             "checksum": "48e13bd8c0e9365c43cfa5c9e8f9ad49d3c8444926c9aac819e0e4dc503c8fdf"}])
                return [expected], {"lock_sha256": digest(payload), "packages": 1}
            self.assertEqual(payload, (root / path).read_bytes())
            return [], {"lock_sha256": digest(payload), "packages": 1}

        with patch.object(advisories, "tracked_paths", return_value=paths), \
                patch.object(advisories, "verify_tool", return_value=root / "not-executed"), \
                patch.object(advisories, "fetch_rustsec", return_value=(root / "database", {"commit": "a" * 40})), \
                patch.object(advisories, "audit_lock", side_effect=audit):
            findings, receipt = advisories.rustsec(root, root, root)
        self.assertEqual(observed, ["Cargo.lock", tls.LOCK, tls.MANIFEST])
        self.assertEqual(findings, [expected])
        self.assertTrue(receipt["locks"][-1]["notBuildLock"])

    def test_missing_partial_or_changed_source_cannot_claim_the_authenticated_origin(self):
        root = tls.bounded.ROOT
        self.assertIsNone(tls.origin(root, ["Cargo.toml", "Cargo.lock"]))
        for paths in ([tls.MANIFEST], [tls.LOCK], [tls.bounded.PROVIDER + "/LICENSE-MIT"]):
            with self.subTest(paths=paths), self.assertRaisesRegex(SecurityError, "partial-bounded-tls-source"):
                tls.origin(root, paths)
        with patch.object(tls.bounded, "verify", side_effect=ValueError("tampered-whole-source")), \
                self.assertRaisesRegex(SecurityError, "unreviewed-bounded-tls-source"):
            tls.origin(root, [tls.MANIFEST, tls.LOCK])

    def test_only_the_exact_provider_policy_entry_is_accepted(self):
        row = {"path": tls.MANIFEST, "kind": "bounded-rustls", "lock": tls.LOCK,
               "absent_when_directory_missing": tls.bounded.PROVIDER}
        for changed in ({**row, "path": "crates/vendor/foreign/Cargo.toml"},
                        {**row, "lock": "Cargo.lock"}, {**row, "skip_advisories": True},
                        {**row, "absent_when_directory_missing": "crates/vendor"}):
            with self.subTest(changed=changed), self.assertRaisesRegex(SecurityError, "unreviewed-bounded-tls-inventory"):
                tls.inventory_record(tls.bounded.ROOT, changed, [tls.MANIFEST, tls.LOCK])


if __name__ == "__main__":
    unittest.main()
