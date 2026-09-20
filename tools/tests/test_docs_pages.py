"""Publication authority and hostile artifact regressions; no network or deployment."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import docs_pages as command
from tools import docs_pages_policy as policy

SOURCE = "a" * 40
RELEASE = "b" * 40


def run():
    return {"id": 11, "repository": {"id": 7}, "head_repository": {"id": 7},
            "head_sha": SOURCE, "head_branch": "development", "event": "push",
            "workflow_id": 9, "run_attempt": 2, "status": "completed", "conclusion": "success"}


def artifact():
    return {"id": 13, "name": "selected", "expired": False, "size_in_bytes": 200,
            "digest": "sha256:" + "c" * 64,
            "workflow_run": {"id": 11, "repository_id": 7, "head_repository_id": 7, "head_sha": SOURCE}}


def files():
    manifest = {"schema": 1, "revision": SOURCE, "dirty": False,
                "baseUrl": policy.BASE_URL, "channel": "development",
                "versions": [{"version": "0.1.0-alpha.3", "profile": "historical-source-snapshot"}]}
    result = {name: b'{}' for name in policy.RECEIPTS}
    result.update({"build/project/" + name: b"<html>synthetic static fixture</html>"
                   for name in ("index.html", "404.html", "sitemap.xml")})
    result["build/project/site-manifest.json"] = json.dumps(manifest).encode()
    result["build/project/assets/app.js"] = b"throw new Error('never execute candidate code');"
    return result


def archive(contents):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as value:
        for name, data in contents.items():
            # ZipInfo's constructor normalizes host separators on Windows.
            # Keep the hostile archive name exact on every test host.
            entry = zipfile.ZipInfo("fixture")
            entry.filename = entry.orig_filename = name
            entry.compress_type = zipfile.ZIP_DEFLATED
            value.writestr(entry, data)
    return output.getvalue()


class DocsPagesPolicyTests(unittest.TestCase):
    def test_exact_successful_push_run(self):
        policy.validate_run(run(), 7, SOURCE, 2, 9)

    def test_rejects_fork_pr_wrong_branch_workflow_attempt_or_result(self):
        changes = ({"head_repository": {"id": 8}}, {"repository": {"id": 8}},
                   {"event": "pull_request"}, {"head_branch": "feature"},
                   {"workflow_id": 10}, {"run_attempt": 3}, {"head_sha": RELEASE},
                   {"status": "in_progress"}, {"conclusion": "failure"})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy.validate_run(run() | change, 7, SOURCE, 2, 9)

    def test_prior_publication_requires_successful_default_branch_dispatch(self):
        previous = run() | {"event": "workflow_dispatch", "head_branch": "release", "head_sha": RELEASE}
        policy.validate_run(previous, 7, RELEASE, 2, 9, publisher=True)
        with self.assertRaises(ValueError):
            policy.validate_run(run(), 7, SOURCE, 2, 9, publisher=True)

    def test_artifact_origin_and_immutable_selection(self):
        self.assertEqual(policy.select_artifact([artifact()], run(), 7, "selected")["id"], 13)
        for change in ({"expired": True}, {"digest": ""}, {"size_in_bytes": policy.MAX_ARCHIVE + 1},
                       {"id": "13"}, {"workflow_run": artifact()["workflow_run"] | {"id": 12}},
                       {"workflow_run": artifact()["workflow_run"] | {"head_repository_id": 8}},
                       {"workflow_run": artifact()["workflow_run"] | {"head_sha": RELEASE}}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                policy.select_artifact([artifact() | change], run(), 7, "selected")
        with self.assertRaises(ValueError):
            policy.select_artifact([artifact(), artifact()], run(), 7, "selected")

    def test_archive_digest_is_verified_before_parsing(self):
        data = archive(files())
        self.assertEqual(policy.archive_files(data, policy.digest(data)), files())
        with self.assertRaisesRegex(ValueError, "archive-identity"):
            policy.archive_files(data, "sha256:" + "0" * 64)

    def test_rejects_traversal_absolute_ambiguous_and_control_paths(self):
        for name in ("../escape", "/absolute", "C:/escape", "ok/../bad", "a\\b", "./x", "a//b", "a\nb"):
            with self.subTest(name=name):
                data = archive({name: b"data"})
                with self.assertRaisesRegex(ValueError, "archive-path"):
                    policy.archive_files(data, policy.digest(data))

    def test_rejects_symlink_and_special_file_modes(self):
        for mode in (stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, "w") as value:
                entry = zipfile.ZipInfo("build/project/link")
                entry.create_system = 3
                entry.external_attr = (mode | 0o777) << 16
                value.writestr(entry, b"outside")
            data = stream.getvalue()
            with self.assertRaisesRegex(ValueError, "archive-file-kind"):
                policy.archive_files(data, policy.digest(data))

    def test_rejects_case_collisions_and_finite_size_overflow(self):
        data = archive({"A": b"x", "a": b"y"})
        with self.assertRaisesRegex(ValueError, "archive-duplicate"):
            policy.archive_files(data, policy.digest(data))
        data = archive({"a": b"12345"})
        with patch.object(policy, "MAX_FILE", 4), self.assertRaisesRegex(ValueError, "archive-file-size"):
            policy.archive_files(data, policy.digest(data))
        with patch.object(policy, "MAX_EXPANDED", 4), self.assertRaisesRegex(ValueError, "archive-expanded-size"):
            policy.archive_files(data, policy.digest(data))

    def test_only_exact_clean_complete_site_is_staged_as_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            site = Path(temporary) / "site"
            identity = policy.stage_site(files(), SOURCE, site)
            self.assertEqual(identity["source"], SOURCE)
            self.assertEqual((site / "assets/app.js").read_bytes(), files()["build/project/assets/app.js"])
            with self.assertRaises(FileExistsError):
                policy.stage_site(files(), SOURCE, site)

    def test_incomplete_dirty_wrong_source_and_synthetic_site_are_refused(self):
        for change in ({"dirty": True}, {"revision": RELEASE}, {"baseUrl": "/"},
                       {"versions": []}, {"versions": [{"profile": "synthetic-fixture"}]}):
            contents = files()
            manifest = json.loads(contents["build/project/site-manifest.json"]) | change
            contents["build/project/site-manifest.json"] = json.dumps(manifest).encode()
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                policy.stage_site(contents, SOURCE, Path(temporary) / "site")
        for removed in policy.RECEIPTS | {"build/project/404.html"}:
            contents = files()
            del contents[removed]
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                policy.stage_site(contents, SOURCE, Path(temporary) / "site")

    def test_unexpected_output_and_candidate_publisher_record_are_refused(self):
        for name in ("secret.txt", "build/root/index.html", "build/project/publication.json"):
            with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
                policy.stage_site(files() | {name: b"{}"}, SOURCE, Path(temporary) / "site")

    def test_rechecks_every_staged_byte_before_deploy(self):
        with tempfile.TemporaryDirectory() as temporary:
            site = Path(temporary) / "site"
            receipt = policy.stage_site(files(), SOURCE, site)
            (site / "publication.json").write_text(json.dumps(receipt), encoding="utf-8")
            policy.verify_staged_site(site, receipt)
            (site / "index.html").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "staged-tree-identity"):
                policy.verify_staged_site(site, receipt)

    def test_rollback_binds_prior_published_receipt_to_exact_artifact(self):
        receipt = {"schema": 1, "repository": policy.REPOSITORY, "source": SOURCE,
                   "ciRun": 11, "ciAttempt": 2, "artifactId": 13, "artifactDigest": artifact()["digest"]}
        data = {"publication.json": json.dumps(receipt).encode()}
        self.assertEqual(policy.rollback_receipt(data, SOURCE, 11, 2, artifact()), receipt)
        with self.assertRaisesRegex(ValueError, "rollback-receipt-identity"):
            policy.rollback_receipt(data, SOURCE, 11, 3, artifact())

    def test_guard_rechecks_freshness_after_environment_approval(self):
        environment = {"GITHUB_REPOSITORY": policy.REPOSITORY, "GITHUB_REF": "refs/heads/release",
                       "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_RUN_ID": "31",
                       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_SHA": RELEASE}
        receipt = {"schema": 1, "repository": policy.REPOSITORY, "source": SOURCE, "mode": "publish",
                   "publisherRun": 31, "publisherAttempt": 1, "publisherSource": RELEASE}
        with patch.dict(os.environ, environment), patch.object(command, "api") as api:
            api.return_value = {"commit": {"sha": SOURCE}}
            command.guard(receipt)
            api.return_value = {"commit": {"sha": RELEASE}}
            with self.assertRaisesRegex(ValueError, "stale-development"):
                command.guard(receipt)
        with patch.dict(os.environ, environment | {"GITHUB_REF": "refs/pull/1/merge"}):
            with self.assertRaisesRegex(ValueError, "publisher-ref-event"):
                command.guard(receipt)
        with patch.dict(os.environ, environment), patch.object(command, "live_publication") as live:
            rollback = receipt | {"mode": "rollback", "expectedLiveSource": RELEASE}
            live.return_value = {"source": RELEASE}
            command.guard(rollback)
            live.return_value = {"source": SOURCE}
            with self.assertRaisesRegex(ValueError, "live-source-changed"):
                command.guard(rollback)


if __name__ == "__main__":
    unittest.main()
