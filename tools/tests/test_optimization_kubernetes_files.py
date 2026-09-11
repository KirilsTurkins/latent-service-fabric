"""Bounded ordinary tar/copy fixtures; no container or network is launched."""
from __future__ import annotations

from copy import deepcopy
import io
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest

from tools.optimization_docker import fixtures
from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_kubernetes import files


def archive(path, members):
    with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as output:
        for name, kind, payload in members:
            entry = tarfile.TarInfo(name)
            entry.mode = 0o750 if kind == "directory" else 0o640
            if kind == "directory":
                entry.type = tarfile.DIRTYPE
            elif kind in ("symlink", "hardlink"):
                entry.type = tarfile.SYMTYPE if kind == "symlink" else tarfile.LNKTYPE
                entry.linkname = payload
            else:
                entry.size = len(payload)
            output.addfile(entry, io.BytesIO(payload) if kind == "file" else None)


class KubernetesFiles(unittest.TestCase):
    def test_small_source_archive_retains_exact_payloads_and_observed_modes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "empty").mkdir()
            (source / "nested").mkdir()
            (source / "nested" / "data.bin").write_bytes(b"\x00original\r\n\xff")
            (source / "plan.json").write_bytes(b'{ "x" : 1 }\r\n')
            before = deepcopy(fixtures.inventory(source))
            target = root / "upload.tar"
            receipt = files.create_archive(source, target)
            self.assertEqual(receipt["inventory"], before)
            self.assertEqual(receipt["archive_bytes"], str(target.stat().st_size))
            self.assertEqual(receipt["archive_sha256"], sha256(target.read_bytes()))
            with tarfile.open(target, "r:") as original:
                members = {member.name: member for member in original}
                self.assertEqual(set(members), {row["path"] for row in before["entries"] if row["path"] != "."})
                for row in before["entries"]:
                    if row["path"] == ".":
                        continue
                    member = members[row["path"]]
                    self.assertEqual(member.mode, int(row["mode"], 8))
                    self.assertEqual(member.mtime, 0)
                    self.assertEqual((member.uid, member.gid), (0, 0))
                    if row["kind"] == "file":
                        self.assertEqual(original.extractfile(member).read(), (source / row["path"]).read_bytes())
            self.assertEqual(fixtures.inventory(source), before)
            with self.assertRaises(FileExistsError):
                files.create_archive(source, target)

    def test_directory_download_preserves_empty_dirs_and_raw_file_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tar = root / "download.tar"
            archive(tar, [("output/", "directory", None), ("output/empty/", "directory", None),
                          ("output/events.ndjson", "file", b'{ "original":true }\r\n'),
                          ("output/raw.bin", "file", b"\x00\xff")])
            original = tar.read_bytes()
            target = root / "download"
            inventory = files.extract_archive(tar, target, expected_root="output")
            self.assertTrue((target / "empty").is_dir())
            self.assertEqual((target / "events.ndjson").read_bytes(), b'{ "original":true }\r\n')
            self.assertEqual((target / "raw.bin").read_bytes(), b"\x00\xff")
            self.assertEqual(inventory, fixtures.inventory(target))
            self.assertEqual(tar.read_bytes(), original)
            with self.assertRaises(EvidenceError):
                files.extract_archive(tar, target, expected_root="output")
            self.assertEqual((target / "raw.bin").read_bytes(), b"\x00\xff")

    def test_untrusted_names_and_links_reject_before_extracting_any_member(self):
        invalid = [("output/../outside", "file", b"x"), ("/output/x", "file", b"x"),
                   ("foreign/x", "file", b"x"), ("output/a\\b", "file", b"x"),
                   ("output/link", "symlink", "../../outside"), ("output/link", "hardlink", "output/data"),
                   ("output", "file", b"x")]
        for member in invalid:
            with self.subTest(member=member), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                tar = root / "invalid.tar"
                archive(tar, [("output/safe", "file", b"retained"), member])
                before = tar.read_bytes()
                target = root / "download"
                with self.assertRaises(EvidenceError):
                    files.extract_archive(tar, target, expected_root="output")
                self.assertFalse(target.exists())
                self.assertEqual(tar.read_bytes(), before)

    def test_duplicate_case_alias_and_excess_depth_reject(self):
        for members in ([('output/A', 'file', b'1'), ('output/a', 'file', b'2')],
                        [('output/a', 'file', b'1'), ('output/a', 'file', b'1')],
                        [("output/" + "/".join(["d"] * 10), "file", b"1")]):
            with self.subTest(members=members), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                tar = root / "invalid.tar"
                archive(tar, members)
                with self.assertRaises(EvidenceError):
                    files.extract_archive(tar, root / "download", expected_root="output")

    def test_declared_member_and_physical_archive_bounds_reject_without_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tar = root / "oversized.tar"
            member = tarfile.TarInfo("output/data")
            member.size = files.MAX_TRANSFER + 1
            tar.write_bytes(member.tobuf(format=tarfile.USTAR_FORMAT) + b"\0" * 1024)
            with self.assertRaisesRegex(EvidenceError, "download-member"):
                files.extract_archive(tar, root / "download", expected_root="output")
            self.assertFalse((root / "download").exists())
            archive(tar, [("output/data", "file", b"x")])
            with self.assertRaisesRegex(EvidenceError, "fresh-bound"):
                files.extract_archive(tar, root / "download", expected_root="output", maximum=tar.stat().st_size - 1)

    def test_exact_file_copy_refuses_overwrite_and_keeps_original_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "source", root / "copied"
            data = b"original\r\n\x00\xff"
            source.write_bytes(data)
            source.chmod(0o640)
            files.copy_file(source, target)
            self.assertEqual(source.read_bytes(), data)
            self.assertEqual(target.read_bytes(), data)
            self.assertEqual(stat.S_IMODE(source.stat().st_mode), stat.S_IMODE(target.stat().st_mode))
            with self.assertRaises(FileExistsError):
                files.copy_file(source, target)
            self.assertEqual(target.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
