"""Normal source capture/selection controls; no compiled Rust runtime is claimed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import application_dependencies as dependencies
from tools import rust_capsule_build as build, rust_capsule_project as project
from tools import rust_standard_logging_inputs as standard
from tools import rust_standard_thread_capture as capture
from tools import rust_owned_thread_component as component
from tools.application_dependency_store import tree_identity
from tools.build_snapshot import canonical, digest
from tools.dev_workflow.common import DevError, encode


class StandardThreadCapture(unittest.TestCase):
    def package(self):
        root = project.ROOT / 'sdk/rust-standard-runtime/upstream/futures-executor-0.3.31'
        # Authentic selector/support preimages plus a source-only manifest
        # fixture. This is not a complete compiled published-crate control.
        files = {name: (root / name).read_bytes() for name in capture.profile.EXECUTOR_ORIGINALS}
        files['Cargo.toml'] = b'[package]\nname="futures-executor"\nversion="0.3.31"\n'
        files['.cargo-checksum.json'] = canonical({
            'package': capture.profile.EXECUTOR_ARCHIVE_SHA256,
            'files': {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()}})
        return files

    def artifact(self):
        return {'id': 'ordinary-runtime', 'role': 'runtime', 'format': 'directory',
                'mount': 'dependencies/cargo-vendor/futures-executor', 'source': {'path': 'original'},
                'dependencies': [], 'metadata': {'ecosystem': 'cargo', 'package': 'futures-executor',
                    'version': '0.3.31', 'vendorChecksum': {'package': capture.profile.EXECUTOR_ARCHIVE_SHA256}}}

    def test_real_generic_replacement_capture_materializes_and_rechecks_inline_runtime_from_original_cas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); files = self.package(); row = self.artifact()
            changes, material = capture.captured_changes(row, files, standard.THREAD)
            self.assertEqual(set(changes), {'src/lib.rs', '.cargo-checksum.json'})
            self.assertFalse(material['canonicalThreadRuntimeQualified'])
            self.assertFalse(material['privateExecutorGraphAuthenticated'])
            for name, raw in files.items():
                path = root / 'original' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
            rows = lambda values: [{'path': name, 'digest': digest(raw), 'size': len(raw)}
                                   for name, raw in sorted(values.items())]
            transformed = []
            for name, raw in changes.items():
                path = root / 'replacement' / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
                transformed.append({'path': name, 'inputDigest': digest(files[name]),
                    'source': 'replacement/' + name, 'outputDigest': digest(raw)})
            manifest = {'formatVersion': 1, 'language': 'rust', 'selection': {'runtimeProfile': standard.THREAD},
                'nativeLocks': [], 'artifacts': [row], 'transformations': [{
                    'id': 'selected-ordinary-runtime', 'artifact': row['id'],
                    'inputDigest': tree_identity(rows(files)), 'outputDigest': tree_identity(rows({**files, **changes})),
                    'files': transformed, 'tool': {'name': 'selected-runtime-source'},
                    'selection': {'runtimeThreadPort': material}}]}
            (root / dependencies.MANIFEST).write_bytes(canonical(manifest))
            locked = dependencies.capture(root)
            (root / dependencies.LOCK).write_bytes(canonical(locked))
            verified = dependencies.verify_inputs(root, 'rust')
            capture.verify_capture(verified, standard.THREAD)
            work, output = root / 'work', root / 'output'; work.mkdir(); output.mkdir()
            closure = dependencies.prepare(root, work, output, 'rust')
            closure.check_unchanged()
            selected = work / row['mount']
            self.assertEqual({path.relative_to(selected).as_posix() for path in selected.rglob('*') if path.is_file()}, set(files))
            self.assertEqual((selected / 'src/lib.rs').read_bytes(), changes['src/lib.rs'])
            for name in ('src/thread_pool.rs', 'src/unpark_mutex.rs', 'src/enter.rs'):
                self.assertEqual((selected / name).read_bytes(), files[name])
            with self.assertRaisesRegex(DevError, 'without-selected-profile'):
                capture.verify_capture(verified, standard.CLOSED)
            # A caller-changed output CAS object cannot reuse the recorded
            # source recipe or turn this source result into runtime authority.
            target = next(item for item in verified.lock['artifacts'][0]['files'] if item['path'] == 'src/lib.rs')
            target.update(verified.store.put(changes['src/lib.rs'] + b'changed'))
            with self.assertRaisesRegex(DevError, 'output-drift'):
                capture.verify_capture(verified, standard.THREAD)

    def test_unselected_local_same_name_unknown_version_and_vendor_tampering_do_not_gain_port(self):
        row = self.artifact(); files = self.package()
        self.assertEqual(capture.captured_changes(row, files, standard.CLOSED), ({}, None))
        local = self.artifact(); local['metadata'].pop('vendorChecksum')
        self.assertEqual(capture.captured_changes(local, files, standard.THREAD), ({}, None))
        for change in ('version', 'archive', 'checksum', 'source'):
            row = self.artifact(); altered = dict(files)
            if change == 'version': row['metadata']['version'] = '0.3.32'
            elif change == 'archive': row['metadata']['vendorChecksum']['package'] = '0' * 64
            elif change == 'checksum': altered['.cargo-checksum.json'] = b'{}'
            else: altered['src/unpark_mutex.rs'] += b'changed'
            with self.subTest(change=change), self.assertRaises(DevError):
                capture.captured_changes(row, altered, standard.THREAD)

    def test_ordinary_creator_keeps_application_source_limits_and_grants_while_component_gate_stays_closed(self):
        self.assertEqual(capture.APPLICATION_PROFILE, standard.THREAD)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = project.create(root / 'original', 'greeting', 'ordinary-source')
            selected = project.create(root / 'selected', 'greeting', 'ordinary-source', runtime_profile=standard.THREAD)
            before, after = project.snapshot(original), project.snapshot(selected)
            descriptor, _ = build.validate_project(after)
            self.assertEqual(descriptor['runtimeProfile'], standard.THREAD)
            opening = b'wit_bindgen::generate!({'
            # Exact generator configuration is the sole source change; the
            # ordinary application function and all public calls stay intact.
            self.assertEqual(after['src/lib.rs'], before['src/lib.rs'].replace(
                opening, opening + b' generate_all,', 1))
            self.assertEqual(after['src/lib.rs'].split(b'#[cfg(target_arch', 1)[0],
                             before['src/lib.rs'].split(b'#[cfg(target_arch', 1)[0])
            self.assertEqual(after['Cargo.toml'], before['Cargo.toml'])
            self.assertEqual(descriptor['limits'], json.loads(before['capsule-project.json'])['limits'])
            self.assertNotIn('grants', descriptor)
            for name in ('latent:runtime/activation@0.1.0', 'latent:runtime-native/threads@0.1.0',
                         'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'):
                self.assertEqual(after['wit/world.wit'].count(('import ' + name + ';').encode()), 1)
            with self.assertRaisesRegex(ValueError, 'private-executor-and-canonical-graph-unqualified'):
                component.select({'privateExecutorGraphAuthenticated': True}, root / 'absent-rustc')

    def test_thread_prepared_input_keeps_exact_current_recipe_flags_and_source_only_status(self):
        from tools.tests.test_rust_standard_logging import StandardLogging
        from tools import rust_standard_sysroot_build as std
        fixture = StandardLogging()
        with tempfile.TemporaryDirectory() as directory:
            prepared, compiler, value = fixture.prepared(Path(directory))
            value.update(profile=std.THREAD_PROFILE, standardStdio='explicit-unsupported-v1',
                standardThreads=capture.profile.PROFILE, standardThreadSourceSelected=True,
                standardThreadRuntimeQualified=False,
                recipeDigest=digest(project.inventory({name: (project.ROOT / name).read_bytes()
                    for name in std.recipe(threads=True)})))
            fixture.publish(prepared, value)
            selected = standard.Prepared(prepared, compiler, standard.THREAD)
            selected.check()
            flags = json.loads(selected.arguments()[1].split('=', 1)[1])
            self.assertEqual(flags[0], '--sysroot=' + str(prepared / 'sysroot'))
            self.assertIn('-Clink-arg=--export=__lsf_rust_owned_thread_entry', flags)
            self.assertTrue(set(capture.RECIPE) <= set(standard.source_build_inputs(standard.THREAD)))
            for key, changed in (('recipeDigest', digest(b'older recipe')),
                                 ('standardThreadRuntimeQualified', True), ('standardThreadSourceSelected', False)):
                altered = {**value, key: changed}; fixture.publish(prepared, altered)
                with self.subTest(key=key), self.assertRaises(DevError):
                    standard.Prepared(prepared, compiler, standard.THREAD)


if __name__ == '__main__': unittest.main()
