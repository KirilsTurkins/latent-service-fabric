"""Small static proc/cgroup fixtures; no cgroups are created or modified."""
import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from optimization_runner import cgroups


def mount(root="/", point="/sys/fs/cgroup", device="0:27", identifier="22"):
    return f"{identifier} 1 {device} {root} {point} rw,nosuid shared:1 - cgroup2 cgroup rw\n"


class CgroupResolutionTests(unittest.TestCase):
    def test_native_nested_bind_subtree_and_namespace_root(self):
        for membership, root, expected in (
            ("/user.slice/job.scope", "/", "/sys/fs/cgroup/user.slice/job.scope"),
            ("/docker/id/job", "/docker/id", "/sys/fs/cgroup/job"),
            ("/", "/", "/sys/fs/cgroup"),
        ):
            with self.subTest(membership=membership):
                result = cgroups.resolve_candidates(f"0::{membership}\n", mount(root))
                self.assertEqual(result[0]["path"], expected)

    def test_paths_use_component_prefix_and_decode_escapes_once(self):
        self.assertEqual(cgroups.resolve_candidates("0::/foobar\n", mount("/foo")), [])
        result = cgroups.resolve_candidates("0::/job\n", mount(point=r"/cg\040space\134040"))
        self.assertEqual(result[0]["path"], "/cg space\\040/job")
        entries = mount() + mount("/job", "/bound", identifier="23")
        self.assertEqual(cgroups.resolve_candidates("0::/job\n", entries)[0]["mount_point"], "/bound")

    def test_bad_or_unresolvable_membership_never_becomes_mount_root(self):
        for membership, mounts in (
            ("0::/../job\n", mount()), ("0::/a\n0::/b\n", mount()),
            ("0::/a\nmalformed\n", mount()), ("0::/job\n", mount("/..")),
            ("0::relative\n", mount()), ("0::/\n", "truncated"),
            ("0::/\n", mount(point=r"/bad\099escape")),
        ):
            with self.subTest(membership=membership, mounts=mounts):
                with self.assertRaises(cgroups.ProbeError):
                    cgroups.resolve_candidates(membership, mounts)
        self.assertEqual(cgroups.resolve_candidates("0::/\n", ""), [])
        with self.assertRaisesRegex(cgroups.ProbeError, "oversized"):
            cgroups.resolve_candidates("0::/" + "x" * cgroups.MEMBERSHIP_BYTES, mount())


@unittest.skipUnless(os.name == "posix", "directory-FD Linux probe fixtures")
class CgroupReadTests(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory)
        proc = root / "proc"
        group = root / "group"
        proc.mkdir()
        group.mkdir()
        device = group.stat().st_dev
        device = f"{os.major(device)}:{os.minor(device)}"
        (proc / "cgroup").write_text("0::/nested\n")
        (proc / "mountinfo").write_text(mount("/nested", str(group), device))
        return proc, group

    def test_reads_resolved_directory_and_distinguishes_missing_oversized_denied(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, group = self.fixture(directory)
            (group / "cpu.max").write_text("10000 100000\n")
            (group / "memory.stat").write_bytes(b"x" * (cgroups.CONTROLLER_BYTES + 1))
            original = cgroups._read
            def read(path, maximum, **kwargs):
                if path == "cpu.stat":
                    raise PermissionError(errno.EACCES, "not exported")
                return original(path, maximum, **kwargs)
            with patch.object(cgroups, "_read", side_effect=read):
                result = cgroups.cgroup(proc_root=proc)
            self.assertEqual(result["resolution"]["status"], "resolved")
            self.assertEqual(result["resolution"]["path"], str(group))
            self.assertEqual(result["resolution"]["inode"], str(group.stat().st_ino))
            self.assertEqual(result["cpu.max"], "10000 100000\n")
            self.assertEqual(result["errors"]["cpu.stat"], "permission-denied")
            self.assertEqual(result["errors"]["memory.stat"], "oversized")
            self.assertEqual(result["errors"]["memory.current"], "missing")
            self.assertIsNone(result["memory.current"])

    def test_nonregular_files_do_not_block_and_membership_change_discards_values(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, group = self.fixture(directory)
            os.mkfifo(group / "cpu.stat")
            (group / "cpu.max").write_text("max 100000\n")
            result = cgroups.cgroup(proc_root=proc)
            self.assertEqual(result["errors"]["cpu.stat"], "invalid")
            original = cgroups._read
            reads = 0
            def read(path, maximum, **kwargs):
                nonlocal reads
                if path == proc / "cgroup":
                    reads += 1
                    if reads == 2:
                        return "0::/moved\n"
                return original(path, maximum, **kwargs)
            with patch.object(cgroups, "_read", side_effect=read):
                changed = cgroups.cgroup(proc_root=proc)
            self.assertEqual(changed["resolution"]["status"], "unsupported")
            self.assertEqual(changed["errors"]["resolution"], "membership-changed")
            self.assertTrue(all(changed[name] is None for name in cgroups.FILES))

    def test_unavailable_membership_and_wrong_filesystem_never_fall_back(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = cgroups.cgroup(proc_root=Path(directory))
            self.assertEqual(missing["errors"]["process_membership"], "missing")
            self.assertEqual(missing["resolution"]["status"], "unsupported")
            proc, group = self.fixture(directory)
            (proc / "mountinfo").write_text(mount("/nested", str(group), "999:999"))
            wrong = cgroups.cgroup(proc_root=proc)
            self.assertEqual(wrong["errors"]["resolution"], "invalid")
            self.assertTrue(all(wrong[name] is None for name in cgroups.FILES))

    def test_aliases_must_have_same_directory_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            proc, group = self.fixture(directory)
            other = Path(directory) / "other"
            other.mkdir()
            device = group.stat().st_dev
            mounts = (proc / "mountinfo").read_text()
            mounts += mount("/nested", str(other), f"{os.major(device)}:{os.minor(device)}", "23")
            (proc / "mountinfo").write_text(mounts)
            result = cgroups.cgroup(proc_root=proc)
            self.assertEqual(result["errors"]["resolution"], "ambiguous")
            self.assertEqual(result["resolution"]["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
