"""Completed splicer receipt extraction; no acquisition or compiler execution."""
import io
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from tools.phase2_operator_process import WorkflowError
from tools.typescript_borrow_splicer_inputs import COMPLETED_RECEIPTS, complete_members, extract_complete, unpack_complete
from tools.typescript_fetch_replay_inputs import members


def fixture():
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, 'w') as archive:
        for name in sorted(COMPLETED_RECEIPTS | {'splicer/module.js', 'splicer/core.wasm', 'compiler-inputs.json'}):
            archive.writestr(name, b'owned-fixture')
    return raw.getvalue()


class CompleteBorrowSplicerTests(unittest.TestCase):
    def test_complete_projection_keeps_original_modules_and_all_five_receipts(self):
        with zipfile.ZipFile(io.BytesIO(fixture())) as archive, tempfile.TemporaryDirectory() as temporary:
            original = {row.filename for row in members('splicer', archive.infolist())}
            self.assertEqual(COMPLETED_RECEIPTS - original, COMPLETED_RECEIPTS - {'splicer-input.json'})
            selected = extract_complete(archive, Path(temporary) / 'selected')
            self.assertEqual(set(selected), original | COMPLETED_RECEIPTS)
            self.assertNotIn('compiler-inputs.json', selected)
            for name in selected:
                self.assertEqual((Path(temporary) / 'selected' / name).read_bytes(), b'owned-fixture')

    def test_missing_link_encrypted_or_oversized_receipt_refuses_before_writes(self):
        for mode in ('missing', 'link', 'encrypted', 'oversized'):
            with self.subTest(mode=mode), zipfile.ZipFile(io.BytesIO(fixture())) as archive, tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'selected'
                if mode == 'missing':
                    entries = [row for row in archive.infolist() if row.filename != 'splicer-build.json']
                    with self.assertRaises(WorkflowError):
                        complete_members(entries)
                else:
                    row = archive.getinfo('splicer-build.json')
                    if mode == 'link': row.external_attr = (stat.S_IFLNK | 0o777) << 16
                    elif mode == 'encrypted': row.flag_bits |= 1
                    else: row.file_size = 16*1024**2 + 1
                    with self.assertRaises(WorkflowError):
                        extract_complete(archive, output)
                self.assertFalse(output.exists())

    def test_changed_whole_archive_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'selected'
            with self.assertRaisesRegex(WorkflowError, 'tracking-whole-archive'):
                unpack_complete(b'not-the-frozen-archive', output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
