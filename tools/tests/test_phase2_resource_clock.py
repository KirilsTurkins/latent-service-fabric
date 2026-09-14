"""Bounded renewal descriptors must not hide unrelated retained resources."""
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.phase2_gate_resource_os import clock_lease_descriptor
from tools.phase2_gate_resource_profile import validate_receipt
from tools.phase2_operator_process import WorkflowError
from tools.tests.test_phase2_gate_resource import complete_receipt


class ClockDescriptorTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "requires real Linux descriptor observations")
    def test_live_linux_renewal_files_are_classified_and_lock_is_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            ledger = Path(temporary).resolve()
            (ledger / "INITIALIZED").write_bytes(b"lsf-admission-authority-v1\n")
            (ledger / ".authority.lock").touch()
            root = Path(f"/proc/{os.getpid()}")
            for name, flags, expected in (("", os.O_RDONLY, 1),
                                          ("INITIALIZED", os.O_RDONLY, 1),
                                          ("floor.pending.json", os.O_CREAT | os.O_WRONLY, 1),
                                          (".authority.lock", os.O_RDWR, 0)):
                fd = os.open(ledger / name, flags, 0o600)
                try:
                    entry = SimpleNamespace(name=str(fd), path=str(root / "fd" / str(fd)))
                    target = os.readlink(entry.path)
                    self.assertEqual(clock_lease_descriptor(
                        root, entry, target, lambda path: path.read_text(), ledger), expected)
                finally:
                    os.close(fd)

    def test_accounting_preserves_raw_counts_and_rejects_unrelated_growth(self):
        value = complete_receipt()
        observed = value["samples"][7]["os"]
        observed.update(fdCount=13, clockLeaseFdCount=1)
        validate_receipt(value)
        self.assertEqual(observed["fdCount"], 13)
        observed["fdCount"] = 14
        with self.assertRaisesRegex(WorkflowError, "receipt-topology-growth"):
            validate_receipt(value)
        for clock, sampler in ((2, 0), (1, 1)):
            observed.update(clockLeaseFdCount=clock, loadSamplerFdCount=sampler)
            with self.assertRaisesRegex(WorkflowError, "receipt-clock-bound"):
                validate_receipt(value)

    def test_exact_renewal_paths_flags_types_and_inodes_are_required(self):
        root, ledger = Path("/proc/42"), Path("/owned/node/data/supply-chain")
        entry = SimpleNamespace(name="7", path="/proc/42/fd/7")
        for name, mode, access in (("", stat.S_IFDIR, 0),
                                   ("floor.pending.json", stat.S_IFREG, 1),
                                   ("INITIALIZED", stat.S_IFREG, 0)):
            target = str(ledger / name)
            info = SimpleNamespace(st_dev=1, st_ino=2, st_mode=mode, st_size=24)
            with patch.object(os, "readlink", return_value=target), \
                    patch.object(os, "stat", return_value=info):
                self.assertEqual(clock_lease_descriptor(
                    root, entry, target, lambda _: f"flags: {access:o}\n", ledger), 1)
                for invalid in ("flags: 2", "flags: invalid", "flags: 0\nflags: 0"):
                    with self.subTest(name=name, flags=invalid), self.assertRaises(WorkflowError):
                        clock_lease_descriptor(root, entry, target, lambda _: invalid, ledger)
                with patch.object(os, "readlink", return_value="/replaced"):
                    with self.assertRaisesRegex(WorkflowError, "proc-clock-descriptor"):
                        clock_lease_descriptor(root, entry, target,
                                               lambda _: f"flags: {access:o}", ledger)
                changed = SimpleNamespace(st_dev=1, st_ino=3, st_mode=mode, st_size=24)
                with patch.object(os, "stat", side_effect=[info, changed]):
                    with self.assertRaisesRegex(WorkflowError, "proc-clock-descriptor"):
                        clock_lease_descriptor(root, entry, target,
                                               lambda _: f"flags: {access:o}", ledger)

    def test_unknown_paths_oversized_files_and_sockets_are_not_exempt(self):
        root, ledger = Path("/proc/42"), Path("/owned/node/data/supply-chain")
        entry = SimpleNamespace(name="7", path="/proc/42/fd/7")
        for path in (ledger / "floor.json", ledger / ".authority.lock",
                     ledger / "unexpected", Path("/other/floor.pending.json")):
            self.assertEqual(clock_lease_descriptor(root, entry, str(path),
                             lambda _: self.fail("unrelated descriptor read"), ledger), 0)
        target = str(ledger / "floor.pending.json")
        for mode, size in ((stat.S_IFREG, 4097), (stat.S_IFSOCK, 0), (stat.S_IFDIR, 0)):
            info = SimpleNamespace(st_dev=1, st_ino=2, st_mode=mode, st_size=size)
            with patch.object(os, "stat", return_value=info), \
                    patch.object(os, "readlink", return_value=target):
                with self.assertRaisesRegex(WorkflowError, "proc-clock-descriptor"):
                    clock_lease_descriptor(root, entry, target, lambda _: "flags: 1", ledger)
