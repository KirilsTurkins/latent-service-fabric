"""The maintained committed source fits the shared finite build capture budget."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from tools.build_inventory_manifests import ManifestReader
from tools.build_snapshot import SnapshotError, SnapshotLimits, canonical, capture_source, digest
from tools.tests.test_build_inventory import source_fixture
from tools.tests.test_build_snapshot import git, repository


class SourceCapacityTests(unittest.TestCase):
    def test_current_committed_repository_fits_capture_and_attribution_limits(self) -> None:
        # Exercise the real source selection before compiler work. A tiny tar
        # fixture alone cannot detect growth from ownership-local CI shards.
        from tools.build_inventory_manifests import ManifestReader
        from tools.build_provenance import check_captured_inputs
        from tools.build_snapshot import SOURCE_ALLOWLIST

        root = Path(__file__).resolve().parents[2]
        revision = git(root, "rev-parse", "HEAD")
        selected = set(git(root, "ls-tree", "-r", "--name-only", revision,
                           "--", *SOURCE_ALLOWLIST).splitlines())
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            cache = target / "cargo-cache"
            cache.mkdir()
            with capture_source(root, revision, target) as captured:
                rows = json.loads(captured.inventory)
                self.assertEqual({row["path"] for row in rows}, selected)
                self.assertIn("tools/ci/history/commands-v1.json", selected)
                self.assertTrue(any(name.startswith("tools/ci/contracts/") for name in selected))
                check_captured_inputs(captured.root, captured.inventory)
                reader = ManifestReader(captured.root, captured.inventory, cache)
                self.assertEqual(set(reader.source_files), selected)
                captured_root = captured.root
            self.assertFalse(captured_root.exists())
            self.assertEqual(list(target.iterdir()), [cache])

    def test_tree_file_limit_rejects_before_archive_and_cleans_up(self) -> None:
        from unittest.mock import patch
        from tools import build_snapshot

        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo, target = parent / "repo", parent / "target"
            revision = repository(repo)
            target.mkdir()
            with patch.object(build_snapshot, "run_bounded", wraps=build_snapshot.run_bounded) as run:
                with self.assertRaisesRegex(SnapshotError, "source tree entry limit exceeded"):
                    with capture_source(repo, revision, target, SnapshotLimits(max_entries=2)):
                        self.fail("oversized tree was captured")
                self.assertEqual([call.args[0][1] for call in run.call_args_list],
                                 ["rev-parse", "ls-tree"])
            self.assertEqual(list(target.iterdir()), [])
        with self.assertRaisesRegex(SnapshotError, "invalid source capture limits"):
            SnapshotLimits(max_entries=SnapshotLimits().max_entries + 1).validate()

    def test_source_inventory_uses_capture_file_ceiling_and_rejects_one_over(self):
        from tools.build_snapshot import SnapshotLimits

        with tempfile.TemporaryDirectory() as temporary:
            source, inventory, cache, _ = source_fixture(Path(temporary))
            rows = json.loads(inventory)
            maximum = SnapshotLimits().max_entries
            self.assertEqual(maximum, 8192)
            rows.extend({"path": f"tools/ci/contracts/fixture-{index}.json",
                         "digest": digest(b"fixture"), "size": 7, "mode": 420}
                        for index in range(maximum - len(rows)))
            reader = ManifestReader(source, canonical(rows), cache)
            self.assertEqual(len(reader.source_files), maximum)
            # Repeated rows still count against the finite pre-validation cap.
            with self.assertRaisesRegex(SnapshotError, "invalid captured source inventory"):
                ManifestReader(source, canonical([*rows, rows[-1]]), cache)
            with self.assertRaisesRegex(SnapshotError, "duplicate captured source inventory path"):
                ManifestReader(source, canonical([*rows[:-1], rows[0]]), cache)


if __name__ == "__main__":
    unittest.main()
