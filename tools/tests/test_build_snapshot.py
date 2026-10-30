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
    def test_current_workspace_members_are_all_in_the_exact_capture_selection(self) -> None:
        from tools import build_snapshot
        import tomllib
        root = Path(__file__).resolve().parents[2]
        members = tomllib.loads((root / 'Cargo.toml').read_text(encoding='utf-8'))['workspace']['members']
        self.assertEqual([member for member in members if not build_snapshot._selected(member)], [])
        self.assertTrue(all((root / member / 'Cargo.toml').is_file() for member in members))

    def test_standard_stdio_workspace_member_and_its_source_survive_real_committed_capture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            repo = parent / 'repo'
            repository(repo)
            member = repo / 'sdk/rust-standard-stdio'
            (member / 'src').mkdir(parents=True)
            manifest = b'[package]\nname="latent-rust-standard-stdio"\nversion="0.1.0"\nedition="2024"\n'
            source = b'pub fn captured_standard_stdio() {}\n'
            (member / 'Cargo.toml').write_bytes(manifest)
            (member / 'src/lib.rs').write_bytes(source)
            (repo / 'Cargo.toml').write_bytes(b'[workspace]\nmembers=["crates/demo","sdk/rust-standard-stdio"]\n')
            git(repo, 'add', '.')
            git(repo, 'commit', '--quiet', '-m', 'standard stdio workspace member')
            revision = git(repo, 'rev-parse', 'HEAD')
            target = parent / 'target'
            target.mkdir()
            with capture_source(repo, revision, target) as captured:
                self.assertEqual((captured.root / 'sdk/rust-standard-stdio/Cargo.toml').read_bytes(), manifest)
                self.assertEqual((captured.root / 'sdk/rust-standard-stdio/src/lib.rs').read_bytes(), source)
                self.assertFalse((captured.root / 'benchmarks').exists())

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
        # The finite 76 MiB source budget has a separate 7 MiB allowance
        # for archive framing. Both remain hard caps.
        self.assertEqual(SnapshotLimits().max_total_bytes, 76 * 1024 * 1024)
        self.assertEqual(SnapshotLimits().max_archive_bytes, 83 * 1024 * 1024)
        SnapshotLimits().validate()
        for limits in (SnapshotLimits(max_entries=0),
                       SnapshotLimits(max_total_bytes=76 * 1024 * 1024 + 1),
                       SnapshotLimits(max_archive_bytes=83 * 1024 * 1024 + 1)):
            with self.assertRaises(SnapshotError):
                limits.validate()

    def test_directory_headers_have_a_separate_finite_allowance(self) -> None:
        payload = archive([("crates", b"", tarfile.DIRTYPE),
                           ("crates/example", b"", tarfile.DIRTYPE),
                           ("crates/example/lib.rs", b"source", tarfile.REGTYPE)])
        with tempfile.TemporaryDirectory() as temporary:
            rows = json.loads(extract_archive(payload, Path(temporary) / "source",
                SnapshotLimits(max_entries=1, max_directories=2)))
            self.assertEqual([row["path"] for row in rows], ["crates/example/lib.rs"])
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(SnapshotError):
            extract_archive(payload, Path(temporary) / "source",
                            SnapshotLimits(max_entries=1, max_directories=1))
        for maximum in (0, 4097):
            with self.subTest(maximum=maximum), self.assertRaises(SnapshotError):
                SnapshotLimits(max_directories=maximum).validate()

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


class StoredZipSourceTests(unittest.TestCase):
    @staticmethod
    def _fixture(records=None, *, descriptor=False):
        """Synthetic STORED bytes only; not a compiler or qualified Git source."""
        import binascii
        import struct
        if records is None:
            records = [("tools/", b"", 0x10, 0), ("tools/a.py", b"abc", 0, 0),
                       ("tools/run.sh", b"#!/bin/sh\n", 0x81ed0000, 3)]
        revision = "a" * 40
        extra = b"UT\x05\x00\x01" + struct.pack("<I", 1700000000)
        output = bytearray()
        central = []
        places = {"local": [], "data": [], "central": []}
        for name, data, external, creator in records:
            encoded = name.encode("ascii")
            flags = 8 if descriptor and not name.endswith("/") else 0
            crc = binascii.crc32(data) & 0xffffffff
            start = len(output)
            places["local"].append(start)
            output.extend(struct.pack("<4s5H3I2H", b"PK\x03\x04", 10, flags, 0, 0, 33,
                                      0 if flags else crc, len(data), len(data), len(encoded), len(extra)))
            output.extend(encoded + extra)
            places["data"].append(len(output))
            output.extend(data)
            if flags:
                output.extend(struct.pack("<4s3I", b"PK\x07\x08", crc, len(data), len(data)))
            central.append(struct.pack("<4s6H3I5H2I", b"PK\x01\x02", creator << 8, 10,
                flags, 0, 0, 33, crc, len(data), len(data), len(encoded), len(extra), 0,
                0, 0, external, start) + encoded + extra)
        start = len(output)
        for item in central:
            places["central"].append(len(output)); output.extend(item)
        places["eocd"] = len(output)
        output.extend(struct.pack("<4s4H2IH", b"PK\x05\x06", 0, 0, len(records), len(records),
                                  len(output) - start, start, len(revision)))
        output.extend(revision.encode())
        return bytes(output), places, revision

    @staticmethod
    def _change(raw, offset, kind, value):
        import struct
        output = bytearray(raw); struct.pack_into(kind, output, offset, value)
        return bytes(output)

    def test_stored_git_zip_matches_tar_modes_crlf_and_committed_inventory(self):
        from tools import build_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary); repo = parent / "repo"
            repository(repo)
            (repo / "tools").mkdir()
            script = b"#!/bin/sh\nexit 0\n"  # Never executed.
            launcher = b"@echo off\nexit /b 0\n"
            (repo / "tools/run.sh").write_bytes(script)
            (repo / "tools/intellij.cmd").write_bytes(launcher)
            (repo / ".gitattributes").write_bytes(b"/tools/intellij.cmd text eol=crlf\n")
            git(repo, "add", "."); git(repo, "update-index", "--chmod=+x", "tools/run.sh")
            git(repo, "commit", "--quiet", "-m", "stored capture mode fixture")
            revision = git(repo, "rev-parse", "HEAD")
            listing = subprocess.run(["git", "ls-tree", "-r", "-z", "--full-tree", revision,
                "--", *build_snapshot.SOURCE_ALLOWLIST], cwd=repo, check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15).stdout
            modes = {}
            for item in listing.split(b"\0"):
                if item:
                    head, name = item.decode().split("\t"); modes[name] = head.split()[0]
            roots = sorted({root for name in modes for root in build_snapshot.SOURCE_ALLOWLIST
                            if name == root or name.startswith(root + "/")})
            tar = subprocess.run(["git", "archive", "--format=tar", revision, "--", *roots],
                cwd=repo, env=build_snapshot.git_environment(), check=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15).stdout
            legacy = extract_archive(tar, parent / "legacy", SnapshotLimits())
            (repo / "crates/demo/source.rs").write_bytes(b"dirty, not selected\n")
            (repo / "tools/untracked.py").write_bytes(b"untracked\n")
            target = parent / "target"; target.mkdir()
            with capture_source(repo, revision, target) as snapshot:
                self.assertEqual(snapshot.inventory, legacy)
                self.assertEqual({row["path"] for row in json.loads(legacy)}, set(modes))
                self.assertEqual((snapshot.root / "tools/run.sh").read_bytes(), script)
                self.assertEqual((snapshot.root / "tools/intellij.cmd").read_bytes(), launcher.replace(b"\n", b"\r\n"))
                self.assertEqual(next(row["mode"] for row in json.loads(legacy)
                                      if row["path"] == "tools/run.sh"), 0o755)
                self.assertFalse((snapshot.root / "tools/untracked.py").exists())
                captured = snapshot.root
            self.assertFalse(captured.exists()); self.assertEqual(list(target.iterdir()), [])
            # The real native signed descriptor branch remains stored and
            # mode-bound even when Git's small streaming threshold is forced.
            streamed = subprocess.run(["git", "-c", "core.bigFileThreshold=1", "archive",
                "--format=zip", "-0", revision, "--", *roots], cwd=repo, check=True,
                env=build_snapshot.git_environment(), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=15).stdout
            # Native Git's forced streaming also bypasses CRLF conversion in
            # TAR. Compare both formats under the SAME Git configuration;
            # the normal-config CRLF assertion above remains mandatory.
            streamed_tar = subprocess.run(["git", "-c", "core.bigFileThreshold=1", "archive",
                "--format=tar", revision, "--", *roots], cwd=repo, check=True,
                env=build_snapshot.git_environment(), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=15).stdout
            streamed_legacy = extract_archive(streamed_tar, parent / "streamed-legacy", SnapshotLimits())
            same = extract_archive(streamed, parent / "streamed", SnapshotLimits(),
                archive_format="stored-zip", expected_files=modes, revision=revision)
            self.assertEqual(same, streamed_legacy)

    def test_stored_zip_preflight_rejects_structural_crc_and_descriptor_faults_before_effects(self):
        from unittest.mock import patch
        from tools import build_snapshot
        raw, at, revision = self._fixture()
        modes = {"tools/a.py": "100644", "tools/run.sh": "100755"}
        central, local, end = at["central"][1], at["local"][1], at["eocd"]
        faults = [
            ("trailing bytes", raw + b"x"), ("truncated EOCD", raw[:-1]),
            ("bad commit", raw[:-1] + b"b"),
            ("multi disk", self._change(raw, end + 4, "<H", 1)),
            ("excessive metadata", self._change(self._change(raw, end + 8, "<H", 65534), end + 10, "<H", 65534)),
            ("ZIP64", self._change(self._change(raw, end + 8, "<H", 65535), end + 10, "<H", 65535)),
            ("central size", self._change(raw, end + 12, "<I", 0xffffffff)),
            ("central offset", self._change(raw, end + 16, "<I", 1)),
            ("local alias", self._change(raw, central + 42, "<I", 0)),
            ("local overlap", self._change(raw, central + 42, "<I", local + 1)),
            ("name extent", self._change(raw, central + 28, "<H", 513)),
            ("local CRC", self._change(raw, local + 14, "<I", 1)),
            ("central CRC", self._change(raw, central + 16, "<I", 1)),
            ("local size", self._change(raw, local + 22, "<I", 2)),
            ("payload CRC", self._change(raw, at["data"][1], "<B", 0)),
        ]
        streamed, slots, _ = self._fixture(descriptor=True)
        descriptor = slots["data"][1] + 3
        faults.extend([("descriptor signature", self._change(streamed, descriptor, "<I", 0)),
                       ("descriptor CRC", self._change(streamed, descriptor + 4, "<I", 1))])
        with tempfile.TemporaryDirectory() as temporary:
            for index, (label, candidate) in enumerate(faults):
                destination = Path(temporary) / str(index)
                with self.subTest(label=label), patch.object(build_snapshot.tarfile, "open",
                        side_effect=AssertionError("ZIP must never fall back to tar")):
                    with self.assertRaises(SnapshotError):
                        extract_archive(candidate, destination, SnapshotLimits(),
                            archive_format="stored-zip", expected_files=modes, revision=revision)
                self.assertFalse(destination.exists())

    def test_stored_zip_requires_git_paths_modes_and_rejects_unsupported_encoding(self):
        raw, at, revision = self._fixture()
        modes = {"tools/a.py": "100644", "tools/run.sh": "100755"}
        central = at["central"][1]
        variants = [("missing expected file", raw, {**modes, "tools/absent.py": "100644"}),
            ("unexpected file", raw, {"tools/a.py": "100644"}),
            ("wrong executable mode", raw, {**modes, "tools/run.sh": "100644"}),
            ("invalid Git mode", raw, {**modes, "tools/run.sh": "120000"}),
            ("mode map required", raw, None),
            ("encryption", self._change(raw, central + 8, "<H", 1), modes),
            ("deflate", self._change(raw, central + 10, "<H", 8), modes),
            ("unknown flags", self._change(raw, central + 8, "<H", 2048), modes),
            ("entry comment", self._change(raw, central + 32, "<H", 1), modes),
            ("unknown creator", self._change(raw, central + 4, "<H", 7 << 8), modes),
            ("unknown DOS attrs", self._change(raw, central + 38, "<I", 4), modes),
            ("symlink", self._change(self._change(raw, central + 4, "<H", 3 << 8), central + 38, "<I", 0xa1ff0000), modes),
            ("ZIP64 extra", self._change(raw, central + 46 + len("tools/a.py"), "<H", 1), modes)]
        for bad in ("../outside", "/absolute", "tools/CON.txt", "tools/x/../a", "tools\\x", "C:/drive"):
            encoded, _, _ = self._fixture([("tools/", b"", 0x10, 0), (bad, b"x", 0, 0)])
            variants.append((bad, encoded, modes))
        for label, names in [("duplicate", ("tools/a.py", "tools/a.py")),
                             ("case alias", ("tools/A.py", "tools/a.py")),
                             ("prefix alias", ("tools/a", "tools/a/file.py"))]:
            encoded, _, _ = self._fixture([("tools/", b"", 0x10, 0),
                (names[0], b"x", 0, 0), (names[1], b"y", 0, 0)])
            variants.append((label, encoded, {name: "100644" for name in names}))
        with tempfile.TemporaryDirectory() as temporary:
            for index, (label, encoded, expected) in enumerate(variants):
                destination = Path(temporary) / str(index)
                with self.subTest(label=label), self.assertRaises(SnapshotError):
                    extract_archive(encoded, destination, SnapshotLimits(), archive_format="stored-zip",
                        expected_files=expected, revision=revision)
                self.assertFalse(destination.exists())

    def test_stored_zip_exact_caps_empty_files_and_explicit_dispatch_are_preserved(self):
        from dataclasses import replace
        records = [("tools/", b"", 0x10, 0), ("tools/a/", b"", 0x10, 0),
            ("tools/a/one", b"ab", 0, 0), ("tools/a/two", b"cde", 0, 0),
            ("tools/a/empty", b"", 0, 0)]
        raw, _, revision = self._fixture(records)
        modes = {name: "100644" for name, _, _, _ in records if not name.endswith("/")}
        limits = SnapshotLimits(max_entries=3, max_directories=2, max_file_bytes=3,
                               max_total_bytes=5, max_archive_bytes=len(raw))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rows = json.loads(extract_archive(raw, root / "exact", limits, archive_format="stored-zip",
                expected_files=modes, revision=revision))
            self.assertEqual(len(rows), 3); self.assertEqual(sum(row["size"] for row in rows), 5)
            self.assertEqual((root / "exact/tools/a/empty").read_bytes(), b"")
            for field, maximum in [("max_entries", 2), ("max_directories", 1),
                ("max_file_bytes", 2), ("max_total_bytes", 4), ("max_archive_bytes", len(raw) - 1)]:
                target = root / field
                with self.subTest(field=field), self.assertRaises(SnapshotError):
                    extract_archive(raw, target, replace(limits, **{field: maximum}),
                        archive_format="stored-zip", expected_files=modes, revision=revision)
                self.assertFalse(target.exists())
            with self.assertRaises(SnapshotError):
                extract_archive(raw, root / "unknown", limits, archive_format="guess",
                    expected_files=modes, revision=revision)
            self.assertFalse((root / "unknown").exists())
            # Unknown formats and ZIP without a real caller revision never gain
            # authority by looking like a legacy TAR input.
            with self.assertRaises(SnapshotError):
                extract_archive(raw, root / "missing-revision", limits, archive_format="stored-zip",
                    expected_files=modes)


if __name__ == "__main__":
    unittest.main()
