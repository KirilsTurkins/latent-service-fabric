"""One anchored source read retains platform-specific substitution guards."""
from contextlib import contextmanager, ExitStack
import os
from pathlib import Path
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.dev_workflow import common, paths


class PosixAnchorControl(unittest.TestCase):
    @contextmanager
    def controlled(self, metadata=None):
        root = Path.cwd()
        walks, active, leaves, events = [], [], [], []
        @contextmanager
        def directory(parent):
            self.assertEqual(parent, root / "source")
            descriptor = 100 + len(walks)
            walks.append(parent)
            active.append(descriptor)
            try:
                yield descriptor
            finally:
                self.assertEqual(active.pop(), descriptor)
                events.append(("parent-closed", descriptor))
        def opened(name, flags, *, dir_fd):
            self.assertEqual(name, "input")
            self.assertIn(dir_fd, active)
            self.assertEqual(flags, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            leaves.append(dir_fd)
            return 200
        def closed(descriptor):
            self.assertEqual(descriptor, 200)
            self.assertTrue(active)
            events.append(("leaf-closed", descriptor))
        with ExitStack() as stack:
            stack.enter_context(patch.object(paths.os, "name", "posix"))
            for name, fallback in (("O_NOFOLLOW", 0x100000), ("O_NONBLOCK", 0x200000), ("O_CLOEXEC", 0x400000)):
                stack.enter_context(patch.object(paths.os, name, getattr(os, name, fallback), create=True))
            stack.enter_context(patch.object(paths, "directory", directory))
            stack.enter_context(patch.object(paths.os, "open", opened))
            stack.enter_context(patch.object(paths.os, "close", closed))
            stack.enter_context(patch.object(paths.os, "fstat", return_value=metadata or
                SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_nlink=1)))
            yield root, walks, active, leaves, events

    def test_posix_read_walks_parent_once_and_uses_that_held_anchor(self):
        with self.controlled() as (root, walks, active, leaves, events):
            with paths.opened(root, "source/input") as descriptor:
                self.assertEqual(descriptor, 200)
                self.assertEqual(len(walks), 1)
                self.assertEqual(leaves, active)
            self.assertEqual(events, [("leaf-closed", 200), ("parent-closed", 100)])

    def test_caller_failure_closes_leaf_before_releasing_parent(self):
        original = RuntimeError("owned caller failure")
        with self.controlled() as (root, walks, active, leaves, events):
            with self.assertRaises(RuntimeError) as raised:
                with paths.opened(root, "source/input"):
                    raise original
            self.assertIs(raised.exception, original)
            self.assertFalse(active)
            self.assertEqual(events[-2:], [("leaf-closed", 200), ("parent-closed", 100)])

    def test_invalid_leaf_metadata_still_rejects_and_closes_descriptor(self):
        for mode, links, attributes, reason in (
                (stat.S_IFDIR, 1, 0, "single-link-regular-file-required"),
                (stat.S_IFREG, 2, 0, "single-link-regular-file-required"),
                (stat.S_IFREG, 0, 0, "source-changed-during-read"),
                (stat.S_IFREG, 1, 0x400, "reparse-point-rejected")):
            with self.subTest(reason=reason, links=links), self.controlled(SimpleNamespace(
                    st_mode=mode, st_nlink=links, st_file_attributes=attributes)) as controlled:
                root, walks, active, leaves, events = controlled
                with self.assertRaisesRegex(common.DevError, "^" + reason + "$"):
                    with paths.opened(root, "source/input"):
                        self.fail("unsafe source descriptor was yielded")
                self.assertFalse(active)
                self.assertIn(("leaf-closed", 200), events)


class RealSourceAnchors(unittest.TestCase):
    @unittest.skipUnless(os.name == "posix", "POSIX no-follow source anchors")
    def test_leaf_and_parent_symlinks_remain_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").mkdir()
            (root / "source/input").write_bytes(b"original")
            (root / "source/link").symlink_to("input")
            (root / "alias").symlink_to("source", target_is_directory=True)
            for name in ("source/link", "alias/input"):
                with self.subTest(name=name), self.assertRaisesRegex(common.DevError, "source-file-unavailable-or-unsafe"):
                    paths.read(root, name)

    @unittest.skipUnless(os.name == "posix", "POSIX parent rename preserves descriptor authority")
    def test_parent_substitution_cannot_redirect_the_anchored_leaf_open(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name, raw in (("source", b"original"), ("foreign", b"must-not-read")):
                (root / name).mkdir()
                (root / name / "input").write_bytes(raw)
            original_open = os.open
            def substitute(name, *args, **kwargs):
                if name == "input" and "dir_fd" in kwargs:
                    (root / "source").rename(root / "retained")
                    (root / "source").symlink_to("foreign", target_is_directory=True)
                return original_open(name, *args, **kwargs)
            with patch.object(paths.os, "open", substitute):
                self.assertEqual(paths.read(root, "source/input"), b"original")
            self.assertEqual((root / "foreign/input").read_bytes(), b"must-not-read")
            with self.assertRaisesRegex(common.DevError, "source-file-unavailable-or-unsafe"):
                paths.read(root, "source/input")

    @unittest.skipUnless(os.name == "nt", "Windows ancestor and leaf rename guards")
    def test_windows_read_retains_ancestor_and_leaf_rename_guards(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").mkdir()
            (root / "source/input").write_bytes(b"original")
            with paths.opened(root, "source/input") as descriptor:
                self.assertEqual(os.read(descriptor, 8), b"original")
                with self.assertRaises(PermissionError):
                    (root / "source").rename(root / "moved")
                with self.assertRaises(PermissionError):
                    (root / "source/input").rename(root / "source/moved")
            (root / "source").rename(root / "moved")
            self.assertEqual((root / "moved/input").read_bytes(), b"original")
