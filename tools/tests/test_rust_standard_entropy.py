"""Exact source refusals and native scalar semantics; not signed qualification."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest

from tools import rust_standard_entropy_profile as entropy
from tools.dev_workflow.common import DevError
from tools.rust_capsule_project import ROOT
from tools.application_dependency_store import Store
from tools.build_snapshot import canonical, digest
from tools import rust_standard_logging_inputs as runtime


class StandardEntropy(unittest.TestCase):
    def originals(self):
        return {name: (ROOT / 'sdk/rust-standard-runtime/upstream' / name).read_bytes()
                for name in entropy.ORIGINALS}

    def package(self):
        files = {name: (ROOT / 'sdk/rust-standard-runtime/upstream/getrandom-0.3.4' / name).read_bytes()
                 for name in entropy.GETRANDOM['originals']}
        checksum = {'package': entropy.GETRANDOM['archiveSha256'],
                    'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}}
        files['.cargo-checksum.json'] = json.dumps(checksum).encode()
        return files

    def test_exact_std_overlay_retains_unselected_platforms_and_original_unsupported_source(self):
        original = self.originals()
        changed = entropy.overlay(original, entropy.recipe())
        self.assertEqual(set(changed), {'std/src/sys/random/mod.rs', 'std/src/sys/random/lsf.rs'})
        selector = changed['std/src/sys/random/mod.rs']
        before = original['std/src/sys/random/mod.rs']
        branch = b'    ' + entropy.SELECTOR + b' => {\n        mod lsf;\n        pub use lsf::{fill_bytes, hashmap_random_keys};\n    }\n'
        self.assertEqual(selector.count(branch), 1)
        self.assertEqual(selector.replace(branch, b'', 1), before)
        self.assertIn(b'approved_fill(destination).expect', changed['std/src/sys/random/lsf.rs'])

    def test_changed_or_missing_std_preimages_fail_before_derivation(self):
        for name in entropy.ORIGINALS:
            original = self.originals()
            original[name] += b'changed'
            with self.assertRaisesRegex(DevError, 'std-preimage'):
                entropy.overlay(original, entropy.recipe())
        with self.assertRaisesRegex(DevError, 'original-set'):
            entropy.overlay({}, entropy.recipe())

    def test_runtime_backend_preserves_explicit_choices_and_authenticates_derived_vendor_checksums(self):
        files = self.package()
        changed = entropy.getrandom_overlay(files, entropy.recipe())
        self.assertEqual(set(changed), {'src/backends.rs', 'src/backends/custom.rs', '.cargo-checksum.json'})
        branch = b'    } else if #[cfg(' + entropy.SELECTOR + b')] {\n        mod custom;\n        pub use custom::*;\n'
        self.assertEqual(changed['src/backends.rs'].replace(branch, b'', 1), files['src/backends.rs'])
        before = files['src/backends.rs']
        self.assertLess(before.index(b'getrandom_backend = "unsupported"'),
                        changed['src/backends.rs'].index(branch))
        final = {**files, **changed}
        checksum = json.loads(changed['.cargo-checksum.json'])
        self.assertEqual(checksum['package'], entropy.GETRANDOM['archiveSha256'])
        self.assertEqual(checksum['files'], {name: hashlib.sha256(raw).hexdigest()
                         for name, raw in final.items() if name != '.cargo-checksum.json'})

    def test_runtime_source_or_original_vendor_identity_cannot_be_substituted(self):
        for name in entropy.GETRANDOM['originals']:
            files = self.package(); files[name] += b'changed'
            with self.assertRaisesRegex(DevError, 'getrandom-preimage'):
                entropy.getrandom_overlay(files, entropy.recipe())

        for field in ('package', 'files'):
            files = self.package(); value = json.loads(files['.cargo-checksum.json'])
            value[field] = '0' * 64 if field == 'package' else {}
            files['.cargo-checksum.json'] = json.dumps(value).encode()
            with self.assertRaisesRegex(DevError, 'vendor-checksum'):
                entropy.getrandom_overlay(files, entropy.recipe())


    def captured(self, root):
        files = self.package()
        files['Cargo.toml'] = b'[package]\nname="getrandom"\nversion="0.3.4"\n'
        checksum = json.loads(files['.cargo-checksum.json'])
        checksum['files']['Cargo.toml'] = digest(files['Cargo.toml'])[7:]
        files['.cargo-checksum.json'] = canonical(checksum)
        store = Store(root / 'objects')
        rows = [{'path': name, **store.put(raw)} for name, raw in sorted(files.items())]
        original = store.put(canonical(rows))
        row = {'id': 'captured-runtime', 'format': 'directory', 'original': original,
               'metadata': {'ecosystem': 'cargo', 'package': 'getrandom', 'version': '0.3.4',
                            'vendorChecksum': {'package': entropy.GETRANDOM['archiveSha256']}}}
        changes, selected = entropy.captured_changes(row, files, runtime.ENTROPY)
        row['files'] = [{'path': name, **store.put(raw)} for name, raw in sorted({**files, **changes}.items())]
        transform = {'artifact': row['id'], 'selection': {'runtimeEntropyPort': selected},
                     'changes': [{'path': name} for name in changes]}
        verified = SimpleNamespace(store=store, lock={'artifacts': [row], 'transformations': [transform]})
        return verified, row, transform

    def test_capture_reproduces_current_backend_bytes_from_original_cas(self):
        with tempfile.TemporaryDirectory() as temporary:
            verified, _, _ = self.captured(Path(temporary))
            entropy.verify_capture(verified, runtime.ENTROPY)
            entropy.verify_capture(verified, runtime.LOGGING_ENTROPY)
            with self.assertRaisesRegex(DevError, 'without-selected-profile'):
                entropy.verify_capture(verified, runtime.CLOSED)

    def test_stale_recipe_missing_port_or_substituted_selected_backend_refuses(self):
        for mode in ('recipe', 'missing', 'backend'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                verified, row, transform = self.captured(Path(temporary))
                if mode == 'recipe':
                    transform['selection']['runtimeEntropyPort']['recipeDigest'] = 'sha256:' + '0' * 64
                elif mode == 'missing':
                    transform['selection'] = {}
                else:
                    selected = next(item for item in row['files'] if item['path'] == 'src/backends/custom.rs')
                    selected.update(verified.store.put(b'substituted implementation'))
                with self.assertRaisesRegex(DevError, 'captured-runtime-(recipe|output)-drift'):
                    entropy.verify_capture(verified, runtime.ENTROPY)

    def test_local_same_name_and_unselected_profile_never_acquire_runtime_patch(self):
        local = {'format': 'directory', 'metadata': {'ecosystem': 'cargo', 'package': 'getrandom', 'version': '0.3.4'}}
        self.assertEqual(entropy.captured_changes(local, {}, runtime.ENTROPY), ({}, None))
        local['metadata']['vendorChecksum'] = {'package': entropy.GETRANDOM['archiveSha256']}
        self.assertEqual(entropy.captured_changes(local, {}, runtime.CLOSED), ({}, None))
        local['metadata']['vendorChecksum']['package'] = '0' * 64
        with self.assertRaisesRegex(DevError, 'unreviewed-runtime-package'):
            entropy.captured_changes(local, {}, runtime.ENTROPY)

    def test_explicit_creators_declare_random_and_preserve_logging_without_grants(self):
        from tools.rust_capsule_project import create, snapshot
        from tools.rust_capsule_build import validate_project
        for profile in (runtime.ENTROPY, runtime.LOGGING_ENTROPY):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                project = create(Path(temporary) / 'application', 'greeting', runtime_profile=profile)
                files = snapshot(project)
                descriptor, _ = validate_project(files)
                self.assertEqual(descriptor['runtimeProfile'], profile)
                self.assertNotIn('grants', descriptor)
                self.assertIn(b'import latent:random/random@0.1.0;', files['wit/world.wit'])
                self.assertEqual(files['wit/deps/random/package.wit'], (ROOT / 'wit/platform/random/package.wit').read_bytes())
                self.assertIn(b'"latent:random/random@0.1.0": latent_guest::bindings::random,', files['src/lib.rs'])
                self.assertEqual(b'import latent:log/log@0.1.0;' in files['wit/world.wit'], runtime.has_logging(profile))
    def test_native_core_lengths_lowering_failures_clearing_and_fresh_source_calls(self):
        rustc = shutil.which('rustc')
        self.assertIsNotNone(rustc, 'the maintained Rust toolchain is required')
        version = subprocess.check_output([rustc, '--version'], text=True, timeout=30)
        self.assertTrue(version.startswith('rustc 1.97.1 (8bab26f4f '), version)
        with tempfile.TemporaryDirectory(prefix='lsf-rust-entropy-reference-') as temporary:
            root = Path(temporary)
            source = root / 'reference.rs'
            code = (ROOT / 'sdk/rust-standard-runtime/entropy_core.rs').read_text()
            source.write_text(code + r'''
use core::sync::atomic::{AtomicUsize, Ordering};
static CALLS: AtomicUsize = AtomicUsize::new(0);
static FAIL_AT: AtomicUsize = AtomicUsize::new(0);
static ERROR: AtomicUsize = AtomicUsize::new(0);
#[unsafe(export_name="lsf_entropy_scalar")]
extern "C" fn provider(out: *mut ScalarResult) {
    assert_eq!(out as usize % 8, 0);
    let ordinal = CALLS.fetch_add(1, Ordering::SeqCst) + 1;
    unsafe {
        (*out).tag = u8::from(ordinal == FAIL_AT.load(Ordering::SeqCst));
        (*out).payload = if (*out).tag == 0 {0x0807060504030201} else {ERROR.load(Ordering::SeqCst) as u64};
    }
}
fn main() {
    assert_eq!(approved_fill(&mut []), Ok(()));
    assert_eq!(CALLS.load(Ordering::SeqCst), 0);
    let mut oversized = vec![0x5a; 65_537];
    assert_eq!(approved_fill(&mut oversized), Err(0));
    assert!(oversized.iter().all(|v| *v == 0x5a));
    assert_eq!(CALLS.load(Ordering::SeqCst), 0);
    for length in [1, 8, 9, 32, 257, 4096, 65_536] {
        CALLS.store(0, Ordering::SeqCst);
        let mut bytes=vec![0x5a; length + 2];
        assert_eq!(approved_fill(&mut bytes[1..length+1]), Ok(()));
        assert_eq!(CALLS.load(Ordering::SeqCst), length.div_ceil(8));
        for (i, value) in bytes[1..length+1].iter().enumerate() {assert_eq!(*value, (i%8+1) as u8);}
        assert_eq!(bytes[0], 0x5a); assert_eq!(bytes[length+1], 0x5a);
    }
    for error in 0..3 {
        ERROR.store(error, Ordering::SeqCst);
        for fail_at in [1, 33] {
            CALLS.store(0, Ordering::SeqCst); FAIL_AT.store(fail_at, Ordering::SeqCst);
            let mut bytes=[0x5a; 259];
            assert_eq!(approved_fill(&mut bytes[1..258]), Err(error as u8));
            assert_eq!(CALLS.load(Ordering::SeqCst), fail_at);
            assert!(bytes[1..258].iter().all(|v| *v == 0));
            assert_eq!(bytes[0], 0x5a); assert_eq!(bytes[258], 0x5a);
        }
    }
    FAIL_AT.store(0, Ordering::SeqCst); CALLS.store(0, Ordering::SeqCst);
    assert_eq!(approved_fill(&mut [0; 257]), Ok(()));
    assert_eq!(CALLS.load(Ordering::SeqCst), 33);
}
''', encoding='utf-8')
            binary = root / ('reference.exe' if __import__('os').name == 'nt' else 'reference')
            result = subprocess.run([rustc, '--edition=2024', str(source), '-o', str(binary)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
