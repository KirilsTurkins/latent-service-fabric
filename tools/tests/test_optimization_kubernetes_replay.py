"""Actual small tar bytes test the offline transfer boundary; no workloads."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from tools.optimization_evidence.common import EvidenceError, sha256
from tools.optimization_kubernetes.replay import _tar


class TransferReplayTests(unittest.TestCase):
    def archive(self, directory, entries):
        path = directory / "original.tar"
        with tarfile.open(path, "w", format=tarfile.USTAR_FORMAT) as archive:
            for name, kind, mode, content in entries:
                member = tarfile.TarInfo(name)
                member.mode = mode
                if kind == "directory":
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
                else:
                    member.size = len(content)
                    archive.addfile(member, io.BytesIO(content))
        return path

    def inventory(self):
        return {"bytes": "3", "entries": [{"path": ".", "kind": "directory", "mode": "0700"},
            {"path": "file", "kind": "file", "mode": "0600", "bytes": "3", "sha256": sha256(b"raw")}]}

    def test_upload_and_download_original_bytes_and_modes_are_bound(self):
        for root in (None, "owner"):
            with self.subTest(root=root), tempfile.TemporaryDirectory() as value:
                entries = [] if root is None else [(root, "directory", 0o700, b"")]
                entries.append(((root + "/" if root else "") + "file", "file", 0o600, b"raw"))
                path = self.archive(Path(value), entries)
                before = path.read_bytes()
                _tar(path, self.inventory(), root_name=root)
                self.assertEqual(path.read_bytes(), before)
                self.assertEqual(list(Path(value).iterdir()), [path])

    def test_wrong_bytes_or_mode_cannot_replay(self):
        for mode, data in ((0o600, b"bad"), (0o644, b"raw")):
            with self.subTest(mode=mode, data=data), tempfile.TemporaryDirectory() as value:
                path = self.archive(Path(value), [("file", "file", mode, data)])
                with self.assertRaises(EvidenceError):
                    _tar(path, self.inventory())

    def test_duplicate_missing_and_foreign_members_cannot_replay(self):
        for names in (("file", "file"), (), ("file", "../elsewhere"), ("other",)):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as value:
                path = self.archive(Path(value), [(name, "file", 0o600, b"raw") for name in names])
                with self.assertRaises(EvidenceError):
                    _tar(path, self.inventory())

    def test_download_cannot_borrow_another_owner_root(self):
        with tempfile.TemporaryDirectory() as value:
            path = self.archive(Path(value), [("foreign", "directory", 0o700, b""),
                                              ("foreign/file", "file", 0o600, b"raw")])
            with self.assertRaises(EvidenceError):
                _tar(path, self.inventory(), root_name="owner")


if __name__ == "__main__":
    unittest.main()
