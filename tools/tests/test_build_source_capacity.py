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
        sizes = git(root, "ls-tree", "-r", "-l", revision,
                    "--", *SOURCE_ALLOWLIST).splitlines()
        selected_bytes = sum(int(row.split("\t", 1)[0].split()[-1]) for row in sizes)
        limits = SnapshotLimits()
        print(f"SOURCE_CAPTURE_CAPACITY revision={revision} files={len(selected)} "
              f"bytes={selected_bytes} file_limit={limits.max_entries} "
              f"byte_limit={limits.max_total_bytes}", flush=True)
        self.assertLessEqual(len(selected), limits.max_entries)
        self.assertLessEqual(selected_bytes, limits.max_total_bytes)
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            cache = target / "cargo-cache"
            cache.mkdir()
            with capture_source(root, revision, target) as captured:
                rows = json.loads(captured.inventory)
                self.assertEqual({row["path"] for row in rows}, selected)
                self.assertEqual(sum(row["size"] for row in rows), selected_bytes)
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
            self.assertEqual(maximum, 8704)
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

    def test_current_committed_selection_passes_preflight_without_running_archive(self):
        from unittest.mock import patch
        from tools import build_snapshot

        class ArchiveBoundary(Exception):
            pass

        root = Path(__file__).resolve().parents[2]
        revision = git(root, "rev-parse", "HEAD")
        original_run = build_snapshot.run_bounded

        def before_archive(command, **arguments):
            if command[1] == "archive":
                raise ArchiveBoundary()
            return original_run(command, **arguments)

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            with patch.object(build_snapshot, "run_bounded", side_effect=before_archive) as run:
                with self.assertRaises(ArchiveBoundary):
                    with capture_source(root, revision, target):
                        self.fail("the archive boundary must stop source capture")
                self.assertEqual([call.args[0][1] for call in run.call_args_list],
                                 ["rev-parse", "ls-tree", "archive"])
            self.assertEqual(list(target.iterdir()), [])

    def test_tree_full_file_ceiling_passes_but_one_over_refuses_before_archive(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools import build_snapshot

        class ArchiveBoundary(Exception):
            pass

        revision = "a" * 40
        maximum = SnapshotLimits().max_entries
        for count in (maximum, maximum + 1):
            listing = b"".join(f"100644 blob {'b' * 40}\ttools/part-{index}.py\0".encode()
                               for index in range(count))

            def source_commands(command, **arguments):
                if command[1] == "rev-parse":
                    return SimpleNamespace(stdout=(revision + "\n").encode())
                if command[1] == "ls-tree":
                    return SimpleNamespace(stdout=listing)
                self.assertEqual(command[1], "archive")
                raise ArchiveBoundary()

            with self.subTest(count=count), tempfile.TemporaryDirectory() as temporary:
                target = Path(temporary)
                with patch.object(build_snapshot, "run_bounded", side_effect=source_commands) as run:
                    expected = ArchiveBoundary if count == maximum else SnapshotError
                    with self.assertRaises(expected) as raised:
                        with capture_source(target, revision, target):
                            self.fail("the archive boundary must stop source capture")
                    commands = [call.args[0][1] for call in run.call_args_list]
                    self.assertEqual(commands, ["rev-parse", "ls-tree", "archive"] if count == maximum
                                     else ["rev-parse", "ls-tree"])
                    if count > maximum:
                        self.assertEqual(str(raised.exception), "source tree entry limit exceeded")
                self.assertEqual(list(target.iterdir()), [])

    def test_capture_byte_allowances_are_fixed_and_reject_one_over(self):
        from dataclasses import replace
        from unittest.mock import patch
        from tools import build_process

        limits = SnapshotLimits()
        self.assertEqual(limits.max_total_bytes, 80 * 1024 * 1024)
        self.assertEqual(limits.max_archive_bytes, 88 * 1024 * 1024)
        self.assertEqual(limits.max_archive_bytes, build_process.MAX_OUTPUT_BYTES)
        self.assertEqual(limits.max_file_bytes, 4 * 1024 * 1024)
        self.assertEqual(limits.max_directories, 4096)
        limits.validate()
        for name in limits.__dataclass_fields__:
            with self.subTest(field=name):
                for value in (0, True, getattr(limits, name) + 1):
                    with self.assertRaisesRegex(SnapshotError, "invalid source capture limits"):
                        replace(limits, **{name: value}).validate()
        # Exercise admission itself without spawning or allocating an archive.
        # Python-version and process-ownership checks have separate tests.
        with patch.object(build_process.sys, "version_info", (3, 13)):
            self.assertEqual(build_process._validate(["git"], Path.cwd(), {}, 30,
                                                     limits.max_archive_bytes), ["git"])
            with self.assertRaisesRegex(build_process.BuildProcessError,
                                        "command-output-limit-invalid"):
                build_process._validate(["git"], Path.cwd(), {}, 30,
                                        limits.max_archive_bytes + 1)

    def test_archive_and_content_byte_limits_are_enforced_independently(self):
        from dataclasses import replace
        import tarfile
        from tools.build_snapshot import extract_archive
        from tools.tests.test_build_snapshot import archive

        encoded = archive([("tools/first.py", b"ab", tarfile.REGTYPE),
                           ("tools/second.py", b"cde", tarfile.REGTYPE)])
        limits = SnapshotLimits(max_total_bytes=5, max_file_bytes=3,
                                max_archive_bytes=len(encoded))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = json.loads(extract_archive(encoded, root / "exact", limits))
            self.assertEqual(sum(row["size"] for row in rows), 5)
            for field, value, reason in (
                ("max_total_bytes", 4, "captured source total limit exceeded"),
                ("max_file_bytes", 2, "captured source file limit exceeded"),
                ("max_archive_bytes", len(encoded) - 1, "source archive byte limit exceeded"),
            ):
                with self.subTest(field=field):
                    destination = root / field
                    with self.assertRaisesRegex(SnapshotError, reason):
                        extract_archive(encoded, destination, replace(limits, **{field: value}))
                    self.assertFalse((destination / "tools/second.py").exists())
                    if field == "max_archive_bytes":
                        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
