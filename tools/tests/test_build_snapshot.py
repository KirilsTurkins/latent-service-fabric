"""Committed-source isolation and bounded hostile archive regression tests."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from tools.build_snapshot import (
    SnapshotError, SnapshotLimits, capture_source, digest, extract_archive, owned_child,
    remove_owned_directory,
)


def archive(entries: list[tuple[str, bytes, bytes]]) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as stream:
        for name, contents, kind in entries:
            item = tarfile.TarInfo(name)
            item.type = kind
            item.mode = 0o644
            item.size = len(contents) if kind == tarfile.REGTYPE else 0
            if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                item.linkname = "../outside"
            stream.addfile(item, io.BytesIO(contents) if kind == tarfile.REGTYPE else None)
    return output.getvalue()


def git(root: Path, *args: str, data: bytes | None = None) -> str:
    completed = subprocess.run(["git", "-c", "user.name=LSF fixture", "-c",
        "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=root, input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=15, check=True)
    return completed.stdout.decode().strip()


def repository(root: Path) -> str:
    root.mkdir()
    git(root, "init", "--quiet")
    git(root, "config", "core.autocrlf", "false")
    (root / "crates/demo").mkdir(parents=True)
    (root / "Cargo.toml").write_text('[workspace]\nmembers=["crates/demo"]\n')
    (root / "crates/demo/Cargo.toml").write_text('[package]\nname="demo"\nversion="1.0.0"\n')
    (root / "crates/demo/source.rs").write_bytes(b"committed bytes\n")
    (root / "benchmarks").mkdir()
    (root / "benchmarks/ignored-report.bin").write_bytes(b"excluded evidence")
    git(root, "add", ".")
    git(root, "commit", "--quiet", "-m", "fixture")
    return git(root, "rev-parse", "HEAD")


class BuildSnapshotTests(unittest.TestCase):
    def test_real_capture_uses_committed_bytes_excludes_evidence_and_is_repeatable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo = parent / "repo"
            revision = repository(repo)
            target = parent / "target"
            target.mkdir()
            (repo / "crates/demo/source.rs").write_bytes(b"dirty worktree replacement")
            (repo / "crates/demo/untracked.rs").write_bytes(b"untracked")
            with capture_source(repo, revision, target) as first:
                self.assertEqual((first.root / "crates/demo/source.rs").read_bytes(), b"committed bytes\n")
                self.assertFalse((first.root / "crates/demo/untracked.rs").exists())
                self.assertFalse((first.root / "benchmarks").exists())
                rows = json.loads(first.inventory)
                self.assertEqual(rows, sorted(rows, key=lambda row: row["path"]))
                self.assertTrue(all(row["mode"] == 0o644 for row in rows))
                self.assertEqual(first.digest, digest(first.inventory))
                inventory = first.inventory
                captured_root = first.root
            self.assertFalse(captured_root.exists())
            with capture_source(repo, revision, target) as second:
                self.assertEqual(second.inventory, inventory)
            self.assertEqual(list(target.iterdir()), [])

    def test_capture_rejects_git_symlink_and_cleans_its_owned_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo = parent / "repo"
            repository(repo)
            blob = git(repo, "hash-object", "-w", "--stdin", data=b"../../outside")
            git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},crates/link")
            git(repo, "commit", "--quiet", "-m", "link")
            revision = git(repo, "rev-parse", "HEAD")
            target = parent / "target"
            target.mkdir()
            with self.assertRaises(SnapshotError):
                with capture_source(repo, revision, target):
                    self.fail("link was captured")
            self.assertEqual(list(target.iterdir()), [])

    def test_unsafe_members_cannot_escape_or_introduce_special_files(self) -> None:
        cases = [
            [("../outside", b"x", tarfile.REGTYPE)],
            [("/absolute", b"x", tarfile.REGTYPE)],
            [("crates/a/../../outside", b"x", tarfile.REGTYPE)],
            [("crates\\outside", b"x", tarfile.REGTYPE)],
            [("crates/CON.txt", b"x", tarfile.REGTYPE)],
            [("crates/link", b"", tarfile.SYMTYPE)],
            [("crates/link", b"", tarfile.LNKTYPE)],
            [("crates/fifo", b"", tarfile.FIFOTYPE)],
            [("benchmarks/report", b"x", tarfile.REGTYPE)],
            [("crates/x", b"x", tarfile.REGTYPE), ("crates/x", b"y", tarfile.REGTYPE)],
            [("crates/X", b"x", tarfile.REGTYPE), ("crates/x", b"y", tarfile.REGTYPE)],
            [("crates/x", b"x", tarfile.REGTYPE), ("crates/x/y", b"y", tarfile.REGTYPE)],
            [("crates/x/y", b"x", tarfile.REGTYPE), ("crates/x", b"y", tarfile.REGTYPE)],
            [("crates/Foo/x", b"x", tarfile.REGTYPE), ("crates/foo/y", b"y", tarfile.REGTYPE)],
        ]
        for entries in cases:
            with self.subTest(entries=entries), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary)
                with self.assertRaises(SnapshotError):
                    extract_archive(archive(entries), parent / "source", SnapshotLimits())
                self.assertFalse((parent / "outside").exists())

    def test_archive_entry_file_and_aggregate_ceilings(self) -> None:
        payload = archive([("crates/a", b"1234", tarfile.REGTYPE), ("crates/b", b"12", tarfile.REGTYPE)])
        for limits in (SnapshotLimits(max_entries=1), SnapshotLimits(max_file_bytes=3),
                       SnapshotLimits(max_total_bytes=5), SnapshotLimits(max_archive_bytes=100)):
            with self.subTest(limits=limits), tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(SnapshotError):
                    extract_archive(payload, Path(temporary) / "source", limits)
        for limits in (SnapshotLimits(max_entries=0), SnapshotLimits(max_total_bytes=33 * 1024 * 1024)):
            with self.assertRaises(SnapshotError):
                limits.validate()

    def test_cleanup_refuses_root_and_outside_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "owned"
            child.mkdir()
            (child / "artifact").write_bytes(b"x")
            with self.assertRaises(SnapshotError):
                remove_owned_directory(root, root)
            with self.assertRaises(SnapshotError):
                owned_child(root.parent / "outside", root)
            remove_owned_directory(child, root)
            self.assertFalse(child.exists())

    @unittest.skipIf(os.name == "nt", "Unix executable modes are preserved directly")
    def test_executable_mode_changes_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as stream:
                item = tarfile.TarInfo("tools/driver.sh")
                item.mode = 0o775
                item.size = 1
                stream.addfile(item, io.BytesIO(b"x"))
            rows = json.loads(extract_archive(output.getvalue(), parent / "source", SnapshotLimits()))
            self.assertEqual(rows[0]["mode"], 0o755)
            self.assertEqual((parent / "source/tools/driver.sh").stat().st_mode & 0o777, 0o755)


if __name__ == "__main__":
    unittest.main()
