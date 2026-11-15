from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools.security_actions import verify
from tools.security_common import SecurityError


class ActionGraphTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.reference = "owner/action@" + "a" * 40
        self.paths = []
        self.write(".github/workflows/ci.yml", "jobs:\n  test:\n    steps:\n      - uses: " + self.reference + "\n")
        metadata = self.snapshot("action.yml", "runs:\n  using: node24\n  main: dist/index.js\n")
        manifest = self.snapshot("package.json", "{}\n")
        lock = self.snapshot("package-lock.json", "{}\n")
        self.row = {"repository": "owner/action", "revision": "a" * 40,
                    "upstream_repository": "upstream/action", "kind": "npm",
                    "metadata": metadata, "files": [metadata, manifest, lock]}
        self.actions = {self.reference: self.row}

    def write(self, name, text):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        if name not in self.paths:
            self.paths.append(name)

    def snapshot(self, source, text):
        name = ".github/security/actions/test/" + source
        self.write(name, text)
        return {"source": source, "snapshot": name, "sha256": hashlib.sha256(text.encode()).hexdigest()}

    def check(self):
        self.write(".github/security/actions.json", json.dumps({"schema": 1, "actions": self.actions}))
        return verify(self.root, self.paths)

    def test_complete_reviewed_action_passes(self):
        self.assertEqual(len(self.check()), 1)

    def test_unreviewed_revision_fails(self):
        self.write(".github/workflows/ci.yml", "jobs:\n  test:\n    steps:\n      - uses: owner/action@" + "b" * 40 + "\n")
        with self.assertRaisesRegex(SecurityError, "unreviewed-external") as failure:
            self.check()
        self.assertEqual(str(failure.exception),
                         "unreviewed-external-action-graph:.github/workflows/ci.yml:4")
        self.assertNotIn("owner/action@", str(failure.exception))

    def test_changed_lock_bytes_fail(self):
        self.write(".github/security/actions/test/package-lock.json", '{"changed":true}\n')
        with self.assertRaisesRegex(SecurityError, "snapshot-drift"):
            self.check()

    def test_missing_lock_binding_fails(self):
        self.row["files"] = self.row["files"][:2]
        with self.assertRaisesRegex(SecurityError, "incomplete-action"):
            self.check()

    def test_subpath_cannot_be_rebound_to_root_metadata(self):
        self.row["metadata"]["source"] = "other/action.yml"
        with self.assertRaisesRegex(SecurityError, "entrypoint-drift"):
            self.check()

    def test_composite_dependencies_are_checked_recursively(self):
        metadata = self.snapshot("action.yml", "runs:\n  using: composite\n  steps:\n    - uses: unknown/child@" + "c" * 40 + "\n")
        self.row.update(kind="composite", metadata=metadata, files=[metadata])
        with self.assertRaisesRegex(SecurityError, "unreviewed-external") as failure:
            self.check()
        self.assertEqual(str(failure.exception),
                         "unreviewed-external-action-graph:.github/security/actions/test/action.yml:4")
        self.assertNotIn("unknown/child@", str(failure.exception))

    def test_local_action_chain_is_checked(self):
        self.write(".github/workflows/ci.yml", "jobs:\n  test:\n    steps:\n      - uses: ./.github/actions/local\n")
        self.write(".github/actions/local/action.yml", "runs:\n  using: composite\n  steps:\n    - uses: " + self.reference + "\n")
        self.assertEqual(len(self.check()), 1)

    def test_kind_cannot_hide_node_dependency_graph(self):
        self.row["kind"] = "composite"
        with self.assertRaisesRegex(SecurityError, "runtime-graph-mismatch"):
            self.check()

    def test_unused_policy_entry_fails(self):
        self.actions["unused/action@" + "a" * 40] = self.row
        with self.assertRaisesRegex(SecurityError, "unused-or-stale"):
            self.check()

    def test_additional_runtime_bindings_are_restricted_to_reviewed_action(self):
        extra = [self.snapshot(name, "fixture\n") for name in (
            ".lsf-source/verify-installed-deepmerge.mjs", ".lsf-source/verify-installed-minimatch.mjs")]
        self.row["files"].extend(extra)
        with self.assertRaisesRegex(SecurityError, "unreviewed-additional-action-source"):
            self.check()
        reference = "KirilsTurkins/lsf-setup-python@" + "a" * 40
        self.write(".github/workflows/ci.yml", "jobs:\n  test:\n    steps:\n      - uses: " + reference + "\n")
        self.row["repository"] = "KirilsTurkins/lsf-setup-python"
        self.actions = {reference: self.row}
        self.assertEqual(len(self.check()), 1)
        self.row["files"][-1]["source"] = ".lsf-source/unreviewed.mjs"
        with self.assertRaisesRegex(SecurityError, "unreviewed-additional-action-source"):
            self.check()

    def test_missing_policy_does_not_report_success(self):
        with self.assertRaises(OSError):
            verify(self.root, self.paths)

    def test_six_source_java_binding_requires_the_exact_revision_and_source_set(self):
        revision = '8aaa4ea8191b36cb3f394e91d099da0d31dc02c2'
        reference = 'KirilsTurkins/lsf-setup-java@' + revision
        self.write('.github/workflows/ci.yml', 'jobs:\n  test:\n    steps:\n      - uses: ' + reference + '\n')
        self.row.update(repository='KirilsTurkins/lsf-setup-java', revision=revision)
        self.row['files'].extend(self.snapshot(name, 'fixture\n') for name in (
            '.lsf-source/verify-installed-deepmerge.mjs', '.lsf-source/verify-installed-minimatch.mjs',
            '.lsf-source/minimatch-bounds.test.mjs'))
        self.actions = {reference: self.row}
        self.assertEqual(len(self.check()), 1)
        self.row['files'][-1]['source'] = '.lsf-source/unreviewed.mjs'
        with self.assertRaisesRegex(SecurityError, 'unreviewed-additional-action-source'):
            self.check()
        self.row['files'][-1]['source'] = '.lsf-source/minimatch-bounds.test.mjs'
        stale = 'KirilsTurkins/lsf-setup-java@' + 'a' * 40
        self.write('.github/workflows/ci.yml', 'jobs:\n  test:\n    steps:\n      - uses: ' + stale + '\n')
        self.row['revision'] = 'a' * 40
        self.actions = {stale: self.row}
        with self.assertRaisesRegex(SecurityError, 'unreviewed-additional-action-source'):
            self.check()


    def test_six_source_node_binding_requires_the_exact_revision_and_source_set(self):
        revision = '791d25988f7dc57f537b82342f7af452cd59cd6a'
        reference = 'KirilsTurkins/lsf-setup-node@' + revision
        self.write('.github/workflows/ci.yml', 'jobs:\n  test:\n    steps:\n      - uses: ' + reference + '\n')
        self.row.update(repository='KirilsTurkins/lsf-setup-node', revision=revision)
        self.row['files'].extend(self.snapshot(name, 'fixture\n') for name in (
            '.lsf-source/verify-installed-deepmerge.mjs', '.lsf-source/verify-installed-minimatch.mjs',
            '.lsf-source/minimatch-bounds.test.mjs'))
        self.actions = {reference: self.row}
        self.assertEqual(len(self.check()), 1)
        self.row['files'][-1]['source'] = '.lsf-source/unreviewed.mjs'
        with self.assertRaisesRegex(SecurityError, 'unreviewed-additional-action-source'):
            self.check()
        self.row['files'][-1]['source'] = '.lsf-source/minimatch-bounds.test.mjs'
        stale = 'KirilsTurkins/lsf-setup-node@' + 'a' * 40
        self.write('.github/workflows/ci.yml', 'jobs:\n  test:\n    steps:\n      - uses: ' + stale + '\n')
        self.row['revision'] = 'a' * 40
        self.actions = {stale: self.row}
        with self.assertRaisesRegex(SecurityError, 'unreviewed-additional-action-source'):
            self.check()


if __name__ == "__main__":
    unittest.main()
