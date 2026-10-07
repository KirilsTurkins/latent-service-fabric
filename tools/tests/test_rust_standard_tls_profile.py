"""Actual pinned std TLS source/preimage/selection checks, no guest claim."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import rust_standard_tls_profile as profile
from tools.dev_workflow.common import DevError

ROOT = Path(__file__).resolve().parents[2]


class StandardTlsSource(unittest.TestCase):
    def originals(self):
        return {name: (ROOT / 'sdk/rust-standard-runtime/upstream' / name).read_bytes()
                for name in profile.ORIGINALS}

    def tls(self): return (ROOT / 'sdk/rust-standard-runtime/tls.rs').read_bytes()

    def recipe(self): return {name: (ROOT / name).read_bytes() for name in profile.RECIPE}

    def test_exact_pinned_preimages_and_three_selectors_preserve_all_other_target_bytes(self):
        original = self.originals(); before = dict(original)
        selected = profile.overlay(original, self.tls())
        self.assertEqual(original, before)
        self.assertEqual(set(selected), {'std/src/sys/thread_local/mod.rs', 'std/src/sys/thread_local/key/lsf.rs'})
        restored = selected['std/src/sys/thread_local/mod.rs']
        for before, after in reversed(profile.BRANCHES):
            self.assertEqual(restored.count(after), 1)
            restored = restored.replace(after, before, 1)
        self.assertEqual(restored, original['std/src/sys/thread_local/mod.rs'])
        for name, data in original.items(): self.assertEqual(hashlib.sha256(data).hexdigest(), profile.ORIGINALS[name])

    def test_changed_upstream_tls_or_runtime_cleanup_preimage_rejects_before_selection(self):
        for name in profile.ORIGINALS:
            original = self.originals(); original[name] += b'\n'
            with self.subTest(name=name), self.assertRaisesRegex(DevError, 'original-preimage'):
                profile.overlay(original, self.tls())

    def test_missing_original_cannot_emit_a_partial_profile(self):
        original = self.originals(); original.pop('std/src/rt.rs')
        with self.assertRaisesRegex(DevError, 'original-set'): profile.overlay(original, self.tls())

    def test_unchanged_os_storage_preserves_alignment_initializer_and_destroying_rules(self):
        original = self.originals(); selected = profile.overlay(original, self.tls())
        self.assertNotIn('std/src/sys/thread_local/os.rs', selected)
        source = original['std/src/sys/thread_local/os.rs']
        for part in (b'Layout::new::<Value<T>>().align_to(ALIGN)', b'i.and_then(Option::take).unwrap_or_else(f)',
                     b'if ptr.addr() == 1', b'guard::enable()', b'System.dealloc'):
            self.assertIn(part, source)

    def test_process_global_no_threads_storage_is_not_selected_for_maintained_profile(self):
        original = self.originals(); selected = profile.overlay(original, self.tls())
        self.assertIn(b'static __RUST_STD_INTERNAL_VAL', original['std/src/sys/thread_local/no_threads.rs'])
        first = selected['std/src/sys/thread_local/mod.rs'].split(b'    any(', 1)[0]
        self.assertIn(b'mod os;', first)
        self.assertNotIn(b'mod no_threads;', first)
        self.assertIn(b'[context-get-1]', self.tls()); self.assertIn(b'[context-set-1]', self.tls())
        self.assertNotIn(b'[context-get-0]', self.tls()); self.assertNotIn(b'#[thread_local]', self.tls())

    def test_current_selected_compiler_engine_and_bindgen_pins_are_required(self):
        inputs = self.recipe(); profile.tool_pins(inputs)
        for name, before, after in (('rust-toolchain.toml', b'1.97.1', b'1.97.2'),
                                   ('Cargo.toml', b'=48.0.4', b'=48.0.5'),
                                   ('Cargo.toml', b'=0.62.0', b'=0.63.0'),
                                   ('Cargo.lock', profile.PINS['wasmtime'][1].encode(), b'0' * 64)):
            altered = dict(inputs); self.assertIn(before, altered[name]); altered[name] = altered[name].replace(before, after)
            with self.subTest(name=name), self.assertRaises(DevError): profile.tool_pins(altered)

    def test_runtime_wit_change_invalidates_the_observed_canonical_abi_contract(self):
        inputs = self.recipe(); inputs['wit/platform/activation-runtime/package.wit'] += b'\n'
        with self.assertRaisesRegex(DevError, 'canonical-abi-preimage'): profile.tool_pins(inputs)

    def test_canonical_return_area_matches_real_pinned_generator_reference(self):
        abi = json.loads(self.recipe()['sdk/rust-standard-runtime/activation-abi.json'])
        self.assertEqual(abi['ownerKindNative'], 7)
        self.assertEqual(abi['register']['flatParameters'], ['i32', 'i32', 'i64', 'i64', 'pointer32'])
        self.assertEqual((abi['register']['returnBytes'], abi['register']['returnAlignment']), (24, 8))
        self.assertEqual((abi['register']['discriminantOffset'], abi['register']['generationOffset'], abi['register']['idOffset'], abi['register']['errorOffset']), (0, 8, 16, 8))
        self.assertEqual((abi['settle']['returnBytes'], abi['settle']['returnAlignment'], abi['settle']['errorOffset']), (2, 1, 1))
        self.assertEqual(abi['generator']['version'], 'wit-bindgen-cli 0.62.0')
        self.assertFalse(abi['rebuiltSysrootOrGuestQualified'])

    def test_other_target_or_compiler_rejects_before_read_or_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'new'
            for target, rust in (('x86_64-unknown-linux-gnu', '1.97.1'), ('wasm32-wasip2', '1.97.1'),
                                 ('wasm32-unknown-unknown', 'nightly')):
                with self.subTest(target=target), self.assertRaisesRegex(DevError, 'not-maintained'):
                    profile.prepare(Path(directory) / 'absent', output, target=target, rust=rust)
                self.assertFalse(output.exists())

    def test_unapproved_archive_never_creates_an_overlay_or_installs_sysroot(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'source'; archive.write_bytes(b'unapproved')
            output = Path(directory) / 'overlay'
            with self.assertRaisesRegex(DevError, 'archive-pin'): profile.prepare(archive, output)
            self.assertFalse(output.exists())

    def test_thread_creation_and_single_thread_mutex_remain_explicitly_unqualified(self):
        thread = (ROOT / 'sdk/rust-standard-runtime/upstream/std/src/sys/thread/unsupported.rs').read_bytes()
        mutex = (ROOT / 'sdk/rust-standard-runtime/upstream/std/src/sys/sync/mutex/no_threads.rs').read_bytes()
        self.assertIn(b'Err(io::Error::UNSUPPORTED_PLATFORM)', thread)
        self.assertIn(b'locked: Cell<bool>', mutex)
        selected = profile.overlay(self.originals(), self.tls())
        self.assertNotIn('std/src/sys/thread/unsupported.rs', selected)
        self.assertNotIn('std/src/sys/sync/mutex/no_threads.rs', selected)


if __name__ == '__main__': unittest.main()
