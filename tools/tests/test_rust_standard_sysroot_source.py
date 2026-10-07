"""Compiler-source capture bounds; no compiler/sysroot/profile execution."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import rust_standard_sysroot_source as profile
from tools.dev_workflow.common import DevError


class SysrootSourceCapture(unittest.TestCase):
    def source(self, entries=()):
        content = io.BytesIO()
        required = ('Cargo.toml', 'Cargo.lock', '.cargo/config.toml', 'std/Cargo.toml',
                    'core/Cargo.toml', 'alloc/Cargo.toml', 'sysroot/Cargo.toml')
        with tarfile.open(fileobj=content, mode='w') as archive:
            for name in required:
                member = tarfile.TarInfo(profile.PREFIX + name); member.size = 1
                archive.addfile(member, io.BytesIO(b'x'))
            for name, kind, data in entries:
                member = tarfile.TarInfo(profile.PREFIX + name); member.type = kind
                member.size = len(data) if kind == tarfile.REGTYPE else 0
                if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE): member.linkname = '../external'
                archive.addfile(member, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        content.seek(0)
        return tarfile.open(fileobj=content, mode='r:')

    def test_full_offline_workspace_roots_and_exact_member_bytes_are_required(self):
        with self.source((('std/src/x.rs', tarfile.REGTYPE, b'exact\x00data'),)) as source:
            result = profile.selected_library_entries(source)
        self.assertEqual(result['std/src/x.rs'], b'exact\x00data')
        self.assertEqual(len(result), 8)

    def test_traversal_absolute_alias_and_backslash_paths_reject_before_output(self):
        for name in ('../escape', '/absolute', 'std/./source', 'std//source', 'C:/source', 'std\\source'):
            with self.subTest(name=name), self.source(((name, tarfile.REGTYPE, b'x'),)) as source:
                with self.assertRaisesRegex(DevError, 'source-path'): profile.selected_library_entries(source)

    def test_links_special_entries_and_case_collisions_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.source((('std/x', kind, b''),)) as source:
                with self.assertRaisesRegex(DevError, 'regular-only'): profile.selected_library_entries(source)
        with self.source((('STD/Cargo.toml', tarfile.REGTYPE, b'x'),)) as source:
            with self.assertRaisesRegex(DevError, 'collision'): profile.selected_library_entries(source)

    def test_original_compiler_source_count_file_and_total_limits_fail_closed(self):
        with patch.object(profile, 'MAX_FILES', 6), self.source() as source:
            with self.assertRaisesRegex(DevError, 'entry-bound'): profile.selected_library_entries(source)
        with patch.object(profile, 'MAX_FILE_BYTES', 1), self.source((('std/x', tarfile.REGTYPE, b'xx'),)) as source:
            with self.assertRaisesRegex(DevError, 'entry-bound'): profile.selected_library_entries(source)
        with patch.object(profile, 'MAX_BYTES', 6), self.source() as source:
            with self.assertRaisesRegex(DevError, 'total-bound'): profile.selected_library_entries(source)

    def test_missing_workspace_root_cannot_be_called_complete_source(self):
        content = io.BytesIO()
        with tarfile.open(fileobj=content, mode='w') as source:
            item = tarfile.TarInfo(profile.PREFIX + 'Cargo.toml'); item.size = 1; source.addfile(item, io.BytesIO(b'x'))
        content.seek(0)
        with tarfile.open(fileobj=content, mode='r:') as source:
            with self.assertRaisesRegex(DevError, 'closure-missing'): profile.selected_library_entries(source)

    def test_unapproved_archive_cannot_stage_or_install_sysroot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); archive = root / 'bad'; archive.write_bytes(b'unapproved')
            output = root / 'new'
            with self.assertRaisesRegex(DevError, 'archive-pin'): profile.prepare(archive, output)
            self.assertFalse(output.exists())

    def test_host_target_or_unpinned_compiler_rejects_before_archive_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target, rust in (('x86_64-unknown-linux-gnu', '1.97.1'), ('wasm32-wasip3', '1.97.1'),
                                 ('wasm32-unknown-unknown', 'nightly')):
                with self.subTest(target=target), self.assertRaisesRegex(DevError, 'not-maintained'):
                    profile.prepare(root / 'absent', root / 'new', target=target, rust=rust)
                self.assertFalse((root / 'new').exists())

    def test_original_executable_modes_are_separate_from_immutable_source_bytes(self):
        modes = {}
        with self.source((('vendor/tool.sh', tarfile.REGTYPE, b'exact'),)) as source:
            members = source.getmembers()
            for entry in members:
                if entry.name.endswith('/vendor/tool.sh'): entry.mode = 0o755
            source.members = members
            result = profile.selected_library_entries(source, modes=modes)
        self.assertEqual(result['vendor/tool.sh'], b'exact')
        self.assertEqual(modes['vendor/tool.sh'], 0o755)
        self.assertEqual(modes['std/Cargo.toml'], 0o644)


if __name__ == '__main__': unittest.main()
