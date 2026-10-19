"""Pinned PAL/profile/input controls; no rebuilt-std or signed-node claim."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from tools import rust_capsule_build as build, rust_capsule_project as project
from tools import rust_standard_logging_inputs as inputs, rust_standard_logging_profile as profile
from tools import rust_standard_sysroot_build as std
from tools.build_observation import file_identity
from tools.dev_workflow.common import DevError, encode

ROOT = Path(__file__).resolve().parents[2]


class StandardLogging(unittest.TestCase):
    def originals(self):
        return {name: (ROOT / 'sdk/rust-standard-runtime/upstream' / name).read_bytes()
                for name in profile.ORIGINALS}

    def test_exact_source_changes_only_target_stdio_and_stdout_buffering(self):
        original = self.originals()
        pal = (ROOT / 'sdk/rust-standard-runtime/stdio_logging.rs').read_bytes()
        selected = profile.overlay(original, pal)
        self.assertEqual(set(selected), {'std/src/sys/stdio/mod.rs', 'std/src/sys/stdio/lsf.rs', 'std/src/io/stdio.rs'})
        self.assertEqual(selected['std/src/sys/stdio/lsf.rs'], pal)
        for name, raw in original.items():
            self.assertEqual(hashlib.sha256(raw).hexdigest(), profile.ORIGINALS[name])
        stdout = selected['std/src/io/stdio.rs']
        buffered = b'LineWriter::new(stdout_raw())'
        new = b'if cfg!(' + profile.SELECTOR + b') { LineWriter::with_capacity(0, stdout_raw()) } else { ' + buffered + b' }'
        self.assertEqual(stdout.replace(new, buffered, 1), original['std/src/io/stdio.rs'])
        self.assertIn(b'mod unsupported;', selected['std/src/sys/stdio/mod.rs'])

    def test_changed_missing_or_extra_source_preimage_cannot_be_selected(self):
        for name in profile.ORIGINALS:
            original = self.originals(); original[name] += b'\n'
            with self.subTest(name=name), self.assertRaisesRegex(DevError, 'original-preimage'):
                profile.overlay(original, b'PAL')
        for alter in ('missing', 'extra'):
            original = self.originals()
            if alter == 'missing': original.pop(next(iter(original)))
            else: original['another.rs'] = b'unknown'
            with self.assertRaisesRegex(DevError, 'original-set'): profile.overlay(original, b'PAL')

    def test_default_maintained_overlay_is_closed_and_logging_never_implicitly_selected(self):
        files = {name: (ROOT / name).read_bytes() for name in profile.RECIPE}
        selected = profile.selected(self.originals(), files)
        self.assertEqual(selected['std/src/sys/stdio/lsf.rs'], files['sdk/rust-standard-runtime/stdio_closed.rs'])
        selected = profile.selected(self.originals(), files, logging=True)
        self.assertEqual(selected['std/src/sys/stdio/lsf.rs'], files['sdk/rust-standard-runtime/stdio_logging.rs'])
        for value in (1, 'true', None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(DevError, 'selection-invalid'):
                profile.selected(self.originals(), files, logging=value)

    def test_creator_selects_fixed_sdk_bridge_and_declares_log_without_any_grant(self):
        with tempfile.TemporaryDirectory() as directory:
            source = project.create(Path(directory) / 'source', 'greeting', runtime_profile=inputs.PROFILE)
            files = project.snapshot(source)
            descriptor, _pins = build.validate_project(files)
            self.assertEqual(descriptor['runtimeProfile'], inputs.PROFILE)
            self.assertEqual(descriptor['limits']['logBytes'], 0)
            self.assertNotIn('grants', descriptor)
            self.assertIn(b'import latent:log/log@0.1.0;', files['wit/world.wit'])
            self.assertEqual(files['wit/deps/log/package.wit'], (ROOT / 'wit/platform/log/package.wit').read_bytes())
            self.assertIn(b'features = ["standard-logging"]', files['Cargo.toml'])
            self.assertIn('vendor/lsf/sdk/rust-standard-stdio/src/lib.rs', files)
            self.assertIn(b'#![forbid(unsafe_code)]', files['vendor/lsf/sdk/rust-guest/src/lib.rs'])
            with self.assertRaisesRegex(ValueError, 'requires its owned'):
                build.build(source, Path(directory) / 'output', Path(directory) / 'absent', None,
                            'https://example.invalid/source')
            self.assertFalse((Path(directory) / 'output').exists())

    def test_unknown_or_malformed_project_profile_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ('unknown', 1, True, [], {}, None):
                target = Path(directory) / 'source'
                with self.subTest(value=value), self.assertRaisesRegex(DevError, 'runtime-profile'):
                    project.create(target, 'greeting', runtime_profile=value if value is not None else 'null')
                self.assertFalse(target.exists())

    def prepared(self, root):
        compiler = root / 'rustc'; compiler.write_bytes(b'controlled compiler identity, never invoked')
        prepared = root / 'prepared'
        directory = prepared / 'sysroot/lib/rustlib' / std.clock.TARGET / 'lib'
        directory.mkdir(parents=True)
        libraries = {}
        for crate in ('std', 'core', 'alloc', 'panic_abort', 'compiler_builtins'):
            name, raw = 'lib' + crate + '-current.rlib', crate.encode()
            (directory / name).write_bytes(raw)
            libraries[name] = {'digest': project.digest(raw), 'size': len(raw), 'crate': crate, 'package': crate}
        value = {'schemaVersion': 'latent.rust.std-built-source.v1', 'profile': std.LOGGING_PROFILE,
            'standardStdio': 'typed-log-v1', 'target': std.clock.TARGET, 'rust': std.clock.RUST,
            'rustCommit': std.clock.RUST_COMMIT, 'archiveDigest': 'sha256:' + std.clock.SOURCE_ARCHIVE_SHA256,
            'recipeDigest': project.digest(project.inventory({n: (ROOT / n).read_bytes() for n in dict.fromkeys(std.RECIPE)})),
            'tools': {'rustc': file_identity(compiler, 'rustc')}, 'rustFlags': std.FLAGS,
            'qualification': 'built-source-only', 'installedCompilerChanged': False, 'libraries': libraries,
            'originalInputsDigest': project.digest(b'controlled original'), 'selectedInputsDigest': project.digest(b'controlled selected')}
        self.publish(prepared, value)
        return prepared, compiler, value

    def publish(self, prepared, value):
        value['identity'] = project.digest(encode({k: v for k, v in value.items() if k != 'identity'}))
        (prepared / 'std-sysroot-build.json').write_bytes(encode(value))

    def test_prepared_exact_graph_has_target_only_flag_and_bound_source_material(self):
        self.assertLessEqual(set(std.RECIPE), set(build.RECIPE))
        with tempfile.TemporaryDirectory() as directory:
            prepared, compiler, value = self.prepared(Path(directory))
            selected = inputs.Prepared(prepared, compiler)
            selected.check()
            arguments = selected.arguments()
            self.assertEqual(arguments[0], '--config')
            key, array = arguments[1].split('=', 1)
            self.assertEqual(key, 'target.wasm32-unknown-unknown.rustflags')
            self.assertEqual(json.loads(array), ['--sysroot=' + str(prepared / 'sysroot')])
            record = json.loads(selected.material())
            self.assertEqual(record['preparedBuildIdentity'], value['identity'])
            self.assertEqual(record['libraries'], value['libraries'])
            self.assertEqual(record['authority'], 'none')
            self.assertFalse(record['publisherAuthentication'])

    def test_changed_library_compiler_recipe_or_extra_input_never_reuses_prepared_graph(self):
        for mutation in ('library', 'compiler', 'recipe', 'extra', 'extra-parent'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                prepared, compiler, value = self.prepared(Path(directory))
                if mutation == 'library': next((prepared / 'sysroot/lib/rustlib' / std.clock.TARGET / 'lib').iterdir()).write_bytes(b'changed')
                elif mutation == 'compiler': compiler.write_bytes(b'changed')
                elif mutation == 'recipe': value['recipeDigest'] = project.digest(b'older recipe'); self.publish(prepared, value)
                elif mutation == 'extra': (prepared / 'sysroot/lib/rustlib' / std.clock.TARGET / 'lib/extra.rlib').write_bytes(b'extra')
                else: (prepared / 'sysroot/ambient').write_bytes(b'extra')
                with self.assertRaisesRegex(DevError, 'rust-standard-runtime-'):
                    inputs.Prepared(prepared, compiler)

    def test_receipt_mutation_is_detected_even_if_updated_document_identity_is_consistent(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared, compiler, value = self.prepared(Path(directory))
            selected = inputs.Prepared(prepared, compiler)
            value['selectedInputsDigest'] = project.digest(b'another selection')
            self.publish(prepared, value)
            with self.assertRaisesRegex(DevError, 'receipt-mutated'): selected.check()

    def test_closed_prepared_profile_cannot_be_relabelled_as_logging(self):
        with tempfile.TemporaryDirectory() as directory:
            prepared, compiler, value = self.prepared(Path(directory))
            value['profile'], value['standardStdio'] = std.PROFILE, 'explicit-unsupported-v1'
            self.publish(prepared, value)
            inputs.Prepared(prepared, compiler, inputs.CLOSED).check()
            with self.assertRaisesRegex(DevError, 'prepared-profile'):
                inputs.Prepared(prepared, compiler, inputs.PROFILE)
            created = project.create(Path(directory) / 'closed-project', 'greeting', runtime_profile=inputs.CLOSED)
            files = project.snapshot(created)
            descriptor, _pins = build.validate_project(files)
            self.assertEqual(descriptor['runtimeProfile'], inputs.CLOSED)
            self.assertNotIn(b'standard-logging', files['Cargo.toml'])
            self.assertNotIn(b'latent:log', files['wit/world.wit'])

    def test_uncaptured_profile_receipt_is_verified_against_actual_project_selection(self):
        from tools import guest_runtime_receipts as receipts
        files = {'capsule-project.json': encode({'runtimeProfile': inputs.PROFILE}),
                 'vendor/lsf/sdk/rust-guest/src/lib.rs': b'captured SDK source',
                 'wit/world.wit': b'package outside:stdio@0.1.0; world guest {}'}
        source = project.inventory(files)
        component = b'controlled component identity, not executed'
        materials = [{'name': 'build-recipe', 'digest': project.digest(b'current recipe'), 'size': 14}]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            receipts.emit(output, 'rust', inputs.PROFILE, files, source, component, materials,
                graph=None, binding_digest=project.digest(b'bindings'), configuration={'profile': inputs.PROFILE})
            value = project.read_json(output / 'standard-runtime-selection.json')
            receipts.verify_build(value, 'rust', files, source, component, materials)
            changed = {**files, 'capsule-project.json': encode({'runtimeProfile': inputs.CLOSED})}
            with self.assertRaisesRegex(DevError, 'stale-'):
                receipts.verify_build(value, 'rust', changed, project.inventory(changed), component, materials)


if __name__ == '__main__': unittest.main()
