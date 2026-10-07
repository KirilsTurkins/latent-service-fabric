"""Pinned std source transformation controls; no guest/sysroot qualification."""
import hashlib
from pathlib import Path
import tempfile
import unittest

from tools import rust_standard_clock_profile as profile
from tools.dev_workflow.common import DevError

ROOT = Path(__file__).resolve().parents[2]


class StandardClockSource(unittest.TestCase):
    def originals(self):
        return {name: (ROOT / 'sdk/rust-standard-runtime/upstream' / name).read_bytes() for name in profile.ORIGINALS}

    def clock(self): return (ROOT / 'sdk/rust-standard-runtime/clock.rs').read_bytes()

    def test_real_pinned_originals_remain_exact_and_only_clock_selector_and_module_are_transformed(self):
        original = self.originals(); before = dict(original)
        selected = profile.overlay(original, self.clock())
        self.assertEqual(original, before)
        self.assertEqual(set(selected), {'std/src/sys/time/mod.rs', 'std/src/sys/time/lsf.rs'})
        self.assertEqual(selected['std/src/sys/time/lsf.rs'], self.clock())
        self.assertIn(b'mod unsupported;', selected['std/src/sys/time/mod.rs'])
        self.assertIn(b'all(target_arch = "wasm32", target_os = "unknown", target_vendor = "unknown", target_env = "")',
                      selected['std/src/sys/time/mod.rs'])
        for name, raw in original.items():
            self.assertEqual(hashlib.sha256(raw).hexdigest(), profile.ORIGINALS[name])

    def test_changed_upstream_selector_or_thread_or_mutex_preimage_is_rejected(self):
        for name in profile.ORIGINALS:
            original = self.originals(); original[name] += b'\n'
            with self.subTest(name=name), self.assertRaisesRegex(DevError, 'original-preimage'):
                profile.overlay(original, self.clock())

    def test_missing_originals_cannot_create_a_partial_preimage_receipt(self):
        original = self.originals(); original.pop('std/src/sys/thread/unsupported.rs')
        with self.assertRaisesRegex(DevError, 'original-set'): profile.overlay(original, self.clock())

    def test_clock_pal_keeps_exact_host_units_and_every_original_arithmetic_method(self):
        raw = self.clock()
        self.assertIn(b'wasm_import_module = "latent:clock/monotonic@0.1.0"', raw)
        self.assertIn(b'link_name = "now-nanos"', raw)
        self.assertIn(b'Duration::from_nanos(unsafe { lsf_std_monotonic_now_nanos() })', raw)
        self.assertIn(b'link_name = "now-unix-millis"', raw)
        self.assertIn(b'Duration::from_millis(unsafe { lsf_std_wall_now_unix_millis() })', raw)
        # Compare real pinned arithmetic bodies rather than a second hand-coded
        # implementation. Only now() and new import declarations may differ.
        original = self.originals()['std/src/sys/time/unsupported.rs'].decode()
        selected = raw.decode()
        for name in ('checked_sub_instant', 'checked_add_duration', 'checked_sub_duration', 'sub_time'):
            import re
            pattern = r'    pub fn ' + name + r'\([^}]+?\n    }'
            self.assertEqual(re.findall(pattern, original), re.findall(pattern, selected))

    def test_thread_creation_and_sleep_are_never_replaced_by_inline_or_completed_stubs(self):
        original = self.originals()['std/src/sys/thread/unsupported.rs']
        self.assertIn(b'Err(io::Error::UNSUPPORTED_PLATFORM)', original)
        self.assertIn(b'panic!("can\'t sleep")', original)
        self.assertNotIn('std/src/sys/thread/unsupported.rs', profile.overlay(self.originals(), self.clock()))
        self.assertIn('std::thread::Builder::spawn', profile.UNQUALIFIED)
        self.assertIn('std::thread::sleep', profile.UNQUALIFIED)

    def test_no_threads_cell_mutex_is_not_advertised_as_concurrent_synchronization(self):
        original = self.originals()['std/src/sys/sync/mutex/no_threads.rs']
        self.assertIn(b'locked: Cell<bool>', original)
        self.assertNotIn('std/src/sys/sync/mutex/no_threads.rs', profile.overlay(self.originals(), self.clock()))
        self.assertIn('std::sync blocking mutex/condvar/channel', profile.UNQUALIFIED)

    def test_unmaintained_targets_and_compilers_reject_before_reading_or_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output'
            for target, rust in (('x86_64-unknown-linux-gnu', '1.97.1'), ('wasm32-wasip2', '1.97.1'),
                                 ('wasm32-unknown-unknown', 'nightly')):
                with self.subTest(target=target), self.assertRaisesRegex(DevError, 'not-maintained'):
                    profile.prepare(Path(directory) / 'absent', output, target=target, rust=rust)
                self.assertFalse(output.exists())

    def test_unapproved_archive_hash_fails_without_an_overlay_or_installed_sysroot(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'wrong'; archive.write_bytes(b'unapproved source')
            output = Path(directory) / 'overlay'
            with self.assertRaisesRegex(DevError, 'archive-pin'): profile.prepare(archive, output)
            self.assertFalse(output.exists())


if __name__ == '__main__': unittest.main()
