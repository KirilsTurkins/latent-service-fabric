"""Exact-source admission for the one pinned Wasmtime allocation-hook fork."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from tools import ci_suite_inventory as registry, host_codec_wasmtime as source
from tools.native_runtime_build import dependency_inventory
from tools.native_runtime.common import InstallError


class PinnedWasmtimeSource(unittest.TestCase):
    def fixture(self, root):
        shutil.copytree(source.ROOT / source.PROVIDER, root / source.PROVIDER)
        shutil.copytree(source.ROOT / source.CACHE_PROVIDER, root / source.CACHE_PROVIDER)
        for name in ('Cargo.toml', 'Cargo.lock'):
            shutil.copyfile(source.ROOT / name, root / name)

    def test_exact_vendor_source_and_original_license_are_required_by_the_ci_graph(self):
        checked = source.verify()
        self.assertEqual(len(checked['files']), 275)
        self.assertEqual(checked['nativeCohort'], source.COHORT)
        self.assertEqual(checked['licenseFiles'], {'LICENSE': hashlib.sha256(
            (source.ROOT / source.PROVIDER / 'LICENSE').read_bytes()).hexdigest()})
        self.assertEqual(checked['additionalLicenseFiles'], {name: hashlib.sha256(
            (source.ROOT / source.PROVIDER / name).read_bytes()).hexdigest() for name in (
                'src/runtime/component/concurrent/host_futures/LICENSE-MIT',
                'src/runtime/component/concurrent/host_futures/LICENSE-APACHE')})
        graph = registry.workspace(source.ROOT)
        self.assertNotIn(source.NAME, graph)
        self.assertIn('latent-wasmtime', graph)
        with patch.object(source, 'verify', side_effect=ValueError('tampered-pinned-wasmtime')), \
                self.assertRaisesRegex(ValueError, 'tampered-pinned-wasmtime'):
            registry.workspace(source.ROOT)

    def test_original_patched_added_metadata_extra_and_missing_vendor_bytes_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            directory = root / source.PROVIDER
            for name in ('Cargo.toml', 'LICENSE', 'src/runtime/component/values.rs',
                         'src/runtime/component/dynamic_memory.rs', 'UPSTREAM.latent.json',
                         'src/runtime/component/concurrent/call_future.rs',
                         'src/runtime/component/concurrent/worker_function.rs',
                         'src/runtime/component/concurrent/work_queue.rs',
                         'src/runtime/component/concurrent/host_futures/paid_arc.rs',
                         'src/runtime/component/concurrent/host_futures/paid/task.rs',
                         'src/runtime/component/concurrent/host_futures/LICENSE-MIT',
                         'src/runtime/component/concurrent/host_futures/LICENSE-APACHE',
                         'src/runtime/component/concurrent/futures_and_streams.rs',
                         'src/runtime/component/concurrent/futures_and_streams/stream_outer_tests.rs',
                         'src/runtime/component/concurrent/pending_future.rs',
                         'README.latent.md', 'latent-dynamic-memory.patch'):
                with self.subTest(name=name):
                    target = directory / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-'):
                        source.verify(root)
                    target.write_bytes(original)
            extra = directory / 'foreign.rs'
            extra.write_text('foreign')
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                source.verify(root)
            extra.unlink()
            target = directory / 'LICENSE'
            target.unlink()
            with self.assertRaisesRegex(ValueError, 'source-identity'):
                source.verify(root)

    def test_cache_backport_complete_source_and_fixed_locks_are_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            checked = source.verify(root)
            cache = checked['cacheSecurityBackport']
            self.assertEqual(len(cache['files']), 14)
            self.assertEqual(cache['fixedRegistryPackages']['zstd-safe']['version'], '8.2.0')
            self.assertEqual(cache['fixedRegistryPackages']['zstd-sys']['version'], '2.1.2+zstd.1.5.7')
            directory = root / source.CACHE_PROVIDER
            for name in cache['files']:
                with self.subTest(name=name):
                    target = directory / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged\n')
                    with self.assertRaisesRegex(ValueError, 'cache-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            extra = directory / 'foreign.rs'
            extra.write_bytes(b'foreign')
            with self.assertRaisesRegex(ValueError, 'cache-source-identity'):
                source.verify(root)
            extra.unlink()
            shutil.rmtree(directory)
            with self.assertRaisesRegex(ValueError, 'cache-source-directory'):
                source.verify(root)

    def test_workspace_selection_isolation_global_override_and_registry_lock_are_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            target = root / 'Cargo.toml'
            original = target.read_bytes()
            document = tomllib.loads(original.decode())
            excluded = document['workspace']['exclude']
            needle = ('exclude = ' + json.dumps(excluded)).encode()
            self.assertEqual(original.count(needle), 1)
            mutations = (
                original.replace(needle, ('exclude = ' + json.dumps(
                    [name for name in excluded if name != source.PROVIDER])).encode(), 1),
                original.replace(b'path = "crates/vendor/wasmtime"', b'path = "foreign/wasmtime"', 1),
                original.replace(b'[patch.crates-io]\n', b'[patch.crates-io]\nwasmtime = {path="foreign"}\n', 1),
                original + b'\n[replace]\n"wasmtime:48.0.7" = {path="foreign"}\n')
            for raw in mutations:
                self.assertNotEqual(original, raw)
                target.write_bytes(raw)
                with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-'):
                    source.verify(root)
            target.write_bytes(original)
            lock = root / 'Cargo.lock'
            original = lock.read_bytes()
            needle = b'name = "wasmtime"\nversion = "48.0.7"\n'
            self.assertEqual(original.count(needle), 1)
            lock.write_bytes(original.replace(needle, needle + b'source = "registry+https://github.com/rust-lang/crates.io-index"\n', 1))
            with self.assertRaisesRegex(ValueError, 'lock-selection'):
                source.verify(root)

    def test_native_inventory_retains_original_license_and_distinct_fork_provenance(self):
        package = {'id': 'pinned-local', 'name': source.NAME, 'version': source.VERSION,
                   'source': None, 'license': 'Apache-2.0 WITH LLVM-exception',
                   'manifest_path': str(source.ROOT / source.PROVIDER / 'Cargo.toml')}
        metadata = {'packages': [package], 'resolve': {'nodes': [{'id': package['id'], 'deps': []}]}}
        lock = tomllib.loads((source.ROOT / 'Cargo.lock').read_text())
        sbom, licenses = dependency_inventory(metadata, lock, 'a' * 40, 0, {}, root_names=frozenset({source.NAME}))
        self.assertEqual(licenses, {f'licenses/wasmtime-48.0.7/{Path(name).name}':
            source.ROOT / source.PROVIDER / name for name in (
                *source.verify()['licenseFiles'], *source.verify()['additionalLicenseFiles'])})
        self.assertEqual(len(licenses), 3)
        self.assertIn(source.RECORD_SHA256, sbom['packages'][0]['comment'])
        self.assertIn(source.COHORT, sbom['packages'][0]['comment'])
        self.assertNotIn('checksums', sbom['packages'][0])
        for change in ({'version': '48.0.8'}, {'license': 'MIT'}, {'manifest_path': str(source.ROOT / 'Cargo.toml')}):
            with self.subTest(change=change), self.assertRaises(InstallError):
                dependency_inventory({**metadata, 'packages': [{**package, **change}]}, lock,
                    'a' * 40, 0, {}, root_names=frozenset({source.NAME}))

    def test_local_cache_inventory_retains_original_license_and_backport_identity(self):
        checked = source.verify()['cacheSecurityBackport']
        package = {'id': 'pinned-cache', 'name': checked['package'], 'version': source.VERSION,
                   'source': None, 'license': 'Apache-2.0 WITH LLVM-exception',
                   'manifest_path': str(source.ROOT / source.CACHE_PROVIDER / 'Cargo.toml')}
        metadata = {'packages': [package], 'resolve': {'nodes': [{'id': package['id'], 'deps': []}]}}
        lock = tomllib.loads((source.ROOT / source.CACHE_PROVIDER / 'Cargo.lock').read_text())
        sbom, licenses = dependency_inventory(metadata, lock, 'a' * 40, 0, {},
            root_names=frozenset({checked['package']}))
        self.assertEqual(licenses, {'licenses/wasmtime-internal-cache-48.0.7/LICENSE':
            source.ROOT / source.CACHE_PROVIDER / 'LICENSE'})
        self.assertIn(checked['upstreamSha256'], sbom['packages'][0]['comment'])
        self.assertIn(source.RECORD_SHA256, sbom['packages'][0]['comment'])
        self.assertNotIn('checksums', sbom['packages'][0])
        for change in ({'version': '48.0.8'}, {'license': 'MIT'},
                       {'manifest_path': str(source.ROOT / 'Cargo.toml')}):
            with self.subTest(change=change), self.assertRaises(InstallError):
                dependency_inventory({**metadata, 'packages': [{**package, **change}]}, lock,
                    'a' * 40, 0, {}, root_names=frozenset({checked['package']}))

    def test_unregistered_local_dependency_cannot_reuse_the_wasmtime_alias(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'member').mkdir()
            (root / 'foreign').mkdir()
            (root / 'Cargo.toml').write_text('[workspace]\nmembers=["member"]\n')
            (root / 'member/Cargo.toml').write_text('[package]\nname="member"\nversion="0.1.0"\n[dependencies]\nwasmtime={path="../foreign"}\n')
            with self.assertRaisesRegex(ValueError, 'unregistered-path-dependency'):
                registry.workspace(root)

    def test_actual_table_hook_sources_and_new_cohort_require_exact_postimages(self):
        self.assertEqual(source.COHORT, 'wasmtime-48.0.7-latent-value-table-store-registry-funcrefs-resource-types-linear-notification-retained-context-host-future-owned-reply-join-state-call-future-pending-continuation-worker-function-queue-nodes-unordered-futures-outer-sync-result-stream-outers-consumer-producer-factories-http-ingress-memory-v22-lift-result-memory-cache-repair')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name in ('src/runtime/limits.rs', 'src/runtime/store.rs',
                         'src/runtime/vm/table.rs',
                         'src/runtime/vm/instance/allocator/pooling/table_pool.rs'):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged-table-owner\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(source.verify(root)['nativeCohort'], source.COHORT)


    def test_store_header_binding_and_guarded_buffer_postimages_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name in ('src/runtime/component/concurrent.rs',
                         'src/runtime/native_memory.rs', 'src/runtime/vm/instance.rs',
                         'src/runtime/vm/component.rs', 'src/runtime/component/store.rs',
                         'src/runtime/store/data.rs', 'src/runtime/vm/component/resources.rs',
                         'src/runtime/vm/instance/allocator.rs', 'src/runtime.rs', 'src/runtime/module.rs',
                         'src/runtime/module/registry.rs', 'src/runtime/module/native_registry.rs'):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged-store-owner\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)

    def test_funcrefs_stable_arena_and_directory_sources_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name in ('src/runtime/store/func_refs.rs',
                         'src/runtime/store/func_refs/native.rs',
                         'src/runtime/func.rs', 'src/runtime/instance.rs',
                         'src/runtime/linker.rs'):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged-funcref-owner\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)


    def test_resource_substitution_map_and_escape_ownership_sources_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name in ('src/runtime/component/resource_types.rs',
                         'src/runtime/component/instance.rs',
                         'src/runtime/component/linker.rs',
                         'src/runtime/component/matching.rs',
                         'src/runtime/component/types.rs',
                         'src/runtime/component/mod.rs',
                         'src/runtime/vm/component.rs',
                         'src/runtime/native_memory.rs'):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged-resource-owner\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)


    def test_actual_linear_allocator_notifications_cannot_be_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name in ('src/runtime/limits.rs', 'src/runtime/store.rs',
                         'src/runtime/vm/memory.rs'):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    target.write_bytes(original + b'\nchanged-linear-notification\n')
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)


    def test_per_call_host_future_owner_requires_its_exact_source_postimage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            target = root / source.PROVIDER / 'src/runtime/component/func/host.rs'
            original = target.read_bytes()
            self.assertIn(b'future: Box::pin(future)', original)
            target.write_bytes(original.replace(b'future: Box::pin(future)', b'future: unreviewed_future(future)', 1))
            with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                source.verify(root)
            target.write_bytes(original)
            for name, token in (
                ('src/runtime/component/concurrent/abort.rs', b'self.inner.take().and_then(Arc::into_inner)'),
                ('src/runtime/component/concurrent.rs', b'JoinHandle::run_with_memory'),
            ):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    self.assertIn(token, original)
                    target.write_bytes(original.replace(token, b'unreviewed_join_cell', 1))
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)


    def test_owned_context_reply_lowering_requires_exact_guard_and_public_entrypoint_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            for name, token in (
                ('src/runtime/component/func/host.rs', b'let result = lower(&self.value);'),
                ('src/runtime/component/linker.rs', b'pub fn func_wrap_async_owned<Params, Return, F>'),
                ('src/runtime/component/mod.rs', b'HostOutput'),
            ):
                with self.subTest(name=name):
                    target = root / source.PROVIDER / name
                    original = target.read_bytes()
                    self.assertIn(token, original)
                    target.write_bytes(original.replace(token, b'unreviewed_owned_reply', 1))
                    with self.assertRaisesRegex(ValueError, 'host-codec-wasmtime-source-identity'):
                        source.verify(root)
                    target.write_bytes(original)
            self.assertEqual(len(source.verify(root)['files']), 275)


if __name__ == '__main__':
    unittest.main()
