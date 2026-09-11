"""Bounded ordinary tar/copy fixtures; no container or network is launched."""
from __future__ import annotations

from copy import deepcopy
import io
from pathlib import Path
import stat
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


class KubernetesCampaignInventory(unittest.TestCase):
    def test_inventory_matches_existing_file_bytes_modes_and_empty_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "empty").mkdir()
            (root / "nested").mkdir()
            (root / "nested" / "original.bin").write_bytes(b"\x00original\r\n\xff")
            (root / "zero").write_bytes(b"")
            expected = fixtures.inventory(root)
            self.assertEqual(files.campaign_inventory(root), expected)
            self.assertEqual(expected["entries"][0]["path"], ".")
            self.assertEqual((root / "nested" / "original.bin").read_bytes(), b"\x00original\r\n\xff")

    def test_count_includes_root_and_does_not_change_small_fixture_limit(self):
        self.assertEqual(files.MAX_CAMPAIGN_ENTRIES, 6144)
        self.assertEqual(fixtures.MAXIMUM_FILES, 4096)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("a", "b", "c"):
                (root / name).write_bytes(b"")
            with patch.object(files, "MAX_CAMPAIGN_ENTRIES", 4), patch.object(fixtures, "MAXIMUM_FILES", 2):
                self.assertEqual(len(files.campaign_inventory(root)["entries"]), 4)
                with self.assertRaisesRegex(ValueError, "docker-template-entry-bound"):
                    fixtures.inventory(root)
                (root / "empty-directory").mkdir()
                with self.assertRaisesRegex(EvidenceError, "campaign-entry-bound"):
                    files.campaign_inventory(root)

    def test_directory_depth_is_bounded_without_changing_file_content(self):
        self.assertEqual(files.MAX_CAMPAIGN_DEPTH, 8)
        with tempfile.TemporaryDirectory() as temporary:
            root = current = Path(temporary)
            for _ in range(files.MAX_CAMPAIGN_DEPTH):
                current /= "nested"
                current.mkdir()
            (current / "data").write_bytes(b"leaf")
            self.assertEqual(files.campaign_inventory(root)["bytes"], "4")
            (current / "too-deep").mkdir()
            with self.assertRaisesRegex(EvidenceError, "campaign-depth-bound"):
                files.campaign_inventory(root)
            self.assertEqual((current / "data").read_bytes(), b"leaf")

    def test_file_and_total_byte_caps_reject_with_scaled_physical_files(self):
        self.assertEqual(files.MAX_CAMPAIGN_FILE_BYTES, 256 * 1024**2)
        self.assertEqual(files.MAX_CAMPAIGN_BYTES, 1024**3)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a").write_bytes(b"abc")
            with patch.object(files, "MAX_CAMPAIGN_FILE_BYTES", 2), \
                 patch.object(files, "fingerprint", wraps=files.fingerprint) as hashed, \
                 self.assertRaisesRegex(EvidenceError, "campaign-file-bound"):
                files.campaign_inventory(root)
            hashed.assert_not_called()
            (root / "b").write_bytes(b"1234")
            with patch.object(files, "MAX_CAMPAIGN_FILE_BYTES", 4), patch.object(files, "MAX_CAMPAIGN_BYTES", 7):
                self.assertEqual(files.campaign_inventory(root)["bytes"], "7")
            with patch.object(files, "MAX_CAMPAIGN_BYTES", 6), \
                 self.assertRaisesRegex(EvidenceError, "campaign-total-bound"):
                files.campaign_inventory(root)
            self.assertEqual((root / "a").read_bytes(), b"abc")
            self.assertEqual((root / "b").read_bytes(), b"1234")

    def test_symlink_reparse_and_special_metadata_reject_before_hashing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "ordinary"
            target.write_bytes(b"original")
            original_lstat = Path.lstat
            invalid = ((stat.S_IFLNK | 0o777, 0), (stat.S_IFREG | 0o600, stat.FILE_ATTRIBUTE_REPARSE_POINT),
                       (stat.S_IFIFO | 0o600, 0), (stat.S_IFSOCK | 0o600, 0))
            for mode, attributes in invalid:
                def observed(path):
                    return (SimpleNamespace(st_mode=mode, st_file_attributes=attributes) if path == target
                            else original_lstat(path))
                with self.subTest(mode=mode, attributes=attributes), patch.object(Path, "lstat", observed), \
                     patch.object(files, "fingerprint") as hashed, \
                     self.assertRaisesRegex(EvidenceError, "campaign-entry-type"):
                    files.campaign_inventory(root)
                hashed.assert_not_called()
            self.assertEqual(target.read_bytes(), b"original")

    def test_linked_parent_non_directory_root_and_parent_traversal_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            child = root / "child"
            child.mkdir()
            (root / "ordinary").write_bytes(b"x")
            with self.assertRaisesRegex(EvidenceError, "campaign-directory-type"):
                files.campaign_inventory(root / "ordinary")
            with self.assertRaisesRegex(EvidenceError, "campaign-root-path"):
                files.campaign_inventory(child / "..")
            original_lstat = Path.lstat
            def observed(path):
                return (SimpleNamespace(st_mode=stat.S_IFDIR | 0o700,
                                        st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT) if path == root
                        else original_lstat(path))
            with patch.object(Path, "lstat", observed), self.assertRaisesRegex(EvidenceError, "campaign-entry-type"):
                files.campaign_inventory(child)

    def test_changed_file_during_hash_does_not_return_a_mixed_inventory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "changing"
            target.write_bytes(b"before")
            original = files.fingerprint
            def changed(path, maximum):
                result = original(path, maximum)
                path.write_bytes(b"after-growth")
                return result
            with patch.object(files, "fingerprint", side_effect=changed), \
                 self.assertRaisesRegex(EvidenceError, "campaign-file-changed"):
                files.campaign_inventory(root)


if __name__ == "__main__":
    unittest.main()
